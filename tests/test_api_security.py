import asyncio
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.api import (
    app,
    create_content,
    get_state,
    get_trend_run,
    list_trend_runs,
    trend_research,
)
from marketing_machine.auth import (
    LOCAL_DEV_DISABLED_MODE,
    MUTATION_AUTH_MODE_ENV,
    MUTATION_TOKEN_ENV,
    MUTATION_TOKEN_FILE_ENV,
    MutationAuthorizationError,
    authorize_mutation,
)
from marketing_machine.storage import JsonStore
from marketing_machine.trend_research import trend_request_fingerprint, trend_request_run_id


class MutationAuthorizationTests(unittest.TestCase):
    token = "test-only-" + "high-entropy-" + "mutation-token-123456789"

    def test_direct_mutations_reject_missing_and_mismatched_tokens_but_accept_valid_token(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                MUTATION_TOKEN_ENV: self.token,
                MUTATION_AUTH_MODE_ENV: "required",
            },
            clear=False,
        ):
            with TestClient(app) as client:
                missing = client.post("/workflows/comfyui-brief", json={"campaign": "K1"})
                mismatched = client.post(
                    "/workflows/comfyui-brief",
                    json={"campaign": "K1"},
                    headers={"X-WAMOCON-Mutation-Token": "wrong-token"},
                )
                valid = client.post(
                    "/workflows/comfyui-brief",
                    json={"campaign": "K1"},
                    headers={"X-WAMOCON-Mutation-Token": self.token},
                )

            self.assertEqual(missing.status_code, 401)
            self.assertEqual(mismatched.status_code, 401)
            self.assertEqual(valid.status_code, 200)
            event_path = Path(tmp) / "events" / "comfyui_brief.jsonl"
            self.assertEqual(len(event_path.read_text(encoding="utf-8").splitlines()), 1)
            self.assertNotIn(self.token, missing.text + mismatched.text + valid.text)

    def test_authenticated_mutation_body_is_bounded_before_json_parsing(self):
        oversized = b"x" * (1024 * 1024 + 1)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                MUTATION_TOKEN_ENV: self.token,
                MUTATION_AUTH_MODE_ENV: "required",
            },
            clear=False,
        ), TestClient(app) as client:
            response = client.post(
                "/workflows/comfyui-brief",
                content=oversized,
                headers={
                    "Content-Type": "application/json",
                    "X-WAMOCON-Mutation-Token": self.token,
                },
            )
            event_written = (Path(tmp) / "events" / "comfyui_brief.jsonl").exists()

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"], "request body is too large")
        self.assertFalse(event_written)

    def test_every_registered_state_changing_route_is_denied_before_validation(self):
        mutating_methods = {"POST", "PUT", "PATCH", "DELETE"}
        registered = [
            (method, re.sub(r"\{[^}]+\}", "auth-test-id", route.path))
            for route in app.routes
            for method in sorted((getattr(route, "methods", set()) or set()) & mutating_methods)
        ]
        self.assertTrue(registered)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                MUTATION_TOKEN_ENV: self.token,
                MUTATION_AUTH_MODE_ENV: "required",
            },
            clear=False,
        ):
            with TestClient(app) as client:
                responses = [client.request(method, path, json={}) for method, path in registered]

        self.assertTrue(all(response.status_code == 401 for response in responses))

    def test_public_health_reads_remain_open_but_business_reads_require_token(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                MUTATION_TOKEN_ENV: self.token,
                MUTATION_AUTH_MODE_ENV: "required",
            },
            clear=False,
        ):
            with TestClient(app) as client:
                health = client.get("/healthz")
                states = client.get("/workflows/states")
                authorized_states = client.get(
                    "/workflows/states",
                    headers={"X-WAMOCON-Mutation-Token": self.token},
                )
                readiness = client.get("/readyz")

            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()["instance"]["mode"], "production")
            self.assertFalse(health.json()["instance"]["disposable_data"])
            self.assertEqual(states.status_code, 401)
            self.assertEqual(authorized_states.status_code, 200)
            self.assertEqual(readiness.status_code, 503)
            self.assertFalse(readiness.json()["actor_authentication"]["production_ready"])
            self.assertEqual(readiness.json()["mutation_authorization"]["status"], "protected")

    def test_candidate_marker_requires_mode_namespace_and_disposable_flag_together(self):
        environment = {
            "MARKETING_MACHINE_INSTANCE_MODE": "isolated-candidate",
            "MARKETING_MACHINE_DATA_NAMESPACE": "candidate-security-test",
            "MARKETING_MACHINE_DISPOSABLE_DATA": "true",
        }
        with patch.dict(os.environ, environment, clear=False), TestClient(app) as client:
            candidate = client.get("/healthz").json()["instance"]
        self.assertEqual(candidate["mode"], "isolated-candidate")
        self.assertEqual(candidate["data_namespace"], "candidate-security-test")
        self.assertTrue(candidate["disposable_data"])

        with patch.dict(
            os.environ,
            {**environment, "MARKETING_MACHINE_DATA_NAMESPACE": "production-nvidia1"},
            clear=False,
        ), TestClient(app) as client:
            mismatched = client.get("/healthz").json()["instance"]
        self.assertFalse(mismatched["disposable_data"])

    def test_missing_configuration_blocks_mutation_and_marks_readiness_unsafe(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                MUTATION_TOKEN_ENV: "",
                MUTATION_AUTH_MODE_ENV: "required",
            },
            clear=False,
        ):
            with TestClient(app) as client:
                mutation = client.post("/workflows/comfyui-brief", json={})
                readiness = client.get("/readyz")

            self.assertEqual(mutation.status_code, 503)
            self.assertEqual(readiness.status_code, 503)
            self.assertEqual(readiness.json()["status"], "unsafe")
            self.assertEqual(
                readiness.json()["mutation_authorization"]["status"],
                "blocked_missing_token",
            )
            self.assertFalse((Path(tmp) / "events" / "comfyui_brief.jsonl").exists())

    def test_explicit_disabled_mode_is_loopback_only_and_still_not_ready(self):
        environment = {
            MUTATION_TOKEN_ENV: "",
            MUTATION_AUTH_MODE_ENV: LOCAL_DEV_DISABLED_MODE,
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"MARKETING_MACHINE_DATA_DIR": tmp, **environment},
            clear=False,
        ):
            async def exercise_loopback_client():
                transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 41000))
                async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
                    return (
                        await client.post("/workflows/comfyui-brief", json={}),
                        await client.get("/readyz"),
                    )

            local_mutation, readiness = asyncio.run(exercise_loopback_client())

        self.assertEqual(local_mutation.status_code, 200)
        self.assertEqual(readiness.status_code, 503)
        self.assertEqual(
            readiness.json()["mutation_authorization"]["status"],
            "unsafe_local_dev_only",
        )
        with self.assertRaises(MutationAuthorizationError) as remote:
            authorize_mutation(None, client_host="192.0.2.20", env=environment)
        self.assertEqual(remote.exception.status_code, 403)

    def test_secret_file_token_protects_mutations_without_exposing_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "mutation-token"
            token_path.write_text(self.token + "\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "MARKETING_MACHINE_DATA_DIR": tmp,
                    "MARKETING_MACHINE_INSTANCE_MODE": "development",
                    MUTATION_TOKEN_ENV: "",
                    MUTATION_TOKEN_FILE_ENV: str(token_path),
                    MUTATION_AUTH_MODE_ENV: "required",
                },
                clear=False,
            ):
                with TestClient(app) as client:
                    accepted = client.post(
                        "/workflows/comfyui-brief",
                        json={},
                        headers={"X-WAMOCON-Mutation-Token": self.token},
                    )
                    readiness = client.get("/readyz")

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(readiness.status_code, 200)
        self.assertEqual(
            readiness.json()["mutation_authorization"]["token_source"],
            "secret_file",
        )
        self.assertNotIn(self.token, readiness.text)

    def test_short_or_placeholder_token_never_makes_readiness_safe(self):
        for weak_token in ("x", "changeme", "replace-with-random-secret"):
            with self.subTest(weak_token=weak_token), patch.dict(
                os.environ,
                {
                    MUTATION_TOKEN_ENV: weak_token,
                    MUTATION_AUTH_MODE_ENV: "required",
                    MUTATION_TOKEN_FILE_ENV: "",
                },
                clear=False,
            ):
                with TestClient(app) as client:
                    mutation = client.post(
                        "/workflows/comfyui-brief",
                        json={},
                        headers={"X-WAMOCON-Mutation-Token": weak_token},
                    )
                    readiness = client.get("/readyz")

                self.assertEqual(mutation.status_code, 503)
                self.assertEqual(readiness.status_code, 503)
                self.assertEqual(
                    readiness.json()["mutation_authorization"]["status"],
                    "blocked_weak_token",
                )


class ApiTransportSecurityTests(unittest.TestCase):
    edge_attestation = "a" * 64
    mutation_token = "b" * 64

    def test_production_never_reports_ready_or_accepts_sensitive_work_without_named_actor_auth(self):
        environment = {
            "MARKETING_MACHINE_INSTANCE_MODE": "production",
            "MARKETING_MACHINE_MUTATION_AUTH_MODE": "required",
            "MARKETING_MACHINE_MUTATION_TOKEN": self.mutation_token,
            "MARKETING_MACHINE_ACTOR_AUTH_MODE": "local-optional",
            "MARKETING_MACHINE_EDGE_ATTESTATION": "",
            "MARKETING_MACHINE_EDGE_ATTESTATION_FILE": "",
        }
        with patch.dict(os.environ, environment, clear=False), TestClient(app) as client:
            readiness = client.get("/readyz")
            sensitive = client.post(
                "/workflows/approve-content",
                json={},
                headers={"X-WAMOCON-Mutation-Token": self.mutation_token},
            )

        self.assertEqual(readiness.status_code, 503)
        self.assertEqual(readiness.json()["status"], "unsafe")
        self.assertFalse(readiness.json()["actor_authentication"]["production_ready"])
        self.assertIn(sensitive.status_code, {401, 503})

    def test_dynamic_console_and_api_responses_are_never_cacheable(self):
        with TestClient(app) as client:
            console = client.get("/ui")
            health = client.get("/healthz")
            static_asset = client.get("/static/console.css")

        for response in (console, health):
            self.assertEqual(response.headers["cache-control"], "no-store, max-age=0")
            self.assertEqual(response.headers["pragma"], "no-cache")
            self.assertEqual(response.headers["expires"], "0")
            self.assertNotIn("access-control-allow-origin", response.headers)
        self.assertNotIn("no-store", static_asset.headers.get("cache-control", ""))

    def test_framework_documentation_is_hidden_except_in_explicit_dev_mode(self):
        with patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_INSTANCE_MODE": "production",
                "MARKETING_MACHINE_ENABLE_TECHNICAL_DOCS": "true",
            },
            clear=False,
        ), TestClient(app) as client:
            production_openapi = client.get("/openapi.json")
            production_docs = client.get("/docs")
            production_redoc_slash = client.get("/redoc/")

        self.assertEqual(production_openapi.status_code, 404)
        self.assertEqual(production_docs.status_code, 404)
        self.assertEqual(production_redoc_slash.status_code, 404)
        self.assertEqual(production_openapi.headers["cache-control"], "no-store, max-age=0")

        with patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_INSTANCE_MODE": "development",
                "MARKETING_MACHINE_ENABLE_TECHNICAL_DOCS": "true",
            },
            clear=False,
        ), TestClient(app) as client:
            development_openapi = client.get("/openapi.json")
            development_docs = client.get("/docs")

        self.assertEqual(development_openapi.status_code, 200)
        self.assertEqual(development_docs.status_code, 200)

    def test_unlisted_and_wildcard_hosts_fail_closed_but_exact_hosts_work(self):
        async def request(base_url: str):
            transport = httpx.ASGITransport(app=app, client=("192.0.2.30", 41000))
            async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
                return await client.get("/healthz")

        with patch.dict(
            os.environ,
            {"MARKETING_MACHINE_ALLOWED_HOSTS": "dashboard.internal"},
            clear=False,
        ):
            accepted = asyncio.run(request("http://dashboard.internal"))
            rejected = asyncio.run(request("http://unlisted.internal"))

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(rejected.headers["cache-control"], "no-store, max-age=0")

        with patch.dict(
            os.environ,
            {"MARKETING_MACHINE_ALLOWED_HOSTS": "*.internal"},
            clear=False,
        ):
            invalid_policy = asyncio.run(request("http://localhost"))
        self.assertEqual(invalid_policy.status_code, 503)

    def test_only_attested_one_hop_forwarding_changes_redirect_authority(self):
        environment = {
            "MARKETING_MACHINE_ACTOR_AUTH_MODE": "required",
            "MARKETING_MACHINE_EDGE_ATTESTATION": self.edge_attestation,
            "MARKETING_MACHINE_MUTATION_TOKEN": self.mutation_token,
        }
        headers = {
            "Host": "wmc-marketing-agent",
            "X-WAMOCON-Actor": "anna.schmidt",
            "X-WAMOCON-Edge-Attestation": self.edge_attestation,
            "X-WAMOCON-Mutation-Token": self.mutation_token,
            "X-Forwarded-For": "192.168.178.39",
            "X-Forwarded-Host": "marketing.internal:18117",
            "X-Forwarded-Proto": "https",
            # This legacy header must be ignored; the authority already carries
            # the exact external port when one exists.
            "X-Forwarded-Port": "9999",
        }
        with patch.dict(os.environ, environment, clear=False), TestClient(
            app, follow_redirects=False
        ) as client:
            trusted = client.get("/ui/", headers=headers)
            forged = client.get(
                "/ui/",
                headers={
                    name: value
                    for name, value in headers.items()
                    if name not in {"X-WAMOCON-Actor", "X-WAMOCON-Edge-Attestation"}
                },
            )

        self.assertEqual(trusted.status_code, 307)
        self.assertEqual(trusted.headers["location"], "https://marketing.internal:18117/ui")
        self.assertEqual(forged.status_code, 307)
        self.assertEqual(forged.headers["location"], "http://wmc-marketing-agent/ui")
        self.assertNotIn("9999", trusted.headers["location"])

    def test_invalid_business_timezone_blocks_business_routes_and_readiness(self):
        with patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_BUSINESS_TIMEZONE": "Not/A-Timezone",
                "MARKETING_MACHINE_MUTATION_TOKEN": self.mutation_token,
                "MARKETING_MACHINE_MUTATION_AUTH_MODE": "required",
            },
            clear=False,
        ), TestClient(app) as client:
            console = client.get("/ui")
            unauthenticated_campaigns = client.get("/campaigns")
            campaigns = client.get(
                "/campaigns",
                headers={"X-WAMOCON-Mutation-Token": self.mutation_token},
            )
            readiness = client.get("/readyz")

        self.assertEqual(console.status_code, 200)
        self.assertEqual(unauthenticated_campaigns.status_code, 401)
        self.assertEqual(campaigns.status_code, 503)
        self.assertEqual(
            campaigns.json()["detail"],
            "business timezone configuration is invalid",
        )
        self.assertEqual(readiness.status_code, 503)
        self.assertEqual(
            readiness.json()["business_timezone_policy"]["status"],
            "blocked_invalid_business_timezone",
        )


class ApiIntegrityTests(unittest.TestCase):
    def test_state_detail_projects_current_safe_evidence_metadata(self):
        content_id = "evidence-projection-test"
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            JsonStore(Path(tmp)).save_state(
                {
                    "brief": {"id": content_id, "campaign_id": "k1"},
                    "evidence_records": [
                        {
                            "id": "Kampagnen/kampagne_1_consulting_qa.json",
                            "claim": "untrusted stale copy",
                            "owner": "untrusted stale owner",
                        }
                    ],
                },
                expected_revision=None,
            )
            projected = get_state(content_id)

        record = projected["evidence_records"][0]
        self.assertTrue(record["vault_verified"])
        self.assertEqual(record["owner"], "WAMOCON Marketing")
        self.assertEqual(record["vault_version"], "2026-07-01")
        self.assertNotEqual(record["claim"], "untrusted stale copy")

    def test_state_detail_fails_closed_for_migrated_unverified_postiz_media(self):
        content_id = "legacy-reel-media-projection"
        legacy_asset = {
            "asset_id": "legacy-video",
            "status": "approved",
            "media_type": "video",
            "postiz_media_id": "legacy-postiz-video",
            "postiz_path": "https://uploads.postiz.example/legacy.mp4",
            "sha256": "a" * 64,
            "provider_verified": True,
            # A migrated record cannot make its own derived verdict trusted.
            "provider_verification_valid": True,
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            store.save_state(
                {
                    "brief": {
                        "id": content_id,
                        "campaign_id": "k1",
                        "channel": "Instagram",
                        "format": "Reel",
                        "status": "ready_to_schedule",
                    },
                    "approved_media_assets": [legacy_asset],
                    "approved_media_count": 99,
                    "provider_verified_media_count": 99,
                    "postiz_media_ready": True,
                },
                expected_revision=None,
            )
            projected = get_state(content_id)
            stored = store.load_state(content_id)

        self.assertEqual(projected["approved_media_count"], 1)
        self.assertEqual(projected["provider_verified_media_count"], 0)
        self.assertFalse(projected["postiz_media_ready"])
        self.assertFalse(
            projected["approved_media_assets"][0]["provider_verification_valid"]
        )
        self.assertTrue(stored["postiz_media_ready"])
        self.assertTrue(stored["approved_media_assets"][0]["provider_verification_valid"])

    def test_state_detail_marks_only_exact_provider_binding_as_verified(self):
        content_id = "exact-reel-media-projection"
        digest = "b" * 64
        media_url = "https://uploads.postiz.example/exact.mp4"
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            JsonStore(Path(tmp)).save_state(
                {
                    "brief": {
                        "id": content_id,
                        "campaign_id": "k1",
                        "channel": "Instagram",
                        "format": "Reel",
                        "status": "ready_to_schedule",
                    },
                    "approved_media_assets": [
                        {
                            "asset_id": "exact-video",
                            "status": "approved",
                            "media_type": "video",
                            "postiz_media_id": "postiz-exact-video",
                            "postiz_path": media_url,
                            "sha256": digest,
                            "provider_verified": True,
                            "provider_verification_method": "postiz_public_url_sha256",
                            "provider_sha256": digest,
                            "provider_path": media_url,
                        }
                    ],
                },
                expected_revision=None,
            )
            projected = get_state(content_id)

        self.assertEqual(projected["provider_verified_media_count"], 1)
        self.assertTrue(projected["postiz_media_ready"])
        self.assertTrue(
            projected["approved_media_assets"][0]["provider_verification_valid"]
        )

    def test_trend_api_rejects_explicit_empty_sources_before_idempotent_lookup(self):
        payload = {
            "request_id": "legacy-empty-source-selection",
            "campaign_ids": ["k1"],
            "platforms": [],
        }
        stored = {
            "id": trend_request_run_id(payload["request_id"]),
            "request_id": payload["request_id"],
            "request_fingerprint": trend_request_fingerprint(payload),
            "status": "needs_live_sources",
            "campaigns": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            JsonStore(Path(tmp)).save_trend_run(stored)
            with patch.dict(os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False):
                with self.assertRaises(HTTPException) as raised:
                    trend_research(payload)

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail, "platforms must contain at least one source")

    def test_trend_api_rejects_unknown_campaign_before_legacy_idempotent_result(self):
        token = "test-only-" + "trend-api-" + "mutation-token-123456789"
        payload = {
            "request_id": "legacy-invalid-campaign-selection",
            "campaign_ids": ["not-a-real-campaign"],
        }
        stored = {
            "id": trend_request_run_id(payload["request_id"]),
            "request_id": payload["request_id"],
            "request_fingerprint": trend_request_fingerprint(payload),
            "status": "needs_live_sources",
            "campaigns": [],
        }

        with tempfile.TemporaryDirectory() as tmp:
            JsonStore(Path(tmp)).save_trend_run(stored)
            with patch.dict(
                os.environ,
                {
                    "MARKETING_MACHINE_DATA_DIR": tmp,
                    "MARKETING_MACHINE_MUTATION_TOKEN": token,
                    "MARKETING_MACHINE_MUTATION_AUTH_MODE": "required",
                    "MARKETING_MACHINE_ACTOR_AUTH_MODE": "local-optional",
                },
                clear=False,
            ), TestClient(app) as client:
                response = client.post(
                    "/workflows/trend-research",
                    json=payload,
                    headers={"X-WAMOCON-Mutation-Token": token},
                )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "unknown campaign selection; choose K1, K2, K3, K4, or K5",
        )
        self.assertNotIn("not-a-real-campaign", response.text)

    def test_manual_intake_cannot_remove_canonical_risk_or_proof_fields(self):
        captured = []

        def generate(brief):
            captured.append(brief)
            return {
                "brief": brief.to_dict(),
                "approval": None,
                "errors": [],
                "next_step": "human_review",
                "requires_human_review": True,
                "evidence_records": [],
                "scheduler_payload": {},
            }

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ), patch("marketing_machine.api.create_state_for_brief", side_effect=generate):
            result = create_content(
                {
                    "id": "k4-canonical-integrity",
                    "campaign_id": "k4",
                    "content_mode": "evergreen",
                    "proof_sources": ["Kampagnen/kampagne_1_consulting_qa.json"],
                    "risk_flags": ["caller_added_review_flag"],
                    "campaign_context": {"content_constraints": []},
                }
            )

        brief = captured[0]
        self.assertEqual(result["state"]["brief"]["campaign_id"], "k4")
        self.assertEqual(
            brief.proof_sources,
            [
                "Kampagnen/kampagne_4_mitarbeiter.json",
                "Kampagnen/kampagne_1_consulting_qa.json",
            ],
        )
        self.assertEqual(
            brief.risk_flags,
            ["people_consent_and_real_assets_required", "caller_added_review_flag"],
        )
        self.assertTrue(brief.campaign_context["content_constraints"])

    def test_manual_intake_rejects_non_array_proof_and_risk_fields(self):
        invalid = (
            {"proof_sources": "Kampagnen/kampagne_1_consulting_qa.json"},
            {"risk_flags": "people_consent_and_real_assets_required"},
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            for index, override in enumerate(invalid):
                with self.subTest(override=override), self.assertRaises(HTTPException) as raised:
                    create_content(
                        {
                            "id": f"k4-invalid-union-{index}",
                            "campaign_id": "k4",
                            "content_mode": "evergreen",
                            **override,
                        }
                    )
                self.assertEqual(raised.exception.status_code, 422)

    def test_idempotent_and_stored_trend_runs_are_refreshed_before_return(self):
        payload = {"request_id": "refresh-before-return", "campaign_ids": ["k1"]}
        run_id = trend_request_run_id(payload["request_id"])
        stored = {
            "id": run_id,
            "request_id": payload["request_id"],
            "request_fingerprint": trend_request_fingerprint(payload),
            "status": "stale-status",
            "campaigns": [],
        }

        def refresh(run):
            run["status"] = "refreshed-status"
            run["eligibility_evaluated_at"] = "2026-07-10T12:00:00+00:00"
            return run

        with tempfile.TemporaryDirectory() as tmp:
            JsonStore(Path(tmp)).save_trend_run(stored)
            with patch.dict(os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False), patch(
                "marketing_machine.api.refresh_trend_run_eligibility", side_effect=refresh
            ) as refresh_call:
                retry = trend_research(payload)
                loaded = get_trend_run(run_id)
                listed = list_trend_runs(limit=25)

        self.assertTrue(retry["idempotent"])
        self.assertEqual(retry["trend_run"]["status"], "refreshed-status")
        self.assertEqual(loaded["status"], "refreshed-status")
        self.assertEqual(listed["items"][0]["status"], "refreshed-status")
        self.assertEqual(refresh_call.call_count, 3)


if __name__ == "__main__":
    unittest.main()

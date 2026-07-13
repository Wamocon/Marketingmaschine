import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.api import _record_outbox_reconciliation, app
from marketing_machine.auth import edge_actor_authorization_status
from marketing_machine.campaign_catalog import default_brief_payload, load_campaign_catalog
from marketing_machine.content_generator import ContentGenerator
from marketing_machine.evidence import EvidenceVault
from marketing_machine.governance import GovernancePolicy
from marketing_machine.schemas import ContentBrief
from marketing_machine.storage import JsonStore
from marketing_machine.workflow import MarketingWorkflow


MUTATION_TOKEN = "actor-test-" + "mutation-token-" + "1234567890abcdef"
EDGE_ATTESTATION = "a" * 64
SECOND_EDGE_ATTESTATION = "b" * 64


class SafeStructuredAIClient:
    provider = "test-local-ai"
    model = "schema-valid-test-model"
    route_name = "local_content_draft"

    def complete_json(self, **_kwargs):
        return {
            "channel_copy": {
                "headline": "QA-Risiken strukturiert prüfen",
                "body": (
                    "WAMOCON kann QA-Risiken, Testabdeckung und Freigabeprozesse "
                    "strukturiert prüfen und priorisieren. Welche QA-Frage braucht "
                    "zuerst Ihre Aufmerksamkeit und wie möchten Sie sie prüfen?"
                ),
                "caption": "",
                "cta": "",
                "hashtags": [],
                "carousel_slides": [],
            },
            "reel": {
                "idea": "",
                "format": "",
                "hook": "",
                "script": [],
                "shot_list": [],
                "on_screen_text": [],
                "caption": "",
                "cta": "",
                "editing_notes": "",
            },
            "citations": [],
            "review_notes": [],
        }


class ActorAuthenticationTests(unittest.TestCase):
    def production_env(self, data_dir: str) -> dict[str, str]:
        return {
            "MARKETING_MACHINE_DATA_DIR": data_dir,
            "MARKETING_MACHINE_MUTATION_TOKEN": MUTATION_TOKEN,
            "MARKETING_MACHINE_MUTATION_TOKEN_FILE": "",
            "MARKETING_MACHINE_MUTATION_AUTH_MODE": "required",
            "MARKETING_MACHINE_ACTOR_AUTH_MODE": "required",
            "MARKETING_MACHINE_EDGE_ATTESTATION": EDGE_ATTESTATION,
            "MARKETING_MACHINE_EDGE_ATTESTATION_FILE": "",
        }

    @staticmethod
    def headers(actor: str = "alice.marketer", attestation: str = EDGE_ATTESTATION):
        return {
            "X-WAMOCON-Mutation-Token": MUTATION_TOKEN,
            "X-WAMOCON-Actor": actor,
            "X-WAMOCON-Edge-Attestation": attestation,
        }

    def test_forged_or_unbound_actor_is_rejected_before_sensitive_handler(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, self.production_env(tmp), clear=False
        ):
            with TestClient(app) as client:
                cases = (
                    ({"X-WAMOCON-Mutation-Token": MUTATION_TOKEN}, 401),
                    (
                        {
                            "X-WAMOCON-Mutation-Token": MUTATION_TOKEN,
                            "X-WAMOCON-Actor": "alice.marketer",
                        },
                        401,
                    ),
                    (
                        {
                            "X-WAMOCON-Mutation-Token": MUTATION_TOKEN,
                            "X-WAMOCON-Edge-Attestation": EDGE_ATTESTATION,
                        },
                        401,
                    ),
                    (self.headers(attestation=SECOND_EDGE_ATTESTATION), 401),
                    (self.headers(actor="operator"), 403),
                )
                for headers, expected in cases:
                    with self.subTest(headers=set(headers), expected=expected):
                        response = client.post(
                            "/workflows/approve-content",
                            headers=headers,
                            json={},
                        )
                        self.assertEqual(response.status_code, expected)

                authenticated = client.post(
                    "/workflows/approve-content",
                    headers=self.headers(),
                    json={},
                )
                self.assertEqual(authenticated.status_code, 422)

            audit_path = Path(tmp) / "events" / "authenticated_request.jsonl"
            audit = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(audit), 1)
            self.assertEqual(audit[0]["authenticated_actor"], "alice.marketer")
            self.assertEqual(len(audit[0]["request_fingerprint"]), 64)
            self.assertNotIn("payload", audit[0])

    def test_session_returns_only_edge_attested_identity(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, self.production_env(tmp), clear=False
        ):
            with TestClient(app) as client:
                missing = client.get(
                    "/session",
                    headers={"X-WAMOCON-Mutation-Token": MUTATION_TOKEN},
                )
                forged = client.get(
                    "/session",
                    headers=self.headers(attestation=SECOND_EDGE_ATTESTATION),
                )
                valid = client.get("/session", headers=self.headers())

            self.assertEqual(missing.status_code, 401)
            self.assertEqual(forged.status_code, 401)
            self.assertEqual(
                valid.json(),
                {
                    "authenticated": True,
                    "actor": "alice.marketer",
                    "authentication": "edge_attested",
                },
            )
            serialized = json.dumps(valid.json())
            self.assertNotIn(EDGE_ATTESTATION, serialized)
            self.assertNotIn(MUTATION_TOKEN, serialized)

    def test_content_approval_persists_actor_separately_from_display_reviewer(self):
        root = Path(__file__).resolve().parents[1]
        policy = GovernancePolicy.from_json_file(root / "config" / "governance-policy.json")
        evidence = EvidenceVault.from_json_file(root / "config" / "evidence-vault.json")
        workflow = MarketingWorkflow(
            policy,
            evidence_vault=evidence,
            content_generator=ContentGenerator([SafeStructuredAIClient()]),
        )
        content_id = "k1-edge-actor-approval"
        campaign = next(item for item in load_campaign_catalog(root) if item["id"] == "k1")
        state = workflow.run_until_review(
            ContentBrief(**default_brief_payload(campaign, content_id=content_id))
        ).to_dict()

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, self.production_env(tmp), clear=False
        ):
            store = JsonStore(Path(tmp))
            store.save_state(state)
            with TestClient(app) as client:
                response = client.post(
                    "/workflows/approve-content",
                    headers=self.headers("alice.marketer"),
                    json={
                        "content_id": content_id,
                        "reviewer": "Alice Display Name",
                        "decision": "approved",
                        "brand_score": 95,
                        "fact_check_passed": True,
                        "privacy_check_passed": True,
                        "ai_disclosure_check_passed": True,
                        "notes": "Evidence and privacy checks completed.",
                    },
                )
            self.assertEqual(response.status_code, 200, response.text)
            saved = store.load_state(content_id)
            self.assertEqual(saved["approval"]["reviewer"], "Alice Display Name")
            self.assertEqual(
                saved["approval_audit"]["authenticated_actor"],
                "alice.marketer",
            )
            self.assertEqual(
                len(saved["approval_audit"]["authenticated_request_fingerprint"]),
                64,
            )

    def test_readiness_fails_closed_for_missing_weak_or_reused_attestation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.production_env(tmp)
            for attestation, expected_status in (
                ("", "blocked_missing_attestation"),
                ("short", "blocked_weak_or_reused_attestation"),
                (MUTATION_TOKEN, "blocked_weak_or_reused_attestation"),
            ):
                environment = {**base, "MARKETING_MACHINE_EDGE_ATTESTATION": attestation}
                with self.subTest(expected_status=expected_status), patch.dict(
                    os.environ, environment, clear=False
                ):
                    status = edge_actor_authorization_status()
                    self.assertFalse(status["safe"])
                    self.assertEqual(status["status"], expected_status)
                    with TestClient(app) as client:
                        readiness = client.get("/readyz")
                    self.assertEqual(readiness.status_code, 503)

            with patch.dict(os.environ, base, clear=False), TestClient(app) as client:
                readiness = client.get("/readyz")
            self.assertEqual(readiness.status_code, 200)
            self.assertTrue(readiness.json()["actor_authentication"]["production_ready"])

    def test_live_routes_require_actor_while_dry_run_reaches_normal_validation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, self.production_env(tmp), clear=False
        ):
            token_only = {"X-WAMOCON-Mutation-Token": MUTATION_TOKEN}
            with TestClient(app) as client:
                dry_run = client.post(
                    "/workflows/route-scheduler-draft",
                    headers=token_only,
                    json={"dry_run": True},
                )
                live = client.post(
                    "/workflows/route-scheduler-draft",
                    headers=token_only,
                    json={"dry_run": False},
                )
            self.assertEqual(dry_run.status_code, 422)
            self.assertEqual(live.status_code, 401)

    def test_two_distinct_authenticated_requests_confirm_absence(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, self.production_env(tmp), clear=False
        ):
            store = JsonStore(Path(tmp))
            route_id = "route-two-person"
            store.save_outbox(
                {
                    "id": route_id,
                    "kind": "scheduler_draft",
                    "target": "postiz",
                    "source_id": "k1-content",
                    "status": "delivery_unknown",
                    "external_reference": "",
                    "created_at": "2026-07-10T10:00:00+00:00",
                }
            )
            payload = {
                "event_id": "absence-check-one",
                "outcome": "confirmed_not_created",
                "source_ref": "postiz-ui:snapshot:sha256:" + "c" * 64,
                "verification_method": "operator_provider_ui",
                "operator": "free text does not prove identity",
                "second_operator": "forged second name",
                "observed_at": datetime.now(timezone.utc).isoformat(),
            }
            with TestClient(app) as client:
                first = client.post(
                    f"/workflows/outbox/{route_id}/reconcile",
                    headers=self.headers("alice.marketer"),
                    json=payload,
                )
                same_actor = client.post(
                    f"/workflows/outbox/{route_id}/reconcile",
                    headers=self.headers("alice.marketer"),
                    json=payload,
                )
                second = client.post(
                    f"/workflows/outbox/{route_id}/reconcile",
                    headers=self.headers("bob.marketer"),
                    json=payload,
                )

            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()["status"], "pending_second_confirmation")
            self.assertEqual(first.json()["route"]["status"], "delivery_unknown")
            self.assertEqual(same_actor.json()["status"], "pending_second_confirmation")
            self.assertTrue(same_actor.json()["idempotent"])
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(second.json()["route"]["status"], "confirmed_not_created")
            event = second.json()["route"]["reconciliation_events"][-1]
            self.assertEqual(event["first_authenticated_actor"], "alice.marketer")
            self.assertEqual(event["second_authenticated_actor"], "bob.marketer")
            self.assertEqual(event["second_operator"], "")

    def test_server_provider_reconciliation_does_not_need_human_actor(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, self.production_env(tmp), clear=False
        ):
            route_id = "provider-read-route"
            JsonStore(Path(tmp)).save_outbox(
                {
                    "id": route_id,
                    "kind": "scheduler_draft",
                    "target": "postiz",
                    "source_id": "k1-content",
                    "status": "delivery_unknown",
                    "external_reference": "",
                }
            )
            result = _record_outbox_reconciliation(
                route_id,
                {
                    "event_id": "provider-absence-proof",
                    "outcome": "confirmed_not_created",
                    "source_ref": "postiz:two-list-checks:sha256:" + "d" * 64,
                    "verification_method": "provider_api",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                },
                provider_api_verified=True,
            )
            self.assertEqual(result["route"]["status"], "confirmed_not_created")

    def test_public_analytics_cannot_impersonate_operator_or_provider_api(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, self.production_env(tmp), clear=False
        ):
            with TestClient(app) as client:
                provider_claim = client.post(
                    "/workflows/analytics-review",
                    headers=self.headers(),
                    json={
                        "content_id": "missing-content",
                        "source_system": "postiz_api",
                        "operator": "alice.marketer",
                    },
                )
                impersonation = client.post(
                    "/workflows/analytics-review",
                    headers=self.headers(),
                    json={
                        "content_id": "missing-content",
                        "source_system": "manual",
                        "operator": "bob.marketer",
                    },
                )
                bound = client.post(
                    "/workflows/analytics-review",
                    headers=self.headers(),
                    json={
                        "content_id": "missing-content",
                        "source_system": "manual",
                        "operator": "alice.marketer",
                    },
                )
            self.assertEqual(provider_claim.status_code, 403)
            self.assertEqual(impersonation.status_code, 422)
            self.assertEqual(bound.status_code, 404)

    def test_production_proxy_overwrites_actor_and_mounts_distinct_attestation(self):
        root = Path(__file__).resolve().parents[1]
        nginx = (root / "deploy" / "network-access" / "nginx.conf").read_text(
            encoding="utf-8"
        )
        entrypoint = (
            root / "deploy" / "network-access" / "entrypoint.sh"
        ).read_text(encoding="utf-8")
        agent_compose = (root / "deploy" / "docker-compose.existing-stack.yml").read_text(
            encoding="utf-8"
        )
        edge_compose = (root / "deploy" / "docker-compose.network-access.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("proxy_set_header X-WAMOCON-Actor $remote_user;", nginx)
        self.assertIn(
            'proxy_set_header X-WAMOCON-Edge-Attestation "__WAMOCON_EDGE_ATTESTATION__";',
            nginx,
        )
        self.assertNotIn("$http_x_wamocon_actor", nginx.casefold())
        self.assertIn('[ "$edge_attestation" = "$token" ]', entrypoint)
        self.assertIn("MARKETING_MACHINE_ACTOR_AUTH_MODE: required", agent_compose)
        for compose in (agent_compose, edge_compose):
            self.assertIn("marketing_edge_attestation", compose)
            self.assertIn("marketing_mutation_token", compose)


if __name__ == "__main__":
    unittest.main()

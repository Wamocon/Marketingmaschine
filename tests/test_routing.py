import hashlib
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.governance import GovernancePolicy
from marketing_machine.routing import (
    post_json,
    route_lead,
    route_scheduler_draft,
    send_or_prepare,
    verify_postiz_media_url,
)
from marketing_machine.storage import JsonStore


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JsonStore(Path(self.tmp.name))
        self.policy = GovernancePolicy(
            name="test-policy",
            allowed_tools=["create_postiz_draft", "route_twenty_lead", "route_mautic_lead"],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def save_ready_state(self, content_id="content-1"):
        self.store.save_state(
            {
                "brief": {
                    "id": content_id,
                    "campaign": "K1 QA",
                    "persona": "IT-Leiter Thomas",
                    "channel": "LinkedIn",
                    "format": "expert_post",
                    "status": "ready_to_schedule",
                    "updated_at": "2026-07-01T00:00:00+00:00",
                },
                "next_step": "scheduler",
                "requires_human_review": False,
                "scheduler_payload": {
                    "status": "draft_only_requires_final_platform_approval",
                    "copy": "LinkedIn-Entwurf\n\nTest",
                    "utm": {"utm_source": "linkedin"},
                    "evidence_records": [{"id": "proof-1"}],
                    "postiz_mode": "draft_only",
                },
            }
        )

    def save_lead_source(self, content_id: str) -> None:
        self.store.save_state(
            {
                "brief": {
                    "id": content_id,
                    "campaign_id": "k1",
                    "campaign": "K1 QA",
                    "status": "published",
                },
                "lifecycle": {
                    "provider": "postiz",
                    "provider_status": "published",
                    "provider_post_id": f"postiz-{content_id}",
                    "route_id": f"route-{content_id}",
                    "published_at": "2026-07-01T10:00:00+00:00",
                    "last_observed_at": "2026-07-01T10:01:00+00:00",
                    "source_ref": f"postiz:{content_id}",
                    "verification_method": "operator_postiz_ui",
                    "operator": "named-reviewer",
                    "events": [
                        {
                            "provider": "postiz",
                            "provider_status": "published",
                            "provider_post_id": f"postiz-{content_id}",
                            "route_id": f"route-{content_id}",
                            "verification_method": "operator_postiz_ui",
                            "request_fingerprint": "c" * 64,
                        }
                    ],
                },
            }
        )

    def test_scheduler_draft_dry_run_prepares_postiz_payload(self):
        self.save_ready_state()

        with patch.dict(
            os.environ,
            {"POSTIZ_LINKEDIN_INTEGRATION_ID": "linkedin-integration-1"},
            clear=False,
        ):
            result = route_scheduler_draft(store=self.store, policy=self.policy, content_id="content-1")

        self.assertEqual(result["status"], "prepared")
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["target"], "postiz")
        self.assertEqual(result["payload"]["type"], "draft")
        self.assertEqual(
            result["payload"]["posts"][0]["integration"]["id"],
            "linkedin-integration-1",
        )
        self.assertEqual(result["payload"]["posts"][0]["settings"]["__type"], "linkedin")
        self.assertEqual(result["payload"]["posts"][0]["value"][0]["image"], [])
        self.assertEqual(result["config"]["draft_scope"], "text_only")
        self.assertFalse(result["config"]["media_asset_attached"])
        self.assertEqual(result["config"]["authorization_scheme"], "raw")
        self.assertTrue(result["config"]["payload_contract_ready"])

    def test_scheduler_route_blocks_unapproved_content(self):
        self.store.save_state(
            {
                "brief": {
                    "id": "content-2",
                    "campaign": "K1 QA",
                    "persona": "IT-Leiter Thomas",
                    "channel": "LinkedIn",
                    "status": "needs_human_review",
                    "updated_at": "2026-07-01T00:00:00+00:00",
                },
                "next_step": "human_review",
                "requires_human_review": True,
                "scheduler_payload": {},
            }
        )

        result = route_scheduler_draft(store=self.store, policy=self.policy, content_id="content-2")

        self.assertEqual(result["status"], "blocked")
        self.assertIn("not approved", result["reason"])

    def test_lead_dry_run_prepares_twenty_payload(self):
        consent_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        retention_expires_at = consent_at + timedelta(days=365)
        self.save_lead_source("k1-lead-source-1")
        self.store.append_lead(
            {
                "lead": {
                    "id": "lead-1",
                    "source_content_id": "k1-lead-source-1",
                    "campaign_id": "k1",
                    "campaign": "K1 QA",
                    "next_action": "sales_follow_up",
                    "source_verified": True,
                    "consent_given": True,
                    "consent_at": consent_at.isoformat(),
                    "consent_purposes": ["contact_request", "marketing_automation"],
                    "retention_policy": "contact-leads-365d",
                    "retention_expires_at": retention_expires_at.isoformat(),
                },
                "source_verified": True,
                "routing_allowed": True,
                "crm_payload": {"external_id": "lead-1"},
                "mautic_payload": {"email": "it-leitung@example.com"},
                "privacy": {
                    "status": "active",
                    "consent_status": "granted",
                    "suppression_status": "active",
                    "retention_policy": "contact-leads-365d",
                    "retention_expires_at": retention_expires_at.isoformat(),
                },
            }
        )

        result = route_lead(store=self.store, policy=self.policy, lead_id="lead-1", target="twenty")

        self.assertEqual(result["status"], "prepared")
        self.assertEqual(result["payload"]["external_id"], "lead-1")
        self.assertEqual(result["config"]["authorization_scheme"], "bearer")

    def test_post_json_uses_raw_postiz_api_key_without_bearer_prefix(self):
        captured = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self, _size=None):
                return b"{}"

        def fake_urlopen(request, timeout):
            captured["authorization"] = request.get_header("Authorization")
            return FakeResponse()

        with patch("marketing_machine.routing.urlopen", side_effect=fake_urlopen):
            post_json(
                "http://postiz/api/public/v1/posts",
                {"type": "draft"},
                "postiz-key",
                authorization_scheme="raw",
            )

        self.assertEqual(captured["authorization"], "postiz-key")

    def test_post_json_keeps_bearer_auth_for_crm_tokens(self):
        captured = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self, _size=None):
                return b"{}"

        def fake_urlopen(request, timeout):
            captured["authorization"] = request.get_header("Authorization")
            return FakeResponse()

        with patch("marketing_machine.routing.urlopen", side_effect=fake_urlopen):
            post_json("http://twenty/rest/people", {}, "twenty-key")

        self.assertEqual(captured["authorization"], "Bearer twenty-key")

    def test_postiz_media_verification_hashes_exact_provider_bytes(self):
        media = b"verified-provider-video-bytes"

        class MediaResponse:
            headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(len(media)),
            }

            def __init__(self):
                self.remaining = media

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def geturl(self):
                return "https://uploads.postiz.example/reel.mp4"

            def read(self, size=None):
                chunk = self.remaining[:size]
                self.remaining = self.remaining[len(chunk) :]
                return chunk

        expected = hashlib.sha256(media).hexdigest()
        with patch(
            "marketing_machine.routing.urlopen",
            return_value=MediaResponse(),
        ):
            result = verify_postiz_media_url(
                "https://uploads.postiz.example/reel.mp4",
                expected_sha256=expected,
                media_type="video",
            )

        self.assertTrue(result["provider_verified"])
        self.assertEqual(result["provider_sha256"], expected)
        self.assertEqual(result["provider_bytes"], len(media))
        self.assertEqual(result["provider_path"], "https://uploads.postiz.example/reel.mp4")

    def test_postiz_media_verification_rejects_mismatch_redirect_and_wrong_type(self):
        class MediaResponse:
            def __init__(self, *, final_url, content_type):
                self.final_url = final_url
                self.headers = {"Content-Type": content_type, "Content-Length": "5"}
                self.remaining = b"media"

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def geturl(self):
                return self.final_url

            def read(self, size=None):
                chunk = self.remaining[:size]
                self.remaining = self.remaining[len(chunk) :]
                return chunk

        url = "https://uploads.postiz.example/reel.mp4"
        cases = (
            (MediaResponse(final_url=url, content_type="video/mp4"), "0" * 64),
            (
                MediaResponse(
                    final_url="https://other.example/reel.mp4",
                    content_type="video/mp4",
                ),
                hashlib.sha256(b"media").hexdigest(),
            ),
            (
                MediaResponse(final_url=url, content_type="text/html"),
                hashlib.sha256(b"media").hexdigest(),
            ),
        )
        for response, digest in cases:
            with self.subTest(response=response), patch(
                "marketing_machine.routing.urlopen",
                return_value=response,
            ), self.assertRaises(ValueError):
                verify_postiz_media_url(
                    url,
                    expected_sha256=digest,
                    media_type="video",
                )

    def test_live_write_stays_blocked_until_contract_is_explicitly_verified(self):
        env = {
            "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
            "POSTIZ_BASE_URL": "http://postiz:5000",
            "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "configured-not-sent",
            "POSTIZ_CONTRACT_VERIFIED": "false",
            "POSTIZ_LINKEDIN_INTEGRATION_ID": "linkedin-integration-1",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "marketing_machine.routing.urlopen"
        ) as mocked_urlopen:
            result = send_or_prepare(
                kind="scheduler_draft",
                target="postiz",
                source_id="content-1",
                payload={"type": "draft"},
                dry_run=False,
                endpoint_env="POSTIZ_CREATE_DRAFT_PATH",
                base_url_env="POSTIZ_BASE_URL",
                token_env=("POSTIZ_API_KEY",),
                authorization_scheme="raw",
                verification_env="POSTIZ_CONTRACT_VERIFIED",
            )

        self.assertEqual(result["status"], "prepared")
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["config"]["contract_verified"])
        self.assertIn("not verified", result["reason"])
        mocked_urlopen.assert_not_called()

    def test_identical_live_route_is_sent_once_with_stable_idempotency_key(self):
        self.save_ready_state()
        captured = []

        class FakeResponse:
            status = 201

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self, _size=None):
                return b'{"id":"postiz-draft-123"}'

        def fake_urlopen(request, timeout):
            captured.append(
                {
                    "idempotency": request.get_header("Idempotency-key"),
                    "correlation": request.get_header("X-correlation-id"),
                }
            )
            return FakeResponse()

        env = {
            "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
            "POSTIZ_BASE_URL": "http://postiz:5000",
            "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "configured-not-logged",
            "POSTIZ_CONTRACT_VERIFIED": "true",
            "POSTIZ_LINKEDIN_INTEGRATION_ID": "linkedin-integration-1",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "marketing_machine.routing.urlopen", side_effect=fake_urlopen
        ):
            first = route_scheduler_draft(
                store=self.store,
                policy=self.policy,
                content_id="content-1",
                dry_run=False,
            )
            retry = route_scheduler_draft(
                store=self.store,
                policy=self.policy,
                content_id="content-1",
                dry_run=False,
            )

        self.assertEqual(len(captured), 1)
        self.assertEqual(first["id"], retry["id"])
        self.assertEqual(first["status"], "sent")
        self.assertEqual(first["external_reference"], "postiz-draft-123")
        self.assertTrue(retry["idempotent"])
        self.assertEqual(captured[0]["idempotency"], first["idempotency_key"])
        self.assertEqual(captured[0]["correlation"], first["idempotency_key"])

    def test_ambiguous_delivery_is_not_blindly_retried(self):
        self.save_ready_state()
        env = {
            "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
            "POSTIZ_BASE_URL": "http://postiz:5000",
            "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "configured-not-logged",
            "POSTIZ_CONTRACT_VERIFIED": "true",
            "POSTIZ_LINKEDIN_INTEGRATION_ID": "linkedin-integration-1",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "marketing_machine.routing.urlopen", side_effect=URLError("connection closed after send")
        ) as mocked_urlopen:
            first = route_scheduler_draft(
                store=self.store,
                policy=self.policy,
                content_id="content-1",
                dry_run=False,
            )
            retry = route_scheduler_draft(
                store=self.store,
                policy=self.policy,
                content_id="content-1",
                dry_run=False,
            )

        self.assertEqual(first["status"], "delivery_unknown")
        self.assertTrue(retry["idempotent"])
        self.assertIn("reconciliation", first["reason"])
        self.assertEqual(mocked_urlopen.call_count, 1)

    def test_redirected_provider_write_is_ambiguous_and_never_blindly_retried(self):
        self.save_ready_state()

        class RedirectedResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def geturl(self):
                return "http://postiz:5000/login"

            def read(self, _size=None):
                return b'{"ok":true}'

        env = {
            "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
            "POSTIZ_BASE_URL": "http://postiz:5000",
            "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "configured-not-logged",
            "POSTIZ_CONTRACT_VERIFIED": "true",
            "POSTIZ_LINKEDIN_INTEGRATION_ID": "linkedin-integration-1",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "marketing_machine.routing.urlopen", return_value=RedirectedResponse()
        ) as transport:
            first = route_scheduler_draft(
                store=self.store,
                policy=self.policy,
                content_id="content-1",
                dry_run=False,
            )
            retry = route_scheduler_draft(
                store=self.store,
                policy=self.policy,
                content_id="content-1",
                dry_run=False,
            )

        self.assertEqual(first["status"], "delivery_unknown")
        self.assertTrue(retry["idempotent"])
        self.assertIn("redirect", first["reason"])
        self.assertEqual(transport.call_count, 1)

    def test_real_provider_redirect_is_not_followed_with_authorization_header(self):
        redirected_requests: list[str] = []

        class RedirectTarget(BaseHTTPRequestHandler):
            def do_GET(self):
                redirected_requests.append(self.headers.get("Authorization", ""))
                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):
                return

        target = ThreadingHTTPServer(("127.0.0.1", 0), RedirectTarget)
        target_thread = threading.Thread(target=target.serve_forever, daemon=True)
        target_thread.start()
        target_url = f"http://127.0.0.1:{target.server_port}/credential-sink"

        class RedirectSource(BaseHTTPRequestHandler):
            def do_POST(self):
                content_length = int(self.headers.get("Content-Length", "0") or 0)
                if content_length:
                    self.rfile.read(content_length)
                self.send_response(302)
                self.send_header("Location", target_url)
                self.end_headers()

            def log_message(self, format, *args):
                return

        source = ThreadingHTTPServer(("127.0.0.1", 0), RedirectSource)
        source_thread = threading.Thread(target=source.serve_forever, daemon=True)
        source_thread.start()
        try:
            with self.assertRaises(HTTPError) as redirected:
                post_json(
                    f"http://127.0.0.1:{source.server_port}/provider-write",
                    {"type": "draft"},
                    "provider-secret-must-not-follow",
                    authorization_scheme="raw",
                )
            self.assertEqual(redirected.exception.code, 302)
            self.assertEqual(redirected_requests, [])
        finally:
            source.shutdown()
            target.shutdown()
            source.server_close()
            target.server_close()

    def test_definite_401_rejection_can_be_retried_once_after_configuration_fix(self):
        self.save_ready_state()

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self, _size=None):
                return b'[{"postId":"postiz-after-token-fix"}]'

        env = {
            "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
            "POSTIZ_BASE_URL": "http://postiz:5000",
            "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "definitely-bad-token",
            "POSTIZ_CONTRACT_VERIFIED": "true",
            "POSTIZ_LINKEDIN_INTEGRATION_ID": "linkedin-integration-1",
        }
        unauthorized = HTTPError(
            "http://postiz:5000/api/public/v1/posts",
            401,
            "Unauthorized",
            {},
            None,
        )
        with patch.dict(os.environ, env, clear=False), patch(
            "marketing_machine.routing.urlopen", side_effect=unauthorized
        ) as rejected_transport:
            rejected = route_scheduler_draft(
                store=self.store,
                policy=self.policy,
                content_id="content-1",
                dry_run=False,
            )
            unchanged_retry = route_scheduler_draft(
                store=self.store,
                policy=self.policy,
                content_id="content-1",
                dry_run=False,
            )
        with patch.dict(
            os.environ,
            {**env, "POSTIZ_API_KEY": "corrected-" + "high-entropy-provider-token"},
            clear=False,
        ), patch("marketing_machine.routing.urlopen", return_value=FakeResponse()) as corrected_transport:
            retried = route_scheduler_draft(
                store=self.store,
                policy=self.policy,
                content_id="content-1",
                dry_run=False,
            )

        self.assertEqual(rejected["status"], "failed_safe_to_retry")
        self.assertTrue(unchanged_retry["idempotent"])
        self.assertEqual(retried["status"], "sent")
        self.assertEqual(retried["external_reference"], "postiz-after-token-fix")
        self.assertEqual(retried["retry_count"], 1)
        self.assertEqual(rejected_transport.call_count, 1)
        self.assertEqual(corrected_transport.call_count, 1)

    def test_rate_limit_retry_after_blocks_immediate_automatic_retry(self):
        self.save_ready_state()
        env = {
            "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
            "POSTIZ_BASE_URL": "http://postiz:5000",
            "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "configured-not-logged",
            "POSTIZ_CONTRACT_VERIFIED": "true",
            "POSTIZ_LINKEDIN_INTEGRATION_ID": "linkedin-integration-1",
        }
        limited = HTTPError(
            "http://postiz:5000/api/public/v1/posts",
            429,
            "Too Many Requests",
            {"Retry-After": "120"},
            None,
        )
        with patch.dict(os.environ, env, clear=False), patch(
            "marketing_machine.routing.urlopen", side_effect=limited
        ) as transport:
            first = route_scheduler_draft(
                store=self.store,
                policy=self.policy,
                content_id="content-1",
                dry_run=False,
            )
            immediate = route_scheduler_draft(
                store=self.store,
                policy=self.policy,
                content_id="content-1",
                dry_run=False,
            )

        self.assertEqual(first["status"], "rate_limited")
        self.assertTrue(first["retry_after_at"])
        self.assertTrue(immediate["idempotent"])
        self.assertEqual(transport.call_count, 1)

    def test_non_json_2xx_response_is_delivery_unknown_and_not_retried(self):
        class FakeResponse:
            status = 202

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self, _size=None):
                return b"accepted"

        env = {
            "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
            "POSTIZ_BASE_URL": "http://postiz:5000",
            "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "configured-not-logged",
            "POSTIZ_CONTRACT_VERIFIED": "true",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "marketing_machine.routing.urlopen", return_value=FakeResponse()
        ) as transport:
            first = send_or_prepare(
                kind="scheduler_draft",
                target="postiz",
                source_id="invalid-json-response",
                payload={"type": "draft"},
                dry_run=False,
                endpoint_env="POSTIZ_CREATE_DRAFT_PATH",
                base_url_env="POSTIZ_BASE_URL",
                token_env=("POSTIZ_API_KEY",),
                authorization_scheme="raw",
                verification_env="POSTIZ_CONTRACT_VERIFIED",
                store=self.store,
            )
            retry = send_or_prepare(
                kind="scheduler_draft",
                target="postiz",
                source_id="invalid-json-response",
                payload={"type": "draft"},
                dry_run=False,
                endpoint_env="POSTIZ_CREATE_DRAFT_PATH",
                base_url_env="POSTIZ_BASE_URL",
                token_env=("POSTIZ_API_KEY",),
                authorization_scheme="raw",
                verification_env="POSTIZ_CONTRACT_VERIFIED",
                store=self.store,
            )

        self.assertEqual(first["status"], "delivery_unknown")
        self.assertTrue(retry["idempotent"])
        self.assertIn("invalid JSON", first["reason"])
        self.assertEqual(transport.call_count, 1)

    def test_oversized_2xx_response_is_delivery_unknown_and_not_retried(self):
        class OversizedResponse:
            status = 201

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self, size=None):
                return b"x" * int(size or 1)

        env = {
            "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
            "POSTIZ_BASE_URL": "http://postiz:5000",
            "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "configured-not-logged",
            "POSTIZ_CONTRACT_VERIFIED": "true",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "marketing_machine.routing.urlopen", return_value=OversizedResponse()
        ) as transport:
            first = send_or_prepare(
                kind="scheduler_draft",
                target="postiz",
                source_id="oversized-response",
                payload={"type": "draft"},
                dry_run=False,
                endpoint_env="POSTIZ_CREATE_DRAFT_PATH",
                base_url_env="POSTIZ_BASE_URL",
                token_env=("POSTIZ_API_KEY",),
                authorization_scheme="raw",
                verification_env="POSTIZ_CONTRACT_VERIFIED",
                store=self.store,
            )
            retry = send_or_prepare(
                kind="scheduler_draft",
                target="postiz",
                source_id="oversized-response",
                payload={"type": "draft"},
                dry_run=False,
                endpoint_env="POSTIZ_CREATE_DRAFT_PATH",
                base_url_env="POSTIZ_BASE_URL",
                token_env=("POSTIZ_API_KEY",),
                authorization_scheme="raw",
                verification_env="POSTIZ_CONTRACT_VERIFIED",
                store=self.store,
            )

        self.assertEqual(first["status"], "delivery_unknown")
        self.assertTrue(retry["idempotent"])
        self.assertIn("safe size limit", first["reason"])
        self.assertEqual(transport.call_count, 1)

    def test_missing_postiz_integration_id_fails_closed_before_transport(self):
        self.save_ready_state()
        env = {
            "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
            "POSTIZ_BASE_URL": "http://postiz:5000",
            "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "configured-not-logged",
            "POSTIZ_CONTRACT_VERIFIED": "true",
            "POSTIZ_LINKEDIN_INTEGRATION_ID": "",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "marketing_machine.routing.urlopen"
        ) as mocked_urlopen:
            result = route_scheduler_draft(
                store=self.store,
                policy=self.policy,
                content_id="content-1",
                dry_run=False,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["config"]["payload_contract_ready"])
        self.assertIn("POSTIZ_LINKEDIN_INTEGRATION_ID", result["reason"])
        mocked_urlopen.assert_not_called()

    def test_instagram_reel_handoff_blocks_until_approved_postiz_video_is_attached(self):
        self.save_ready_state("instagram-reel-content")
        stored = self.store.load_state("instagram-reel-content")
        stored["brief"].update({"channel": "Instagram", "format": "reel"})
        self.store.save_state(stored)

        with patch.dict(
            os.environ,
            {
                "POSTIZ_INSTAGRAM_INTEGRATION_ID": "instagram-integration-1",
                "POSTIZ_INSTAGRAM_PROVIDER_TYPE": "instagram",
            },
            clear=False,
        ):
            result = route_scheduler_draft(
                store=self.store,
                policy=self.policy,
                content_id="instagram-reel-content",
            )

        post = result["payload"]["posts"][0]
        self.assertEqual(post["settings"]["__type"], "instagram")
        # Postiz documents a single video with post_type=post as an Instagram Reel.
        self.assertEqual(post["settings"]["post_type"], "post")
        self.assertEqual(post["value"][0]["image"], [])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["config"]["draft_scope"], "text_only")
        self.assertFalse(result["config"]["media_asset_attached"])
        self.assertIn("approved Postiz-uploaded video", result["reason"])

        stored = self.store.load_state("instagram-reel-content")
        stored["approved_media_assets"] = [
            {
                "asset_id": "approved-reel-video",
                "status": "approved",
                "media_type": "video",
                "postiz_media_id": "postiz-video-1",
                "postiz_path": "https://uploads.postiz.example/reel.mp4",
                "sha256": "a" * 64,
                "provider_verified": True,
                "provider_sha256": "a" * 64,
                "provider_path": "https://uploads.postiz.example/reel.mp4",
                "provider_verification_method": "postiz_public_url_sha256",
            }
        ]
        self.store.save_state(stored)
        with patch.dict(
            os.environ,
            {
                "POSTIZ_INSTAGRAM_INTEGRATION_ID": "instagram-integration-1",
                "POSTIZ_INSTAGRAM_PROVIDER_TYPE": "instagram",
            },
            clear=False,
        ):
            ready = route_scheduler_draft(
                store=self.store,
                policy=self.policy,
                content_id="instagram-reel-content",
            )

        media = ready["payload"]["posts"][0]["value"][0]["image"]
        self.assertEqual(
            media,
            [{"id": "postiz-video-1", "path": "https://uploads.postiz.example/reel.mp4"}],
        )
        self.assertEqual(ready["status"], "prepared")
        self.assertEqual(ready["config"]["draft_scope"], "approved_media")
        self.assertTrue(ready["config"]["media_asset_attached"])

    def test_lead_route_blocks_non_routable_lead(self):
        self.save_lead_source("k1-lead-source-2")
        self.store.append_lead(
            {
                "lead": {
                    "id": "lead-2",
                    "source_content_id": "k1-lead-source-2",
                    "campaign_id": "k1",
                    "campaign": "K1 QA",
                    "next_action": "consent_required",
                    "source_verified": True,
                    "consent_given": False,
                    "consent_purposes": [],
                },
                "source_verified": True,
                "routing_allowed": False,
                "crm_payload": {},
                "mautic_payload": {},
                "privacy": {
                    "status": "withdrawn",
                    "consent_status": "withdrawn",
                    "suppression_status": "suppressed",
                    "retention_expires_at": "2099-01-01T00:00:00+00:00",
                },
            }
        )

        result = route_lead(store=self.store, policy=self.policy, lead_id="lead-2", target="twenty")

        self.assertEqual(result["status"], "blocked")
        self.assertIn("not routable", result["reason"])


if __name__ == "__main__":
    unittest.main()

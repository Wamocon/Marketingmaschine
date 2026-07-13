import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.api import (
    _project_content_lifecycle_route,
    analytics_due,
    analytics_review,
    correct_analytics_review,
    content_lifecycle,
    reconcile_postiz,
    reconcile_outbox_delivery,
    register_content_media_asset,
    revoke_content_media_asset,
)
from marketing_machine.routing import send_or_prepare
from marketing_machine.storage import JsonStore


class PublishingLifecycleTests(unittest.TestCase):
    content_id = "k1-provider-lifecycle"
    route_id = "route-provider-lifecycle"
    post_id = "postiz-post-123"

    def setUp(self):
        # These direct-function unit tests intentionally exercise the local
        # optional-auth contract. Production actor enforcement is covered by
        # the dedicated authentication/API suites.
        self.runtime_env = patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_INSTANCE_MODE": "development",
                "MARKETING_MACHINE_ACTOR_AUTH_MODE": "local-optional",
            },
            clear=False,
        )
        self.runtime_env.start()
        self.media_verifier = patch(
            "marketing_machine.api.verify_postiz_media_url",
            side_effect=lambda url, *, expected_sha256, media_type: {
                "provider_verified": True,
                "provider_sha256": expected_sha256,
                "provider_bytes": 1024,
                "provider_content_type": "video/mp4" if media_type == "video" else "image/png",
                "provider_verification_method": "postiz_public_url_sha256",
                "provider_verified_at": "2026-07-10T10:00:00+00:00",
                "provider_path": url,
            },
        )
        self.media_verifier.start()

    def tearDown(self):
        self.media_verifier.stop()
        self.runtime_env.stop()

    @staticmethod
    def state(content_id, *, status="ready_to_schedule", published_at=""):
        state = {
            "brief": {
                "id": content_id,
                "campaign_id": "k1",
                "campaign": "K1 Consulting QA",
                "status": status,
                "updated_at": "2026-07-10T00:00:00+00:00",
            },
            "next_step": "scheduler" if status == "ready_to_schedule" else "analytics",
            "requires_human_review": False,
            "scheduler_payload": {
                "status": "draft_only_requires_final_platform_approval",
            },
        }
        if published_at:
            state["lifecycle"] = {
                "provider": "postiz",
                "provider_status": "published",
                "provider_post_id": "postiz-existing",
                "published_at": published_at,
                "source_ref": "postiz:get-posts:snapshot-existing",
            }
        return state

    @classmethod
    def route(cls, content_id=None, route_id=None, *, status="sent"):
        return {
            "id": route_id or cls.route_id,
            "kind": "scheduler_draft",
            "target": "postiz",
            "source_id": content_id or cls.content_id,
            "status": status,
            "dry_run": False,
            "external_reference": cls.post_id,
            "created_at": "2026-07-01T00:00:00+00:00",
            "updated_at": "2026-07-01T00:00:00+00:00",
        }

    @classmethod
    def event(cls, event_id, provider_status, **overrides):
        payload = {
            "event_id": event_id,
            "content_id": cls.content_id,
            "route_id": cls.route_id,
            "provider": "postiz",
            "provider_status": provider_status,
            "provider_post_id": cls.post_id,
            "observed_at": "2026-07-10T10:00:00+00:00",
            "source_ref": f"postiz:get-posts:snapshot-{event_id}",
            "verification_method": "operator_postiz_ui",
            "preview_ref": "creative-review:preview:reel-video-123",
            "brand_check_passed": True,
            "fact_check_passed": True,
            "privacy_check_passed": True,
            "ai_disclosure_check_passed": True,
            "operator": "M. Beispiel",
        }
        payload.update(overrides)
        return payload

    @classmethod
    def media_payload(cls, **overrides):
        payload = {
            "content_id": cls.content_id,
            "asset_id": "approved-reel-video",
            "media_type": "video",
            "postiz_media_id": "postiz-video-123",
            "postiz_path": "https://uploads.postiz.com/reel.mp4",
            "sha256": "a" * 64,
            "reviewer": "M. Beispiel",
            "approved_at": "2020-07-10T10:00:00+00:00",
            "source_ref": "creative-review:reel-video-123",
            "preview_ref": "postiz-preview:reel-video-123",
            "verification_method": "operator_postiz_ui",
            "brand_check_passed": True,
            "fact_check_passed": True,
            "privacy_check_passed": True,
            "ai_disclosure_check_passed": True,
        }
        payload.update(overrides)
        return payload

    def test_provider_events_are_idempotent_and_monotonic(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            store.save_state(self.state(self.content_id))
            store.save_outbox(self.route())

            draft = content_lifecycle(self.event("postiz-event-draft", "draft_created"))
            retry = content_lifecycle(self.event("postiz-event-draft", "draft_created"))
            scheduled = content_lifecycle(
                self.event(
                    "postiz-event-scheduled",
                    "scheduled",
                    scheduled_for="2026-07-10T12:00:00+00:00",
                )
            )
            published = content_lifecycle(
                self.event(
                    "postiz-event-published",
                    "published",
                    observed_at="2026-07-10T12:06:00+00:00",
                    published_at="2026-07-10T12:05:00+00:00",
                )
            )

            self.assertEqual(draft["state"]["brief"]["status"], "ready_to_schedule")
            self.assertTrue(draft["state"]["requires_human_review"])
            self.assertTrue(retry["idempotent"])
            self.assertEqual(scheduled["state"]["brief"]["status"], "scheduled")
            self.assertEqual(published["state"]["brief"]["status"], "published")
            self.assertEqual(published["state"]["next_step"], "analytics")
            self.assertEqual(store.load_outbox(self.route_id)["status"], "confirmed")

            with self.assertRaises(HTTPException) as regression:
                content_lifecycle(
                    self.event(
                        "postiz-event-regression",
                        "scheduled",
                        scheduled_for="2026-07-11T12:00:00+00:00",
                    )
                )
            self.assertEqual(regression.exception.status_code, 409)

    def test_approved_postiz_media_registration_is_idempotent_and_immutable(self):
        payload = self.media_payload()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                "POSTIZ_MEDIA_ORIGIN": "https://uploads.postiz.com",
            },
            clear=False,
        ):
            store = JsonStore(Path(tmp))
            store.save_state(self.state(self.content_id))
            first = register_content_media_asset(payload)
            retry = register_content_media_asset(dict(payload))
            with self.assertRaises(HTTPException) as conflict:
                register_content_media_asset({**payload, "sha256": "b" * 64})

            self.assertFalse(first["idempotent"])
            self.assertTrue(retry["idempotent"])
            self.assertTrue(first["asset"]["provider_verification_valid"])
            self.assertTrue(retry["asset"]["provider_verification_valid"])
            self.assertEqual(conflict.exception.status_code, 409)
            assets = store.load_state(self.content_id)["approved_media_assets"]
            self.assertEqual(len(assets), 1)
            self.assertEqual(assets[0]["media_type"], "video")
            self.assertTrue(assets[0]["provider_verified"])
            self.assertEqual(assets[0]["provider_sha256"], payload["sha256"])

    def test_media_registration_fails_without_exact_provider_checksum_binding(self):
        payload = self.media_payload()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                "POSTIZ_MEDIA_ORIGIN": "https://uploads.postiz.com",
            },
            clear=False,
        ), patch(
            "marketing_machine.api.verify_postiz_media_url",
            side_effect=ValueError(
                "Postiz media checksum does not match the human-approved artifact"
            ),
        ):
            store = JsonStore(Path(tmp))
            store.save_state(self.state(self.content_id))

            with self.assertRaises(HTTPException) as rejected:
                register_content_media_asset(payload)

            self.assertEqual(rejected.exception.status_code, 422)
            self.assertIn("checksum", str(rejected.exception.detail))
            self.assertNotIn(
                "approved_media_assets",
                store.load_state(self.content_id),
            )

    def test_k4_media_registration_is_allowed_during_review_but_remains_consent_gated(self):
        content_id = "k4-consent-evidence-before-review"
        pending = self.state(content_id, status="needs_human_review")
        pending["brief"]["campaign_id"] = "k4"
        pending["brief"]["risk_flags"] = ["people_consent_and_real_assets_required"]
        pending["next_step"] = "human_review"
        pending["requires_human_review"] = True
        payload = self.media_payload(content_id=content_id, consent_refs=["consent:k4-person-1"])
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                "POSTIZ_MEDIA_ORIGIN": "https://uploads.postiz.com",
            },
            clear=False,
        ):
            store = JsonStore(Path(tmp))
            store.save_state(pending)

            with self.assertRaises(HTTPException) as missing_consent:
                register_content_media_asset({**payload, "consent_refs": []})
            self.assertEqual(missing_consent.exception.status_code, 422)
            self.assertNotIn("approved_media_assets", store.load_state(content_id))

            registered = register_content_media_asset(payload)
            self.assertFalse(registered["idempotent"])
            self.assertEqual(
                store.load_state(content_id)["approved_media_assets"][0]["consent_refs"],
                ["consent:k4-person-1"],
            )

    def test_non_k4_media_registration_remains_blocked_during_human_review(self):
        content_id = "k1-review-media-not-allowed"
        pending = self.state(content_id, status="needs_human_review")
        pending["next_step"] = "human_review"
        pending["requires_human_review"] = True
        payload = self.media_payload(content_id=content_id)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                "POSTIZ_MEDIA_ORIGIN": "https://uploads.postiz.com",
            },
            clear=False,
        ):
            store = JsonStore(Path(tmp))
            store.save_state(pending)

            with self.assertRaises(HTTPException) as blocked:
                register_content_media_asset(payload)

            self.assertEqual(blocked.exception.status_code, 409)
            self.assertNotIn("approved_media_assets", store.load_state(content_id))

    def test_media_registration_retry_repairs_audit_after_post_state_crash(self):
        payload = self.media_payload()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                "POSTIZ_MEDIA_ORIGIN": "https://uploads.postiz.com",
            },
            clear=False,
        ):
            store = JsonStore(Path(tmp))
            store.save_state(self.state(self.content_id))
            original_append = JsonStore.append_event_once
            failed = False

            def fail_first_registration_audit(instance, name, event_id, event_payload):
                nonlocal failed
                if name == "content_media_asset" and not failed:
                    failed = True
                    raise OSError("simulated audit append crash")
                return original_append(instance, name, event_id, event_payload)

            with patch.object(JsonStore, "append_event_once", new=fail_first_registration_audit):
                with self.assertRaises(OSError):
                    register_content_media_asset(payload)

            retry = register_content_media_asset(dict(payload))
            self.assertTrue(retry["idempotent"])
            events = [
                json.loads(line)
                for line in (Path(tmp) / "events" / "content_media_asset.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0]["_event_id"].startswith(f"{self.content_id}-{payload['asset_id']}-"))
            self.assertIn(retry["asset"]["request_fingerprint"][:32], events[0]["_event_id"])

    def test_media_revoke_retry_repairs_audit_after_post_state_crash(self):
        media_payload = self.media_payload()
        revoke_payload = {
            "content_id": self.content_id,
            "asset_id": media_payload["asset_id"],
            "reviewer": "M. Beispiel",
            "reason": "The approved file was withdrawn after a rights review.",
            "revoked_at": "2020-07-10T12:00:00+00:00",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                "POSTIZ_MEDIA_ORIGIN": "https://uploads.postiz.com",
            },
            clear=False,
        ):
            store = JsonStore(Path(tmp))
            store.save_state(self.state(self.content_id))
            register_content_media_asset(media_payload)
            original_append = JsonStore.append_event_once
            failed = False

            def fail_first_revoke_audit(instance, name, event_id, event_payload):
                nonlocal failed
                if name == "content_media_asset_revoke" and not failed:
                    failed = True
                    raise OSError("simulated revoke audit append crash")
                return original_append(instance, name, event_id, event_payload)

            with patch.object(JsonStore, "append_event_once", new=fail_first_revoke_audit):
                with self.assertRaises(OSError):
                    revoke_content_media_asset(revoke_payload)

            retry = revoke_content_media_asset(dict(revoke_payload))
            self.assertTrue(retry["idempotent"])
            events = [
                json.loads(line)
                for line in (Path(tmp) / "events" / "content_media_asset_revoke.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0]["_event_id"].startswith(f"{self.content_id}-{media_payload['asset_id']}-"))
            self.assertIn(retry["asset"]["revocation"]["request_fingerprint"][:32], events[0]["_event_id"])

    def test_media_replacement_and_revocation_enforce_active_reference_and_timeline(self):
        initial = self.media_payload()
        replacement = self.media_payload(
            asset_id="approved-reel-video-v2",
            postiz_media_id="postiz-video-456",
            postiz_path="https://uploads.postiz.com/reel-v2.mp4",
            sha256="b" * 64,
            approved_at="2020-07-10T11:00:00+00:00",
            supersedes_asset_id=initial["asset_id"],
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                "POSTIZ_MEDIA_ORIGIN": "https://uploads.postiz.com",
            },
            clear=False,
        ):
            store = JsonStore(Path(tmp))
            store.save_state(self.state(self.content_id))

            with self.assertRaises(HTTPException) as bogus_without_active:
                register_content_media_asset({**replacement, "supersedes_asset_id": "not-an-active-asset"})
            self.assertEqual(bogus_without_active.exception.status_code, 409)

            register_content_media_asset(initial)
            with self.assertRaises(HTTPException) as wrong_active_reference:
                register_content_media_asset({**replacement, "supersedes_asset_id": "not-an-active-asset"})
            self.assertEqual(wrong_active_reference.exception.status_code, 409)

            with self.assertRaises(HTTPException) as approval_regression:
                register_content_media_asset(
                    {**replacement, "approved_at": "2020-07-10T09:59:59+00:00"}
                )
            self.assertEqual(approval_regression.exception.status_code, 422)

            registered = register_content_media_asset(replacement)
            self.assertEqual(registered["asset"]["supersedes_asset_id"], initial["asset_id"])
            stored_assets = store.load_state(self.content_id)["approved_media_assets"]
            self.assertEqual([asset["status"] for asset in stored_assets], ["superseded", "approved"])

            revoke = {
                "content_id": self.content_id,
                "asset_id": replacement["asset_id"],
                "reviewer": "M. Beispiel",
                "reason": "The replacement was withdrawn after the final rights check.",
                "revoked_at": "2020-07-10T10:30:00+00:00",
            }
            with self.assertRaises(HTTPException) as revoke_regression:
                revoke_content_media_asset(revoke)
            self.assertEqual(revoke_regression.exception.status_code, 422)
            revoked = revoke_content_media_asset(
                {**revoke, "revoked_at": "2020-07-10T12:00:00+00:00"}
            )
            self.assertEqual(revoked["asset"]["status"], "revoked")

    def test_lifecycle_retry_repairs_outbox_and_audit_after_each_write_boundary(self):
        event = self.event("postiz-crash-repair", "draft_created")
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            store.save_state(self.state(self.content_id))
            store.save_outbox(self.route())

            original_save_outbox = JsonStore.save_outbox
            failed = False

            def fail_first_outbox(instance, payload):
                nonlocal failed
                if payload.get("id") == self.route_id and not failed:
                    failed = True
                    raise OSError("fault after state write")
                return original_save_outbox(instance, payload)

            with patch.object(JsonStore, "save_outbox", new=fail_first_outbox):
                with self.assertRaises(OSError):
                    content_lifecycle(event)

            self.assertEqual(store.load_state(self.content_id)["lifecycle"]["events"][0]["event_id"], event["event_id"])
            repaired = content_lifecycle(dict(event))
            self.assertTrue(repaired["idempotent"])
            self.assertEqual(store.load_outbox(self.route_id)["status"], "confirmed")

            second_id = "k1-audit-crash-repair"
            second_route = "route-audit-crash-repair"
            store.save_state(self.state(second_id))
            store.save_outbox(self.route(second_id, second_route))
            second_event = {
                **self.event("postiz-audit-crash-repair", "draft_created"),
                "content_id": second_id,
                "route_id": second_route,
            }
            original_append_once = JsonStore.append_event_once
            audit_failed = False

            def fail_first_audit(instance, name, event_id, payload):
                nonlocal audit_failed
                if event_id == second_event["event_id"] and not audit_failed:
                    audit_failed = True
                    raise OSError("fault after outbox write")
                return original_append_once(instance, name, event_id, payload)

            with patch.object(JsonStore, "append_event_once", new=fail_first_audit):
                with self.assertRaises(OSError):
                    content_lifecycle(second_event)

            self.assertEqual(store.load_outbox(second_route)["status"], "confirmed")
            repaired_audit = content_lifecycle(dict(second_event))
            self.assertTrue(repaired_audit["idempotent"])
            audit_lines = (Path(tmp) / "events" / "content_lifecycle.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(
                sum(second_event["event_id"] in line for line in audit_lines),
                1,
            )

    def test_lifecycle_and_outbox_reconciliation_serialize_without_lost_events(self):
        projection_started = threading.Event()
        allow_projection = threading.Event()
        reconciliation_waiting = threading.Event()
        thread_role = threading.local()
        original_outbox_lock = JsonStore.outbox_lock

        @contextmanager
        def observed_outbox_lock(instance, route_id):
            if getattr(thread_role, "reconciliation", False):
                reconciliation_waiting.set()
            with original_outbox_lock(instance, route_id):
                yield

        def delayed_projection(store, route, event):
            projection_started.set()
            self.assertTrue(allow_projection.wait(timeout=5))
            return _project_content_lifecycle_route(store, route, event)

        def record_reconciliation():
            thread_role.reconciliation = True
            return reconcile_outbox_delivery(
                self.route_id,
                {
                    "event_id": "operator-confirmed-after-lifecycle",
                    "outcome": "confirmed_created",
                    "provider_post_id": self.post_id,
                    "source_ref": "postiz-ui:operator-confirmed-after-lifecycle",
                    "verification_method": "operator_provider_ui",
                    "operator": "M. Beispiel",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                },
            )

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                "MARKETING_MACHINE_INSTANCE_MODE": "development",
                "MARKETING_MACHINE_ACTOR_AUTH_MODE": "local-optional",
            },
            clear=False,
        ), patch.object(JsonStore, "outbox_lock", new=observed_outbox_lock), patch(
            "marketing_machine.api._project_content_lifecycle_route",
            side_effect=delayed_projection,
        ):
            store = JsonStore(Path(tmp))
            store.save_state(self.state(self.content_id))
            store.save_outbox(self.route())

            with ThreadPoolExecutor(max_workers=2) as pool:
                lifecycle_future = pool.submit(
                    content_lifecycle,
                    self.event("postiz-lifecycle-race", "draft_created"),
                )
                self.assertTrue(projection_started.wait(timeout=5))
                reconciliation_future = pool.submit(record_reconciliation)
                self.assertTrue(reconciliation_waiting.wait(timeout=5))
                self.assertFalse(reconciliation_future.done())
                allow_projection.set()
                lifecycle_result = lifecycle_future.result(timeout=5)
                reconciliation_result = reconciliation_future.result(timeout=5)

            final_route = store.load_outbox(self.route_id)
            self.assertEqual(lifecycle_result["provider_status"], "draft_created")
            self.assertEqual(reconciliation_result["route"]["status"], "confirmed")
            self.assertEqual(
                final_route["reconciliation"]["event_id"],
                "postiz-lifecycle-race",
            )
            self.assertEqual(
                [event["event_id"] for event in final_route["reconciliation_events"]],
                ["operator-confirmed-after-lifecycle"],
            )

    def test_lifecycle_projection_preserves_pending_two_person_confirmation(self):
        pending = {
            "event_id": "pending-no-object-check",
            "evidence_fingerprint": "a" * 64,
            "first_authenticated_actor": "operator-a",
            "first_operator_display": "M. Beispiel",
            "source_ref": "postiz-ui:pending-no-object-check",
            "verification_method": "operator_provider_ui",
            "observed_at": "2026-07-10T09:58:00+00:00",
            "recorded_at": "2026-07-10T09:59:00+00:00",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                "MARKETING_MACHINE_INSTANCE_MODE": "development",
                "MARKETING_MACHINE_ACTOR_AUTH_MODE": "local-optional",
            },
            clear=False,
        ):
            store = JsonStore(Path(tmp))
            store.save_state(self.state(self.content_id))
            route = self.route(status="delivery_unknown")
            route["external_reference"] = ""
            route["pending_operator_confirmation"] = pending
            store.save_outbox(route)

            content_lifecycle(self.event("postiz-preserve-pending", "draft_created"))

            projected = store.load_outbox(self.route_id)
            self.assertEqual(projected["status"], "confirmed")
            self.assertEqual(projected["pending_operator_confirmation"], pending)

    def test_lifecycle_event_id_conflict_and_dry_run_route_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            store.save_state(self.state(self.content_id))
            store.save_outbox(self.route())
            content_lifecycle(self.event("postiz-event-one", "draft_created"))

            with self.assertRaises(HTTPException) as conflict:
                content_lifecycle(
                    self.event(
                        "postiz-event-one",
                        "failed",
                        provider_reason="provider rejected media",
                    )
                )
            self.assertEqual(conflict.exception.status_code, 409)

            second_id = "k1-dry-route"
            second_route = "route-dry-lifecycle"
            store.save_state(self.state(second_id))
            store.save_outbox(self.route(second_id, second_route, status="prepared"))
            payload = self.event("postiz-dry-event", "draft_created")
            payload.update({"content_id": second_id, "route_id": second_route})
            with self.assertRaises(HTTPException) as dry_route:
                content_lifecycle(payload)
            self.assertEqual(dry_route.exception.status_code, 409)

    def test_public_lifecycle_cannot_spoof_server_verified_postiz_api_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            store.save_state(self.state(self.content_id))
            store.save_outbox(self.route())
            spoof = self.event("spoofed-provider-proof", "draft_created")
            spoof.update({"verification_method": "postiz_api", "operator": ""})

            with self.assertRaises(HTTPException) as rejected:
                content_lifecycle(spoof)

            self.assertEqual(rejected.exception.status_code, 403)
            self.assertNotIn("lifecycle", store.load_state(self.content_id))

    def test_delivery_unknown_is_resolved_by_postiz_read_without_resending(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_DATA_DIR": tmp,
                "POSTIZ_BASE_URL": "http://postiz:5000",
                "POSTIZ_LIST_POSTS_PATH": "/api/public/v1/posts",
                "POSTIZ_API_KEY": "not-logged",
                "POSTIZ_CONTRACT_VERIFIED": "true",
            },
            clear=False,
        ):
            store = JsonStore(Path(tmp))
            store.save_state(self.state(self.content_id))
            route = self.route(status="delivery_unknown")
            route["external_reference"] = ""
            route["payload"] = {
                "type": "draft",
                "posts": [
                    {
                        "integration": {"id": "linkedin-integration-1"},
                        "value": [{"content": "Unique governed draft", "image": []}],
                        "settings": {"__type": "linkedin"},
                    }
                ],
            }
            store.save_outbox(route)
            postiz_response = {
                "posts": [
                    {
                        "id": self.post_id,
                        "content": "Unique governed draft",
                        "publishDate": "2020-01-01T00:00:00+00:00",
                        "releaseURL": "https://www.linkedin.com/posts/wamocon-proof",
                        "integration": {"id": "linkedin-integration-1"},
                    }
                ]
            }
            with patch(
                "marketing_machine.api.get_json", return_value=postiz_response
            ) as provider_read, patch(
                "marketing_machine.api.source_domain", return_value="linkedin.com"
            ):
                result = reconcile_postiz({"route_id": self.route_id})
                repeated = reconcile_postiz({"route_id": self.route_id})

            self.assertEqual(result["provider_status"], "published")
            self.assertTrue(repeated["lifecycle"]["idempotent"])
            self.assertFalse(result["writes_performed"])
            self.assertEqual(store.load_state(self.content_id)["brief"]["status"], "published")
            self.assertEqual(store.load_outbox(self.route_id)["status"], "confirmed")
            self.assertEqual(analytics_due("30d")["count"], 1)
            self.assertEqual(provider_read.call_count, 2)
            self.assertIn("startDate=", provider_read.call_args.args[0])
            self.assertNotIn("not-logged", provider_read.call_args.args[0])

    def test_oversized_postiz_reconciliation_response_fails_without_route_mutation(self):
        class OversizedResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self, size=None):
                return b"x" * int(size or 1)

        env = {
            "POSTIZ_BASE_URL": "http://postiz:5000",
            "POSTIZ_LIST_POSTS_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "not-logged",
            "POSTIZ_CONTRACT_VERIFIED": "true",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"MARKETING_MACHINE_DATA_DIR": tmp, **env},
            clear=False,
        ):
            store = JsonStore(Path(tmp))
            route = self.route(status="delivery_unknown")
            route["external_reference"] = ""
            store.save_outbox(route)
            before = store.load_outbox(self.route_id)

            with patch(
                "marketing_machine.routing.urlopen",
                return_value=OversizedResponse(),
            ) as provider_read, self.assertRaises(HTTPException) as rejected:
                reconcile_postiz({"route_id": self.route_id})

            self.assertEqual(rejected.exception.status_code, 502)
            self.assertIn("safe size limit", str(rejected.exception.detail))
            self.assertEqual(provider_read.call_count, 1)
            self.assertEqual(store.load_outbox(self.route_id), before)

    def test_confirmed_not_created_allows_one_governed_retry_and_resolves_crash_sending(self):
        env = {
            "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
            "POSTIZ_BASE_URL": "http://postiz:5000",
            "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "not-logged",
            "POSTIZ_CONTRACT_VERIFIED": "true",
        }
        payload = {
            "type": "draft",
            "date": "2026-07-10T00:00:00+00:00",
            "shortLink": False,
            "tags": [],
            "posts": [],
        }

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self, _size=None):
                return b'[{"postId":"postiz-after-reconciliation"}]'

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"MARKETING_MACHINE_DATA_DIR": tmp, **env},
            clear=False,
        ):
            store = JsonStore(Path(tmp))
            with patch(
                "marketing_machine.routing.urlopen",
                side_effect=URLError("timeout after request body"),
            ) as first_transport:
                ambiguous = send_or_prepare(
                    kind="scheduler_draft",
                    target="postiz",
                    source_id=self.content_id,
                    payload=payload,
                    dry_run=False,
                    endpoint_env="POSTIZ_CREATE_DRAFT_PATH",
                    base_url_env="POSTIZ_BASE_URL",
                    token_env=("POSTIZ_API_KEY",),
                    authorization_scheme="raw",
                    verification_env="POSTIZ_CONTRACT_VERIFIED",
                    store=store,
                )
            resolution = reconcile_outbox_delivery(
                ambiguous["id"],
                {
                    "event_id": "provider-check-no-object",
                    "outcome": "confirmed_not_created",
                    "source_ref": "postiz:list-posts:sha256:" + "a" * 64,
                    "verification_method": "operator_provider_ui",
                    "operator": "M. Beispiel",
                    "second_operator": "A. Kontrolle",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            with patch(
                "marketing_machine.routing.urlopen", return_value=FakeResponse()
            ) as retry_transport:
                retried = send_or_prepare(
                    kind="scheduler_draft",
                    target="postiz",
                    source_id=self.content_id,
                    payload=payload,
                    dry_run=False,
                    endpoint_env="POSTIZ_CREATE_DRAFT_PATH",
                    base_url_env="POSTIZ_BASE_URL",
                    token_env=("POSTIZ_API_KEY",),
                    authorization_scheme="raw",
                    verification_env="POSTIZ_CONTRACT_VERIFIED",
                    store=store,
                )

            self.assertEqual(ambiguous["status"], "delivery_unknown")
            self.assertEqual(first_transport.call_count, 1)
            self.assertEqual(resolution["route"]["status"], "confirmed_not_created")
            self.assertEqual(retried["status"], "sent")
            self.assertEqual(retried["retry_count"], 1)
            self.assertEqual(retry_transport.call_count, 1)
            self.assertTrue(retried["reconciliation_events"])

            crash_route = {
                "id": "route-crash-left-sending",
                "kind": "scheduler_draft",
                "target": "postiz",
                "source_id": self.content_id,
                "status": "sending",
                "dry_run": False,
                "external_reference": "",
                "created_at": "2026-07-01T00:00:00+00:00",
            }
            store.save_outbox(crash_route)
            crash_resolution = reconcile_outbox_delivery(
                crash_route["id"],
                {
                    "event_id": "provider-check-crash-no-object",
                    "outcome": "confirmed_not_created",
                    "source_ref": "postiz:list-posts:sha256:" + "b" * 64,
                    "verification_method": "operator_provider_ui",
                    "operator": "M. Beispiel",
                    "second_operator": "A. Kontrolle",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            self.assertEqual(crash_resolution["route"]["status"], "confirmed_not_created")

    def test_public_reconciliation_cannot_spoof_provider_api_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            with self.assertRaises(HTTPException) as denied:
                reconcile_outbox_delivery(
                    "route-provider-spoof",
                    {
                        "event_id": "spoofed-provider-read",
                        "outcome": "confirmed_not_created",
                        "source_ref": "postiz:list-posts:sha256:" + "a" * 64,
                        "verification_method": "provider_api",
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                    },
                )

        self.assertEqual(denied.exception.status_code, 403)

    def test_postiz_absence_requires_two_clean_reads_separated_in_time(self):
        created_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        route = {
            "id": "route-two-clean-reads",
            "kind": "scheduler_draft",
            "target": "postiz",
            "source_id": self.content_id,
            "status": "delivery_unknown",
            "dry_run": False,
            "external_reference": "",
            "created_at": created_at,
            "payload": {
                "posts": [
                    {
                        "value": [{"content": "Unique absent draft"}],
                        "integration": {"id": "linkedin-integration-1"},
                    }
                ]
            },
        }
        env = {
            "POSTIZ_BASE_URL": "http://postiz:5000",
            "POSTIZ_LIST_POSTS_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "not-logged",
            "POSTIZ_CONTRACT_VERIFIED": "true",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"MARKETING_MACHINE_DATA_DIR": tmp, **env},
            clear=False,
        ), patch("marketing_machine.api.get_json", return_value={"posts": []}):
            store = JsonStore(Path(tmp))
            store.save_outbox(route)

            first = reconcile_postiz({"route_id": route["id"]})
            immediate_retry = reconcile_postiz({"route_id": route["id"]})

            self.assertEqual(first["status"], "reconciliation_pending")
            self.assertEqual(immediate_retry["status"], "reconciliation_pending")
            self.assertEqual(store.load_outbox(route["id"])["status"], "delivery_unknown")

            aged = store.load_outbox(route["id"])
            aged["absence_observations"][-1]["observed_at"] = (
                datetime.now(timezone.utc) - timedelta(minutes=3)
            ).isoformat()
            store.save_outbox(aged)
            confirmed = reconcile_postiz({"route_id": route["id"]})

            self.assertEqual(confirmed["provider_status"], "confirmed_not_created")
            self.assertEqual(
                store.load_outbox(route["id"])["status"],
                "confirmed_not_created",
            )

    def test_delivery_completion_and_reconciliation_serialize_to_confirmed_state(self):
        payload = {
            "type": "draft",
            "date": "2026-07-10T00:00:00+00:00",
            "shortLink": False,
            "tags": [],
            "posts": [],
        }
        env = {
            "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
            "POSTIZ_BASE_URL": "http://postiz:5000",
            "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "not-logged",
            "POSTIZ_CONTRACT_VERIFIED": "true",
        }
        transport_started = threading.Event()
        allow_transport_to_finish = threading.Event()

        def delayed_post(*_args, **_kwargs):
            transport_started.set()
            self.assertTrue(allow_transport_to_finish.wait(timeout=5))
            return {"status": 200, "body": {"postId": "race-post-123"}}

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"MARKETING_MACHINE_DATA_DIR": tmp, **env},
            clear=False,
        ), patch("marketing_machine.routing.post_json", side_effect=delayed_post):
            store = JsonStore(Path(tmp))
            with ThreadPoolExecutor(max_workers=2) as pool:
                delivery_future = pool.submit(
                    send_or_prepare,
                    kind="scheduler_draft",
                    target="postiz",
                    source_id=self.content_id,
                    payload=payload,
                    dry_run=False,
                    endpoint_env="POSTIZ_CREATE_DRAFT_PATH",
                    base_url_env="POSTIZ_BASE_URL",
                    token_env=("POSTIZ_API_KEY",),
                    authorization_scheme="raw",
                    verification_env="POSTIZ_CONTRACT_VERIFIED",
                    store=store,
                )
                self.assertTrue(transport_started.wait(timeout=5))
                route_id = store.list_outbox(limit=10)[0]["id"]
                reconciliation_future = pool.submit(
                    reconcile_outbox_delivery,
                    route_id,
                    {
                        "event_id": "operator-confirmed-race-post",
                        "outcome": "confirmed_created",
                        "provider_post_id": "race-post-123",
                        "source_ref": "postiz-ui:race-post-123",
                        "verification_method": "operator_provider_ui",
                        "operator": "M. Beispiel",
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                self.assertFalse(reconciliation_future.done())
                allow_transport_to_finish.set()
                delivered = delivery_future.result(timeout=5)
                reconciled = reconciliation_future.result(timeout=5)

            self.assertEqual(delivered["status"], "sent")
            self.assertEqual(reconciled["route"]["status"], "confirmed")
            self.assertEqual(store.load_outbox(route_id)["status"], "confirmed")

    def test_due_uses_published_at_and_never_requeues_completed_record_beyond_100(self):
        published_at = "2020-01-01T00:00:00+00:00"
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            store.save_state(self.state(self.content_id, status="published", published_at=published_at))
            initially_due = analytics_due("30d")
            self.assertEqual([item["content_id"] for item in initially_due["items"]], [self.content_id])
            self.assertEqual(initially_due["items"][0]["published_at"], published_at)

            store.append_performance(
                {
                    "record": {"content_id": self.content_id, "review_window": "30d"},
                    "action": "stop",
                    "reason": "completed",
                }
            )
            for index in range(105):
                store.append_performance(
                    {
                        "record": {
                            "content_id": f"other-content-{index}",
                            "review_window": "30d",
                        },
                        "action": "wait_for_more_data",
                        "reason": "other",
                    }
                )

            self.assertEqual(analytics_due("30d")["count"], 0)

    def test_analytics_is_due_provenanced_idempotent_and_conflict_safe(self):
        payload = {
            "content_id": self.content_id,
            "review_window": "30d",
            "impressions": 1000,
            "saves": 10,
            "shares": 3,
            "comments_from_target_buyers": 2,
            "profile_visits": 30,
            "clicks": 20,
            "leads": 2,
            "qualified_leads": 1,
            "booked_calls": 1,
            "pipeline_value_eur": 500,
            "landing_page_visits": 20,
            "landing_page_conversions": 2,
            "source_system": "manual",
            "source_ref": "postiz-and-crm-export-2020-02-01.csv",
            "period_start": "2020-01-01T00:00:00+00:00",
            "period_end": "2020-02-01T00:00:00+00:00",
            "retrieved_at": "2020-02-01T01:00:00+00:00",
            "operator": "M. Beispiel",
            "attribution_rule": "utm_last_touch_30d",
            "evidence": [
                {
                    "system": "manual",
                    "ref": "postiz-and-crm-export-2020-02-01.csv",
                    "retrieved_at": "2020-02-01T01:00:00+00:00",
                    "sha256": "c" * 64,
                    "metric_fields": [
                        "impressions",
                        "saves",
                        "shares",
                        "comments_from_target_buyers",
                        "profile_visits",
                        "clicks",
                        "leads",
                        "qualified_leads",
                        "booked_calls",
                        "pipeline_value_eur",
                        "landing_page_visits",
                        "landing_page_conversions",
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            store.save_state(
                self.state(
                    self.content_id,
                    status="published",
                    published_at="2020-01-01T00:00:00+00:00",
                )
            )
            first = analytics_review(payload)
            retry = analytics_review(dict(payload))
            with self.assertRaises(HTTPException) as conflict:
                analytics_review({**payload, "impressions": 1001})

            self.assertFalse(first["idempotent"])
            self.assertTrue(retry["idempotent"])
            self.assertEqual(first["record"]["source_ref"], payload["source_ref"])
            self.assertEqual(conflict.exception.status_code, 409)
            self.assertEqual(len(store.list_performance(limit=10)), 1)

    def test_analytics_correction_is_append_only_idempotent_and_cas_safe(self):
        payload = {
            "content_id": self.content_id,
            "review_window": "30d",
            "impressions": 1000,
            "clicks": 20,
            "leads": 2,
            "qualified_leads": 1,
            "booked_calls": 1,
            "source_system": "manual",
            "source_ref": "postiz-and-crm-export-v1.csv",
            "period_start": "2020-01-01T00:00:00+00:00",
            "period_end": "2020-02-01T00:00:00+00:00",
            "retrieved_at": "2020-02-01T01:00:00+00:00",
            "operator": "M. Beispiel",
            "attribution_rule": "utm_last_touch_30d",
            "evidence": [
                {
                    "system": "manual",
                    "ref": "postiz-and-crm-export-v1.csv",
                    "retrieved_at": "2020-02-01T01:00:00+00:00",
                    "sha256": "a" * 64,
                    "metric_fields": [
                        "impressions",
                        "clicks",
                        "leads",
                        "qualified_leads",
                        "booked_calls",
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            store.save_state(
                self.state(
                    self.content_id,
                    status="published",
                    published_at="2020-01-01T00:00:00+00:00",
                )
            )
            original = analytics_review(payload)
            correction = {
                **payload,
                "impressions": 1250,
                "source_ref": "postiz-and-crm-export-v2.csv",
                "evidence": [
                    {
                        **payload["evidence"][0],
                        "ref": "postiz-and-crm-export-v2.csv",
                        "sha256": "b" * 64,
                    }
                ],
                "supersedes_fingerprint": original["request_fingerprint"],
                "correction_reason": "The first export omitted delayed impressions.",
                "correction_operator": "A. Kontrolle",
                "corrected_at": datetime.now(timezone.utc).isoformat(),
            }

            first = correct_analytics_review(correction)
            retry = correct_analytics_review(dict(correction))
            with self.assertRaises(HTTPException) as stale:
                correct_analytics_review({**correction, "impressions": 1300})

            self.assertFalse(first["idempotent"])
            self.assertTrue(retry["idempotent"])
            self.assertEqual(first["revision"], 2)
            self.assertEqual(stale.exception.status_code, 409)
            self.assertEqual(store.list_performance(limit=10)[0]["revision"], 2)
            history = (Path(tmp) / "performance" / "records.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(history), 2)

    def test_parallel_analytics_corrections_allow_only_one_current_revision(self):
        payload = {
            "content_id": self.content_id,
            "review_window": "30d",
            "impressions": 1000,
            "source_system": "manual",
            "source_ref": "analytics-v1.csv",
            "period_start": "2020-01-01T00:00:00+00:00",
            "period_end": "2020-02-01T00:00:00+00:00",
            "retrieved_at": "2020-02-01T01:00:00+00:00",
            "operator": "M. Beispiel",
            "attribution_rule": "utm_last_touch_30d",
            "evidence": [
                {
                    "system": "manual",
                    "ref": "analytics-v1.csv",
                    "retrieved_at": "2020-02-01T01:00:00+00:00",
                    "sha256": "c" * 64,
                    "metric_fields": ["impressions"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            JsonStore(Path(tmp)).save_state(
                self.state(
                    self.content_id,
                    status="published",
                    published_at="2020-01-01T00:00:00+00:00",
                )
            )
            original = analytics_review(payload)

            def submit(index: int) -> int:
                try:
                    correct_analytics_review(
                        {
                            **payload,
                            "impressions": 1100 + index,
                            "source_ref": f"analytics-v2-{index}.csv",
                            "evidence": [
                                {
                                    **payload["evidence"][0],
                                    "ref": f"analytics-v2-{index}.csv",
                                    "sha256": str(index + 1) * 64,
                                }
                            ],
                            "supersedes_fingerprint": original["request_fingerprint"],
                            "correction_reason": f"Corrected export from source batch {index}.",
                            "correction_operator": f"Operator {index}",
                            "corrected_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    return 200
                except HTTPException as exc:
                    return exc.status_code

            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(submit, (0, 1)))

            self.assertEqual(sorted(statuses), [200, 409])
            history = (Path(tmp) / "performance" / "records.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(history), 2)

    def test_analytics_rejects_unpublished_early_and_impossible_funnel_data(self):
        base = {
            "content_id": self.content_id,
            "review_window": "72h",
            "source_system": "manual",
            "source_ref": "manual-snapshot",
            "period_start": "2026-07-10T00:00:00+00:00",
            "period_end": "2026-07-13T00:00:00+00:00",
            "retrieved_at": "2026-07-13T01:00:00+00:00",
            "operator": "M. Beispiel",
            "attribution_rule": "utm_last_touch_30d",
            "evidence": [
                {
                    "system": "manual",
                    "ref": "manual-snapshot",
                    "retrieved_at": "2026-07-13T01:00:00+00:00",
                    "sha256": "d" * 64,
                    "metric_fields": [
                        "impressions",
                        "saves",
                        "shares",
                        "comments_from_target_buyers",
                        "profile_visits",
                        "clicks",
                        "leads",
                        "qualified_leads",
                        "booked_calls",
                        "pipeline_value_eur",
                        "landing_page_visits",
                        "landing_page_conversions",
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            store.save_state(self.state(self.content_id))
            with self.assertRaises(HTTPException) as unpublished:
                analytics_review(base)
            self.assertEqual(unpublished.exception.status_code, 409)

            early_state = self.state(
                self.content_id,
                status="published",
                published_at=(datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),
            )
            store.save_state(early_state)
            with self.assertRaises(HTTPException) as early:
                analytics_review(base)
            self.assertEqual(early.exception.status_code, 409)

            due_state = self.state(
                self.content_id,
                status="published",
                published_at="2020-01-01T00:00:00+00:00",
            )
            store.save_state(due_state)
            due_base = {
                **base,
                "review_window": "30d",
                "period_start": "2020-01-01T00:00:00+00:00",
                "period_end": "2020-02-01T00:00:00+00:00",
                "retrieved_at": "2020-02-01T01:00:00+00:00",
                "evidence": [
                    {
                        **base["evidence"][0],
                        "retrieved_at": "2020-02-01T01:00:00+00:00",
                    }
                ],
            }
            impossible_cases = {
                "qualified_leads": {"leads": 1, "qualified_leads": 2},
                "booked_calls": {"leads": 2, "qualified_leads": 1, "booked_calls": 2},
                "landing_page_conversions": {
                    "landing_page_visits": 1,
                    "landing_page_conversions": 2,
                },
                "pipeline_value_eur": {
                    "leads": 0,
                    "qualified_leads": 0,
                    "booked_calls": 0,
                    "pipeline_value_eur": 1,
                },
            }
            for expected, overrides in impossible_cases.items():
                with self.subTest(expected=expected), self.assertRaises(HTTPException) as inconsistent:
                    analytics_review({**due_base, **overrides})
                self.assertEqual(inconsistent.exception.status_code, 422)
                self.assertIn(expected, str(inconsistent.exception.detail))


if __name__ == "__main__":
    unittest.main()

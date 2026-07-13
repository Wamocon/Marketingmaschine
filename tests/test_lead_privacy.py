from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.api import lead_intake, lead_lifecycle, leads_retention_due
from marketing_machine.governance import GovernancePolicy
from marketing_machine.leads import build_lead_intake, lead_routing_block_reason
from marketing_machine.routing import route_lead
from marketing_machine.storage import JsonStore


def save_lead_in_process(root: str, payload: dict) -> bool:
    _, idempotent = JsonStore(Path(root)).save_lead_once(payload)
    return idempotent


def consented_payload(**overrides):
    now = datetime.now(timezone.utc)
    consent_at = now - timedelta(minutes=2)
    payload = {
        "id": "lead-privacy-1",
        "source_content_id": "k1-consent-source",
        "campaign": "K1 QA Consulting",
        "offer": "QA-Risikoaudit",
        "persona": "IT-Leiter Thomas",
        "contact_name": "Max Mustermann",
        "company": "Muster GmbH",
        "email": "max.mustermann@muster.invalid",
        "phone": "+49 69 123456",
        "message": "Bitte kontaktieren Sie mich zum Risikoaudit.",
        "consent_given": True,
        "consent_at": consent_at.isoformat(),
        "privacy_notice_version": "privacy-v3",
        "consent_source": "website_contact_form",
        "consent_proof_ref": "form-proof-privacy-1",
        "consent_purposes": ["contact_request", "marketing_automation"],
        "retention_policy": "contact-leads-365d",
        "retention_expires_at": (consent_at + timedelta(days=365)).isoformat(),
        "utm": {
            "utm_source": "linkedin",
            "utm_medium": "organic",
            "utm_campaign": "k1_qa_risk_audit",
        },
    }
    payload.update(overrides)
    return payload


class LeadPrivacyLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        actor = "Privacy Test Operator"
        actor_patch = patch(
            "marketing_machine.api.require_human_actor",
            return_value=actor,
        )
        identity_patch = patch(
            "marketing_machine.api.identity_audit_fields",
            return_value={
                "authenticated_actor": actor,
                "authenticated_request_fingerprint": "lead-privacy-test-request",
            },
        )
        actor_patch.start()
        identity_patch.start()
        self.addCleanup(identity_patch.stop)
        self.addCleanup(actor_patch.stop)

    @staticmethod
    def _save_verified_source(store: JsonStore) -> None:
        store.save_state(
            {
                "brief": {
                    "id": "k1-consent-source",
                    "campaign_id": "k1",
                    "campaign": "K1 QA Consulting",
                    "status": "published",
                },
                "lifecycle": {
                    "provider": "postiz",
                    "provider_status": "published",
                    "provider_post_id": "postiz-k1-consent-source",
                    "route_id": "route-k1-consent-source",
                    "published_at": "2026-07-01T10:00:00+00:00",
                    "last_observed_at": "2026-07-01T10:01:00+00:00",
                    "source_ref": "postiz:postiz-k1-consent-source",
                    "verification_method": "operator_postiz_ui",
                    "operator": "named-reviewer",
                    "events": [
                        {
                            "provider": "postiz",
                            "provider_status": "published",
                            "provider_post_id": "postiz-k1-consent-source",
                            "route_id": "route-k1-consent-source",
                            "verification_method": "operator_postiz_ui",
                            "request_fingerprint": "a" * 64,
                        }
                    ],
                },
            }
        )

    def test_exact_retry_is_idempotent_and_conflicting_natural_key_returns_409(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            self._save_verified_source(JsonStore(Path(tmp)))
            payload = consented_payload()
            first = lead_intake(payload)
            retry = lead_intake(payload)

            with self.assertRaises(HTTPException) as conflict:
                lead_intake({**payload, "email": "different@muster.invalid"})

            current_files = list((Path(tmp) / "leads" / "current").glob("*.json"))
            history = (Path(tmp) / "leads" / "history.jsonl").read_text(encoding="utf-8").splitlines()

        self.assertFalse(first["idempotent"])
        self.assertTrue(retry["idempotent"])
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(len(current_files), 1)
        self.assertEqual(len(history), 1)

    def test_demo_and_campaign_mismatched_sources_are_accepted_only_for_manual_review(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            store.save_state(
                {
                    "brief": {
                        "id": "demo-k1-lead-source",
                        "campaign_id": "k1",
                        "campaign": "K1 QA Consulting",
                        "status": "published",
                    },
                    "lifecycle": {
                        "provider": "postiz",
                        "provider_status": "published",
                        "provider_post_id": "postiz-k2-real-lead-source",
                        "route_id": "route-k2-real-lead-source",
                        "published_at": "2026-07-01T10:00:00+00:00",
                        "last_observed_at": "2026-07-01T10:01:00+00:00",
                        "source_ref": "postiz:postiz-k2-real-lead-source",
                        "verification_method": "operator_postiz_ui",
                        "operator": "named-reviewer",
                        "events": [
                            {
                                "provider": "postiz",
                                "provider_status": "published",
                                "provider_post_id": "postiz-k2-real-lead-source",
                                "route_id": "route-k2-real-lead-source",
                                "verification_method": "operator_postiz_ui",
                                "request_fingerprint": "b" * 64,
                            }
                        ],
                    },
                }
            )
            store.save_state(
                {
                    "brief": {
                        "id": "k2-real-lead-source",
                        "campaign_id": "k2",
                        "campaign": "K2 Sokrates",
                        "status": "published",
                    },
                    "lifecycle": {
                        "provider": "postiz",
                        "provider_status": "published",
                        "provider_post_id": "postiz-k2-real-lead-source",
                        "route_id": "route-k2-real-lead-source",
                        "published_at": "2026-07-01T10:00:00+00:00",
                        "last_observed_at": "2026-07-01T10:01:00+00:00",
                        "source_ref": "postiz:postiz-k2-real-lead-source",
                        "verification_method": "operator_postiz_ui",
                        "operator": "named-reviewer",
                        "events": [
                            {
                                "provider": "postiz",
                                "provider_status": "published",
                                "provider_post_id": "postiz-k2-real-lead-source",
                                "route_id": "route-k2-real-lead-source",
                                "verification_method": "operator_postiz_ui",
                                "request_fingerprint": "b" * 64,
                            }
                        ],
                    },
                }
            )
            demo = lead_intake(
                consented_payload(
                    id="lead-demo-source",
                    source_content_id="demo-k1-lead-source",
                    consent_proof_ref="form-proof-demo-source",
                )
            )
            mismatch = lead_intake(
                consented_payload(
                    id="lead-mismatched-source",
                    source_content_id="k2-real-lead-source",
                    consent_proof_ref="form-proof-mismatched-source",
                )
            )

        for result in (demo, mismatch):
            self.assertFalse(result["source_verified"])
            self.assertFalse(result["routing_allowed"])
            self.assertEqual(result["lead"]["next_action"], "manual_source_review")
            self.assertEqual(result["crm_payload"], {})
            self.assertEqual(result["mautic_payload"], {})
        self.assertIn("demo or unverified", "; ".join(demo["warnings"]))
        self.assertIn("does not match", "; ".join(mismatch["warnings"]))

    def test_real_source_binds_the_lead_to_a_canonical_campaign_id(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            self._save_verified_source(store)
            result = lead_intake(consented_payload())

        self.assertTrue(result["source_verified"])
        self.assertTrue(result["routing_allowed"])
        self.assertEqual(result["lead"]["campaign_id"], "k1")

    def test_draft_or_unproven_published_source_never_verifies_a_lead(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            store.save_state(
                {
                    "brief": {
                        "id": "k1-consent-source",
                        "campaign_id": "k1",
                        "campaign": "K1 QA Consulting",
                        "status": "needs_human_review",
                    }
                }
            )
            draft = lead_intake(consented_payload(id="lead-from-draft"))

            state = store.load_state("k1-consent-source")
            state["brief"]["status"] = "published"
            store.save_state(state)
            unproven = lead_intake(
                consented_payload(
                    id="lead-from-unproven-published",
                    consent_proof_ref="form-proof-unproven-published",
                )
            )

        for result in (draft, unproven):
            self.assertFalse(result["source_verified"])
            self.assertFalse(result["routing_allowed"])
            self.assertEqual(result["crm_payload"], {})
            self.assertEqual(result["mautic_payload"], {})
        self.assertIn("not provider-confirmed", "; ".join(draft["warnings"]))
        self.assertIn("no provider publication evidence", "; ".join(unproven["warnings"]))

    def test_routing_rejects_source_if_publication_evidence_is_later_removed(self):
        policy = GovernancePolicy(name="lead-source-test", allowed_tools=["route_twenty_lead"])
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            self._save_verified_source(store)
            lead_intake(consented_payload(id="lead-publication-recheck"))
            state = store.load_state("k1-consent-source")
            state["lifecycle"]["events"] = []
            store.save_state(state)

            routed = route_lead(
                store=store,
                policy=policy,
                lead_id="lead-publication-recheck",
                target="twenty",
                dry_run=True,
            )

        self.assertEqual(routed["status"], "blocked")
        self.assertEqual(routed["payload"], {})
        self.assertIn("immutable publication event", routed["reason"])

    def test_routing_revalidates_the_canonical_non_demo_source_state(self):
        policy = GovernancePolicy(
            name="lead-source-test",
            allowed_tools=["route_twenty_lead"],
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            self._save_verified_source(store)
            lead_intake(consented_payload())
            state = store.load_state("k1-consent-source")
            state["brief"]["is_demo"] = True
            store.save_state(state)
            routed = route_lead(
                store=store,
                policy=policy,
                lead_id="lead-privacy-1",
                target="twenty",
                dry_run=True,
            )

        self.assertEqual(routed["status"], "blocked")
        self.assertEqual(routed["payload"], {})
        self.assertIn("demo or unverified", routed["reason"])

    def test_concurrent_duplicate_intake_writes_one_pii_record_and_one_audit_event(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            self._save_verified_source(JsonStore(Path(tmp)))
            payload = consented_payload(id="lead-concurrent-consent")
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(lambda _: lead_intake(payload), range(16)))

            current_files = list((Path(tmp) / "leads" / "current").glob("*.json"))
            history_lines = (Path(tmp) / "leads" / "history.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            global_events = (Path(tmp) / "events" / "lead_intake.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            lead_lock_files = list((Path(tmp) / ".locks").glob("lead-[0-9a-f][0-9a-f].lock"))

        self.assertEqual(sum(not item["idempotent"] for item in results), 1)
        self.assertEqual(len(current_files), 1)
        self.assertEqual(len(history_lines), 1)
        self.assertEqual(len(global_events), 1)
        self.assertEqual(len(lead_lock_files), 1)

    def test_duplicate_intake_is_serialized_across_worker_processes(self):
        payload = build_lead_intake(
            consented_payload(id="lead-process-consent"),
            source_verified=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with ProcessPoolExecutor(max_workers=4) as executor:
                results = list(
                    executor.map(
                        save_lead_in_process,
                        [tmp] * 8,
                        [payload] * 8,
                    )
                )
            current_files = list((Path(tmp) / "leads" / "current").glob("*.json"))
            history_lines = (Path(tmp) / "leads" / "history.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(sum(not item for item in results), 1)
        self.assertEqual(len(current_files), 1)
        self.assertEqual(len(history_lines), 1)

    def test_withdrawal_is_audited_and_blocks_external_routing(self):
        occurred_at = datetime.now(timezone.utc).isoformat()
        policy = GovernancePolicy(
            name="lead-privacy-test",
            allowed_tools=["route_twenty_lead", "route_mautic_lead"],
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            self._save_verified_source(store)
            lead_intake(consented_payload())
            prepared = route_lead(
                store=store,
                policy=policy,
                lead_id="lead-privacy-1",
                target="twenty",
                dry_run=True,
            )
            transition = {
                "lead_id": "lead-privacy-1",
                "action": "withdraw_consent",
                "operator": "privacy-officer@example.invalid",
                "reason": "Data subject withdrew consent through the privacy form.",
                "occurred_at": occurred_at,
            }
            first = lead_lifecycle(transition)
            retry = lead_lifecycle(transition)
            routed = route_lead(
                store=store,
                policy=policy,
                lead_id="lead-privacy-1",
                target="twenty",
                dry_run=False,
            )
            stored = store.load_lead("lead-privacy-1")
            held_route = store.load_outbox(prepared["id"])

        self.assertEqual(first["privacy"]["status"], "withdrawn")
        self.assertTrue(retry["idempotent"])
        self.assertFalse(stored["lead"]["consent_given"])
        self.assertFalse(stored["routing_allowed"])
        self.assertEqual(held_route["status"], "blocked")
        self.assertEqual(held_route["payload"], {})
        self.assertEqual(held_route["privacy_hold"]["action"], "withdraw_consent")
        self.assertEqual(routed["status"], "blocked")
        self.assertIn("not routable", routed["reason"])

    def test_old_transition_retry_after_later_action_is_still_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            self._save_verified_source(store)
            lead_intake(consented_payload())
            suppress = {
                "lead_id": "lead-privacy-1",
                "action": "suppress",
                "operator": "privacy-officer@example.invalid",
                "reason": "Verified suppression request from the data subject.",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            first = lead_lifecycle(suppress)
            erased = lead_lifecycle(
                {
                    "lead_id": "lead-privacy-1",
                    "action": "anonymize",
                    "operator": "privacy-officer@example.invalid",
                    "reason": "Verified erasure request after the earlier suppression.",
                    "occurred_at": (
                        datetime.now(timezone.utc) + timedelta(seconds=1)
                    ).isoformat(),
                }
            )
            old_retry = lead_lifecycle(suppress)
            stored = store.load_lead("lead-privacy-1")

        self.assertFalse(first["idempotent"])
        self.assertEqual(erased["privacy"]["status"], "anonymized")
        self.assertTrue(old_retry["idempotent"])
        self.assertEqual(stored["privacy"]["status"], "anonymized")
        self.assertEqual(stored["revision"], 3)

    def test_sent_provider_route_keeps_external_erasure_requirement_visible(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            self._save_verified_source(store)
            lead_intake(consented_payload())
            store.save_outbox(
                {
                    "id": "route-lead-already-sent",
                    "kind": "lead",
                    "target": "twenty",
                    "source_id": "lead-privacy-1",
                    "status": "sent",
                    "payload": {"contact": {"email": "max.mustermann@muster.invalid"}},
                    "response": {"id": "provider-contact-1"},
                }
            )
            lifecycle = lead_lifecycle(
                {
                    "lead_id": "lead-privacy-1",
                    "action": "anonymize",
                    "operator": "privacy-officer@example.invalid",
                    "reason": "Local erasure completed; provider erasure still needs proof.",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            held_route = store.load_outbox("route-lead-already-sent")
            lead_summary = store.list_leads(limit=10)[0]
            outbox_summary = store.list_outbox(limit=10)[0]

        self.assertTrue(lifecycle["privacy"]["external_privacy_action_required"])
        self.assertEqual(
            lifecycle["privacy"]["external_privacy_action_targets"], ["twenty"]
        )
        self.assertEqual(held_route["payload"], {})
        self.assertEqual(held_route["response"], {})
        self.assertTrue(held_route["external_privacy_action_required"])
        for summary in (lead_summary, outbox_summary):
            self.assertTrue(summary["external_privacy_action_required"])
            self.assertEqual(summary["external_privacy_action_targets"], ["twenty"])
            self.assertEqual(summary["provider_erasure_status"], "required_unverified")
        summaries_json = json.dumps([lead_summary, outbox_summary], sort_keys=True)
        self.assertNotIn("max.mustermann@muster.invalid", summaries_json)
        self.assertNotIn("Muster GmbH", summaries_json)

    def test_anonymization_removes_current_pii_but_retains_pii_free_audit_history(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            self._save_verified_source(store)
            accepted = lead_intake(consented_payload())
            lifecycle = lead_lifecycle(
                {
                    "lead_id": "lead-privacy-1",
                    "action": "anonymize",
                    "operator": "privacy-officer@example.invalid",
                    "reason": "Erase reason-victim@example.invalid and retain only anonymous attribution.",
                    "reason_code": "data_subject_request",
                    "reason_ref": "privacy-ticket-20260710-1",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            stored = store.load_lead("lead-privacy-1")
            audit_text = (Path(tmp) / "leads" / "history.jsonl").read_text(encoding="utf-8")
            all_runtime_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in Path(tmp).rglob("*")
                if path.is_file() and path.suffix in {".json", ".jsonl"}
            )

        self.assertEqual(lifecycle["privacy"]["erasure_status"], "anonymized")
        for field in ("company", "email", "contact_name", "phone", "message"):
            self.assertEqual(stored["lead"][field], "")
        self.assertEqual(stored["lead"]["utm"], {})
        self.assertEqual(stored["lead"]["consent_proof_ref"], "")
        self.assertNotIn(accepted["lead"]["email"], audit_text)
        self.assertNotIn(accepted["lead"]["message"], audit_text)
        self.assertNotIn("reason-victim@example.invalid", all_runtime_text)
        self.assertEqual(stored["privacy"]["last_reason_code"], "data_subject_request")
        self.assertEqual(stored["privacy"]["last_reason_ref"], "privacy-ticket-20260710-1")
        self.assertEqual(len([line for line in audit_text.splitlines() if line.strip()]), 2)

    def test_expired_retention_blocks_routing_even_before_cleanup_job_runs(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            self._save_verified_source(store)
            lead_intake(consented_payload())
            stored = store.load_lead("lead-privacy-1")

        after_retention = datetime.fromisoformat(
            stored["privacy"]["retention_expires_at"]
        ) + timedelta(seconds=1)
        reason = lead_routing_block_reason(stored, target="twenty", now=after_retention)

        self.assertEqual(stored["privacy"]["retention_policy"], "contact-leads-365d")
        self.assertIn("expired", reason)

    def test_expire_retention_transition_anonymizes_an_expired_record(self):
        now = datetime.now(timezone.utc)
        expired_at = (now - timedelta(minutes=1)).isoformat()
        record = build_lead_intake(
            consented_payload(id="lead-expired-retention"),
            source_verified=True,
        )
        record["lead"]["retention_expires_at"] = expired_at
        record["privacy"]["retention_expires_at"] = expired_at
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            store.save_lead_once(record)
            lifecycle = lead_lifecycle(
                {
                    "lead_id": "lead-expired-retention",
                    "action": "expire_retention",
                    "operator": "retention-job@example.invalid",
                    "reason": "Configured retention period elapsed; anonymize the operational record.",
                    "occurred_at": now.isoformat(),
                    "effective_expiry_at": expired_at,
                }
            )
            stored = store.load_lead("lead-expired-retention")

        self.assertEqual(lifecycle["privacy"]["status"], "anonymized")
        self.assertEqual(
            lifecycle["privacy"]["retention_disposition"],
            "expired_and_anonymized",
        )
        self.assertEqual(stored["lead"]["email"], "")

    def test_retention_due_discovery_is_pii_free_filtered_sorted_and_read_only(self):
        now = datetime.now(timezone.utc)
        expired_at = (now - timedelta(minutes=10)).isoformat()
        future_at = (now + timedelta(days=1)).isoformat()
        records = (
            ("lead-retention-active", "active", expired_at),
            ("lead-retention-suppressed", "suppressed", expired_at),
            ("lead-retention-withdrawn", "withdrawn", expired_at),
            ("lead-retention-anonymized", "anonymized", expired_at),
            ("lead-retention-future", "active", future_at),
            ("lead-retention-malformed", "active", "not-a-timestamp"),
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            for lead_id, privacy_status, retention_expires_at in records:
                record = build_lead_intake(
                    consented_payload(id=lead_id),
                    source_verified=True,
                )
                record["lead"]["retention_expires_at"] = retention_expires_at
                record["privacy"]["retention_expires_at"] = retention_expires_at
                record["privacy"]["status"] = privacy_status
                store.save_lead_once(record)

            (Path(tmp) / "leads" / "current" / "corrupt-retention-record.json").write_text(
                '{"email":"corrupt.person@muster.invalid"',
                encoding="utf-8",
            )

            root = Path(tmp)
            before = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            response = leads_retention_due()
            after = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

        self.assertEqual(before, after)
        self.assertEqual(response["count"], 3)
        self.assertEqual(response["invalid_count"], 2)
        self.assertTrue(response["operator_review_required"])
        self.assertIn(
            {
                "record_ref": "lead-retention-malformed",
                "field": "retention_expires_at",
                "reason": "invalid_or_missing_timestamp",
            },
            response["invalid_items"],
        )
        self.assertEqual(
            sum(item["field"] == "record" for item in response["invalid_items"]),
            1,
        )
        self.assertEqual(
            [item["lead_id"] for item in response["items"]],
            [
                "lead-retention-active",
                "lead-retention-suppressed",
                "lead-retention-withdrawn",
            ],
        )
        self.assertTrue(
            all(
                set(item) == {
                    "lead_id",
                    "effective_expiry_at",
                    "retention_policy",
                }
                for item in response["items"]
            )
        )
        serialized = json.dumps(response, sort_keys=True)
        for pii in (
            "Max Mustermann",
            "Muster GmbH",
            "max.mustermann@muster.invalid",
            "+49 69 123456",
            "Bitte kontaktieren Sie mich zum Risikoaudit.",
            "corrupt.person@muster.invalid",
        ):
            self.assertNotIn(pii, serialized)

    def test_retention_discovery_payload_is_a_deterministic_local_lifecycle_request(self):
        expired_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        record = build_lead_intake(
            consented_payload(id="lead-retention-n8n"),
            source_verified=True,
        )
        record["lead"]["retention_expires_at"] = expired_at
        record["privacy"]["retention_expires_at"] = expired_at
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            store.save_lead_once(record)
            store.save_outbox(
                {
                    "id": "route-retention-already-sent",
                    "kind": "lead",
                    "target": "twenty",
                    "source_id": "lead-retention-n8n",
                    "status": "sent",
                    "payload": {"contact": {"email": "max.mustermann@muster.invalid"}},
                    "response": {"id": "provider-contact-retention"},
                }
            )
            due = leads_retention_due()["items"]
            transition = {
                "lead_id": due[0]["lead_id"],
                "action": "expire_retention",
                "operator": "automation:n8n-retention",
                "reason": "Configured retention period elapsed; anonymize the local operational record.",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "effective_expiry_at": due[0]["effective_expiry_at"],
            }
            first = lead_lifecycle(transition)
            retry = lead_lifecycle(
                {
                    **transition,
                    "occurred_at": (
                        datetime.now(timezone.utc) + timedelta(milliseconds=1)
                    ).isoformat(),
                }
            )
            held_route = store.load_outbox("route-retention-already-sent")

        self.assertEqual(first["privacy"]["status"], "anonymized")
        self.assertTrue(first["privacy"]["external_privacy_action_required"])
        self.assertEqual(
            first["privacy"]["external_privacy_action_targets"],
            ["twenty"],
        )
        self.assertTrue(retry["idempotent"])
        self.assertEqual(held_route["payload"], {})
        self.assertEqual(held_route["response"], {})
        self.assertTrue(held_route["external_privacy_action_required"])
        self.assertEqual(
            first["privacy"]["provider_erasure_status"],
            "required_unverified",
        )
        self.assertEqual(held_route["provider_erasure_status"], "required_unverified")
        self.assertEqual(
            held_route["privacy_hold"]["occurred_at"],
            first["privacy"]["updated_at"],
        )
        self.assertEqual(held_route["privacy_hold"]["action"], "expire_retention")

    def test_legacy_lead_can_be_anonymized_without_retaining_pii_in_old_store(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore(Path(tmp))
            store.append_lead(
                {
                    "lead": {
                        "id": "legacy-lead-1",
                        "source_content_id": "legacy-source",
                        "campaign": "K1 QA Consulting",
                        "email": "legacy-person@muster.invalid",
                        "message": "Legacy personal inquiry",
                        "routing_allowed": True,
                    },
                    "routing_allowed": True,
                    "crm_payload": {"email": "legacy-person@muster.invalid"},
                }
            )
            result = lead_lifecycle(
                {
                    "lead_id": "legacy-lead-1",
                    "action": "erase",
                    "operator": "privacy-officer@example.invalid",
                    "reason": "Migrate and execute a verified legacy erasure request.",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            current = store.load_lead("legacy-lead-1")
            legacy_text = (Path(tmp) / "leads" / "records.jsonl").read_text(encoding="utf-8")

        self.assertEqual(result["privacy"]["status"], "anonymized")
        self.assertEqual(current["lead"]["email"], "")
        self.assertNotIn("legacy-person@muster.invalid", legacy_text)
        self.assertNotIn("Legacy personal inquiry", legacy_text)


if __name__ == "__main__":
    unittest.main()

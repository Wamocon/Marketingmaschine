import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.leads import build_lead_intake


def lead_payload(**overrides):
    now = datetime.now(timezone.utc)
    consent_at = now - timedelta(minutes=1)
    payload = {
        "id": "lead-1",
        "source_content_id": "mock-approved-1",
        "campaign": "K1 QA Consulting",
        "offer": "QA-Risikoaudit",
        "persona": "IT-Leiter Thomas",
        "contact_name": "Max Mustermann",
        "company": "Muster GmbH",
        "email": "it-leitung@muster-gmbh.de",
        "message": "Wir möchten einen QA-Risikoaudit Termin anfragen.",
        "consent_given": True,
        "consent_at": consent_at.isoformat(),
        "privacy_notice_version": "privacy-v3",
        "consent_source": "website_contact_form",
        "consent_proof_ref": "form-submission-20260710-001",
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


class LeadIntakeTests(unittest.TestCase):
    def test_verified_consent_lead_is_scored_and_routable(self):
        result = build_lead_intake(lead_payload(), source_verified=True)

        self.assertTrue(result["routing_allowed"])
        self.assertEqual(result["lead"]["next_action"], "sales_follow_up")
        self.assertGreaterEqual(result["lead"]["qualification_score"], 75)
        self.assertEqual(result["crm_payload"]["external_id"], "lead-1")
        self.assertEqual(result["mautic_payload"]["email"], "it-leitung@muster-gmbh.de")

    def test_non_affirmative_consent_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "affirmative"):
            build_lead_intake(lead_payload(consent_given=False), source_verified=True)

    def test_unknown_source_requires_manual_source_review(self):
        result = build_lead_intake(lead_payload(), source_verified=False)

        self.assertFalse(result["routing_allowed"])
        self.assertEqual(result["lead"]["next_action"], "manual_source_review")
        self.assertIn("source_content_id was not found", "; ".join(result["warnings"]))

    def test_invalid_email_is_rejected(self):
        with self.assertRaises(ValueError):
            build_lead_intake(lead_payload(email="not-an-email"), source_verified=True)

    def test_non_boolean_consent_cannot_enable_crm_routing(self):
        for value in (-1, 0, 1, 2, "true", "yes", None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "JSON boolean"):
                build_lead_intake(lead_payload(consent_given=value), source_verified=True)

    def test_consent_evidence_requires_timezone_and_purpose_scope(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            build_lead_intake(
                lead_payload(consent_at="2026-07-10T12:00:00"),
                source_verified=True,
            )
        with self.assertRaisesRegex(ValueError, "at least one purpose"):
            build_lead_intake(lead_payload(consent_purposes=[]), source_verified=True)

    def test_retention_policy_is_allowlisted_and_enforces_its_maximum_duration(self):
        payload = lead_payload()
        consent_at = datetime.fromisoformat(payload["consent_at"])
        with self.assertRaisesRegex(ValueError, "unsupported retention_policy"):
            build_lead_intake(
                {**payload, "retention_policy": "custom-forever"},
                source_verified=True,
            )
        with self.assertRaisesRegex(ValueError, "configured maximum"):
            build_lead_intake(
                {
                    **payload,
                    "retention_expires_at": (
                        consent_at + timedelta(days=365, seconds=1)
                    ).isoformat(),
                },
                source_verified=True,
            )

    def test_missing_id_uses_stable_natural_key(self):
        payload = lead_payload()
        payload.pop("id")
        first = build_lead_intake(payload, source_verified=True)
        second = build_lead_intake(payload, source_verified=True)

        self.assertEqual(first["lead"]["id"], second["lead"]["id"])
        self.assertEqual(first["request_fingerprint"], second["request_fingerprint"])


if __name__ == "__main__":
    unittest.main()

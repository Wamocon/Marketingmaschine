import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.evidence import EvidenceVault
from marketing_machine.schemas import EvidenceItem


class EvidenceVaultTests(unittest.TestCase):
    def test_all_configured_campaign_sources_are_approved(self):
        vault = EvidenceVault.from_json_file(Path(__file__).resolve().parents[1] / "config" / "evidence-vault.json")

        errors = vault.validate_proof_sources(
            [
                "Kampagnen/kampagne_1_consulting_qa.json",
                "Kampagnen/kampagne_2_ki_sokrates.json",
                "Kampagnen/kampagne_5_app_entwicklung.json",
            ]
        )

        self.assertEqual(errors, [])
        record = vault.records_for(["Kampagnen/kampagne_1_consulting_qa.json"])[0]
        self.assertEqual(record["vault_version"], "2026-07-01")
        self.assertEqual(record["owner"], "WAMOCON Marketing")
        self.assertEqual(record["source_type"], "internal_campaign_brief")
        self.assertEqual(record["source_ref"], record["id"])

    def test_unapproved_or_unconsented_sources_are_blocked(self):
        vault = EvidenceVault(
            [
                EvidenceItem(
                    id="case/customer-a.json",
                    claim="Customer claim",
                    source_type="customer_story",
                    source_ref="case/customer-a.json",
                    approved_for_public_use=False,
                )
            ]
        )

        errors = vault.validate_proof_sources(["case/customer-a.json"])

        self.assertTrue(any("not approved for public use" in error for error in errors))
        self.assertTrue(any("requires consent reference" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

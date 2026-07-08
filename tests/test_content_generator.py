import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.content_generator import generate_public_copy
from marketing_machine.schemas import ContentBrief


class ContentGeneratorTests(unittest.TestCase):
    def make_brief(self, **overrides):
        payload = {
            "id": "k1-qa-generated",
            "campaign": "K1 QA Risk Audit",
            "persona": "IT-Leiter Thomas",
            "channel": "LinkedIn",
            "format": "expert_post",
            "objective": "QA-Risikoaudit mit senioriger Testexpertise anbieten.",
            "cta": "QA-Risikoaudit anfragen",
            "proof_sources": ["Kampagnen/kampagne_1_consulting_qa.json"],
            "utm": {"utm_source": "linkedin", "utm_medium": "organic", "utm_campaign": "k1_qa_audit"},
            "hypothesis": "Nachweisbasierter QA-Content erzeugt qualifizierte Anfragen von IT-Leitern.",
            "test_variable": "offer",
        }
        payload.update(overrides)
        return ContentBrief(**payload)

    def test_default_linkedin_copy_is_german_publishable_draft_not_placeholder(self):
        generated = generate_public_copy(self.make_brief())

        self.assertIn("LinkedIn-Entwurf", generated.public_copy)
        self.assertIn("Nächster Schritt: QA-Risikoaudit anfragen", generated.public_copy)
        self.assertIn("Nachweis zum Anhängen", generated.public_copy)
        self.assertNotIn("replace this deterministic draft", generated.public_copy)
        self.assertTrue(any("Vor dem Posten pruefen" in note for note in generated.review_notes))

    def test_english_linkedin_copy_remains_available(self):
        generated = generate_public_copy(
            self.make_brief(
                language="en-US",
                objective="Promote a QA risk audit with proof-led copy.",
                cta="Book a QA Risk Audit",
                hypothesis="Proof-led QA content creates qualified buyer interest.",
            )
        )

        self.assertIn("Draft LinkedIn post", generated.public_copy)
        self.assertIn("CTA: Book a QA Risk Audit", generated.public_copy)
        self.assertTrue(any("Before posting, check proof" in note for note in generated.review_notes))

    def test_instagram_copy_caps_hashtags(self):
        generated = generate_public_copy(
            self.make_brief(
                channel="Instagram",
                hashtags=["qa", "ki", "b2b", "testing", "automation", "extra"],
            )
        )

        self.assertIn("Instagram-Entwurf", generated.public_copy)
        self.assertEqual(generated.public_copy.count("#"), 5)


if __name__ == "__main__":
    unittest.main()

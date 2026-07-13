import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.ai_client import AICompletion
from marketing_machine.campaign_catalog import default_brief_payload, load_campaign_catalog
from marketing_machine.content_generator import ContentGenerator, _public_source_urls, generate_public_copy
from marketing_machine.schemas import ContentBrief


class ContentGeneratorTests(unittest.TestCase):
    def test_public_citations_reject_private_and_single_label_hosts(self):
        self.assertEqual(
            _public_source_urls(
                [
                    "http://core-n8n:5678/private",
                    "http://192.168.178.75/private",
                    "http://user:password@example.com/private",
                    "https://news.example.com/public",
                ]
            ),
            ["https://news.example.com/public"],
        )

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

    def valid_ai_payload(self):
        return {
            "channel_copy": {
                "headline": "QA-Risiken werden selten von allein kleiner.",
                "body": "Ein strukturierter Risiko-Check zeigt, wo Freigaben und Testabdeckung zuerst Aufmerksamkeit brauchen.",
                "caption": "",
                "cta": "QA-Risikoaudit anfragen",
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

    def test_default_linkedin_copy_is_safe_structured_fallback(self):
        brief = self.make_brief()
        generated = generate_public_copy(brief)

        self.assertIn("QA-Risikoaudit anfragen", generated.public_copy)
        self.assertNotIn("Kampagnen/", generated.public_copy)
        self.assertNotIn(brief.hypothesis, generated.public_copy)
        self.assertEqual(generated.channel_copy["cta"], "QA-Risikoaudit anfragen")
        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertTrue(generated.provenance["fallback_used"])
        self.assertTrue(any("Vor Veröffentlichung" in note for note in generated.review_notes))

    def test_english_linkedin_copy_remains_available(self):
        generated = generate_public_copy(
            self.make_brief(
                language="en-US",
                objective="Promote a QA risk audit with proof-led copy.",
                cta="Book a QA Risk Audit",
                hypothesis="Proof-led QA content creates qualified buyer interest.",
            )
        )

        self.assertIn("Book a QA Risk Audit", generated.public_copy)
        self.assertTrue(any("Before publishing, check evidence" in note for note in generated.review_notes))

    def test_instagram_copy_caps_hashtags(self):
        generated = generate_public_copy(
            self.make_brief(
                channel="Instagram",
                hashtags=["qa", "ki", "b2b", "testing", "automation", "extra"],
            )
        )

        self.assertEqual(generated.public_copy.count("#"), 5)

    def test_injected_ai_client_is_used_and_provenance_is_recorded(self):
        payload = self.valid_ai_payload()

        class FakeClient:
            provider = "local_qwen"
            model = "qwen-test"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = 0

            def complete_json(self, **kwargs):
                self.calls += 1
                return AICompletion(
                    data=payload,
                    provider=self.provider,
                    model=self.model,
                    latency_ms=37,
                    attempts=1,
                    response_id="completion-1",
                )

        client = FakeClient()
        generated = ContentGenerator([client]).generate(self.make_brief())

        self.assertEqual(client.calls, 1)
        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertEqual(generated.provenance["provider"], "local_qwen")
        self.assertEqual(generated.provenance["model"], "qwen-test")
        self.assertEqual(generated.provenance["latency_ms"], 37)
        self.assertFalse(generated.provenance["fallback_used"])
        self.assertIn("strukturierter Risiko-Check", generated.public_copy)

    def test_ai_prompt_receives_bounded_audience_research_from_canonical_brief(self):
        payload = self.valid_ai_payload()

        class CapturingClient:
            provider = "local_qwen"
            model = "qwen-test"
            route_name = "local_content_draft"

            def __init__(self):
                self.system_prompt = ""
                self.user_prompt = ""

            def complete_json(self, **kwargs):
                self.system_prompt = kwargs["system_prompt"]
                self.user_prompt = kwargs["user_prompt"]
                return payload

        root = Path(__file__).resolve().parents[1]
        campaign = load_campaign_catalog(root, today=date(2026, 7, 10))[0]
        brief = ContentBrief(
            **default_brief_payload(campaign, content_id="k1-2026w28-audience-prompt")
        )
        client = CapturingClient()

        generated = ContentGenerator([client]).generate(brief)

        prompt = json.loads(client.user_prompt)
        profiles = prompt["audience_profiles"]
        self.assertEqual(len(profiles), 4)
        self.assertIn("IT-Leiter", profiles[0]["role"])
        self.assertTrue(profiles[0]["pain_points"])
        self.assertTrue(profiles[0]["goals"])
        self.assertEqual(profiles[0]["journey_phase"], "Consideration")
        self.assertTrue(profiles[0]["decision_context"])
        self.assertNotIn("name", profiles[0])
        self.assertNotIn("age", profiles[0])
        self.assertNotIn("income", profiles[0])
        self.assertNotIn("profile_id", profiles[0])
        self.assertIn("unverified segmentation research", client.system_prompt)
        self.assertEqual(generated.provenance["status"], "ai_generated")

    def test_ai_citations_include_only_urls_the_model_actually_cited(self):
        payload = self.valid_ai_payload()
        cited_url = "https://research-source.com/qa-signal"
        uncited_url = "https://industry-source.net/second-source"
        payload["citations"] = [
            {"url": cited_url, "label": "QA signal", "supports": "The selected claim"},
            {"url": cited_url, "label": "Duplicate", "supports": "Duplicate citation"},
        ]

        class CitationClient:
            provider = "local_qwen"
            model = "qwen-test"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return payload

        brief = self.make_brief(
            trend_sources=[cited_url, uncited_url],
            citations=[
                {"url": cited_url, "title": "QA research"},
                {"url": uncited_url, "title": "Industry research"},
            ],
        )
        generated = ContentGenerator([CitationClient()]).generate(brief)

        self.assertEqual([item["url"] for item in generated.citations], [cited_url])
        self.assertEqual(generated.citations[0]["label"], "QA signal")

    def test_trend_content_repairs_missing_visible_citations(self):
        payload = self.valid_ai_payload()
        source_one = "https://source-one.com/qa"
        source_two = "https://source-two.net/qa"

        class RepairingCitationClient:
            provider = "local_qwen"
            model = "qwen-citations"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = 0

            def complete_json(self, **kwargs):
                self.calls += 1
                payload["citations"] = [] if self.calls == 1 else [
                    {"url": source_one, "label": "Quelle eins", "supports": "QA-Signal"},
                    {"url": source_two, "label": "Quelle zwei", "supports": "QA-Signal"},
                ]
                return payload

        client = RepairingCitationClient()
        generated = ContentGenerator([client]).generate(
            self.make_brief(
                trend_id="trend-verified",
                trend_summary="Aktuelles QA-Signal",
                trend_sources=[source_one, source_two],
                citations=[
                    {"url": source_one, "title": "Quelle eins"},
                    {"url": source_two, "title": "Quelle zwei"},
                ],
            )
        )

        self.assertEqual(client.calls, 2)
        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertTrue(generated.provenance["semantic_repair_used"])
        self.assertEqual(len(generated.citations), 2)

    def test_unsafe_ai_output_uses_clearly_marked_safe_fallback(self):
        payload = self.valid_ai_payload()
        payload["channel_copy"]["body"] = "Details: Kampagnen/kampagne_1_consulting_qa.json"

        class UnsafeClient:
            provider = "unsafe-provider"
            model = "unsafe-model"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return payload

        generated = ContentGenerator([UnsafeClient()]).generate(self.make_brief())

        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertEqual(generated.provenance["fallback_reason"], "unsafe_or_invalid_content")
        self.assertNotIn("Kampagnen/", generated.public_copy)

    def test_reel_fallback_has_separate_caption_and_production_fields(self):
        generated = generate_public_copy(
            self.make_brief(channel="Instagram", format="reel", hashtags=["QA", "Testing"])
        )

        self.assertTrue(generated.reel["idea"])
        self.assertTrue(generated.reel["script"])
        self.assertTrue(generated.reel["shot_list"])
        self.assertEqual(generated.public_copy, generated.reel["caption"] + "\n\n#QA #Testing")
        self.assertNotIn("Shotlist", generated.public_copy)

    def test_reel_fallback_does_not_publish_creation_instructions(self):
        objective = (
            "LFA erklären, ohne Personen, Produktoberflächen oder Ergebnisse zu erfinden."
        )
        generated = generate_public_copy(
            self.make_brief(
                campaign_id="k3",
                campaign="LFA - Lernzentrum Für Azubis",
                channel="Instagram",
                format="reel",
                objective=objective,
                cta="LFA-Demo anfragen",
                hashtags=["Ausbildung", "FIAE"],
            )
        )

        self.assertNotIn("ohne Personen", generated.public_copy)
        self.assertNotIn(objective, generated.reel["hook"])
        self.assertIn("Fachinformatiker-Ausbildung", generated.public_copy)

    def test_portfolio_fallback_ignores_topic_hashtags_as_factual_claims(self):
        generated = generate_public_copy(
            self.make_brief(
                campaign_id="k5",
                campaign="Maßgeschneiderte App-Entwicklung (50+ Portfolio)",
                format="portfolio_carousel",
                objective="Portfolio-Nachweis sachlich einordnen.",
                cta="App-Modernisierungscheck anfragen",
                hashtags=["MaßgeschneiderteSoftware", "KI-Apps", "Prozessdigitalisierung"],
            )
        )

        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertEqual(len(generated.channel_copy["carousel_slides"]), 5)

    def test_environment_flag_can_explicitly_disable_ai_generation(self):
        generator = ContentGenerator.from_environment(
            environ={"MARKETING_MACHINE_AI_ENABLED": "false"}
        )

        generated = generator.generate(self.make_brief())

        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertEqual(
            generator.route_diagnostics[0]["configuration_errors"],
            ["ai_generation_disabled"],
        )

    def test_local_model_flat_post_shape_is_normalized_and_keeps_ai_provenance(self):
        class FlatClient:
            provider = "local_qwen"
            model = "qwen-flat"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return {
                    "post_title": "QA-Risiken sichtbar machen",
                    "post_body": "Ein strukturierter Risiko-Check priorisiert die nächsten Entscheidungen.\n\nQA-Risikoaudit anfragen",
                    "hashtags": ["QA", "Testing"],
                    "reel_idea": "",
                    "reel_format": "",
                    "reel_hook": "",
                    "reel_script": "",
                    "reel_shot_list": "",
                    "reel_on_screen_text": "",
                    "reel_caption": "",
                    "reel_editing_notes": "",
                    "citations": [],
                }

        generated = ContentGenerator([FlatClient()]).generate(self.make_brief())

        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertIn("Risiko-Check", generated.public_copy)
        self.assertEqual(generated.public_copy.count("QA-Risikoaudit anfragen"), 1)

    def test_local_model_flat_reel_shape_maps_production_fields(self):
        class FlatReelClient:
            provider = "local_qwen"
            model = "qwen-flat"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return {
                    "format": "Q&A Reel",
                    "practical_idea": "Drei Fragen für einen klaren QA-Check",
                    "hook": "Welche QA-Frage wird im Sprint zu spät gestellt?",
                    "spoken_script_beats": ["Risiko benennen", "Beleg prüfen", "Nächsten Schritt festlegen"],
                    "shot_list": ["Talking Head", "Neutrale Checkliste", "CTA-Endkarte"],
                    "on_screen_text": ["Risiko", "Beleg", "Entscheidung"],
                    "caption": "Drei klare Fragen schaffen Transparenz.",
                    "editing_notes": "Ruhige Schnitte und gut lesbare Untertitel.",
                    "hashtags": ["QA", "Testing"],
                    "citations": [],
                }

        generated = ContentGenerator([FlatReelClient()]).generate(
            self.make_brief(channel="Instagram", format="reel", hashtags=["QA", "Testing"])
        )

        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertEqual(generated.reel["format"], "Q&A Reel")
        self.assertEqual(len(generated.reel["script"]), 3)

    def test_nested_carousel_slide_objects_are_reduced_to_publishable_text(self):
        payload = self.valid_ai_payload()
        payload["channel_copy"]["carousel_slides"] = [
            {"headline": "Problem", "body": "Risiko bleibt unsichtbar."},
            {"headline": "Prüfung", "body": "Belege schaffen Klarheit."},
            {"headline": "Schritt", "body": "Risikoaudit anfragen."},
        ]

        class CarouselClient:
            provider = "local_qwen"
            model = "qwen-nested"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return payload

        generated = ContentGenerator([CarouselClient()]).generate(
            self.make_brief(format="carousel")
        )

        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertEqual(generated.channel_copy["carousel_slides"][0], "Problem — Risiko bleibt unsichtbar.")

    def test_nested_reel_production_objects_are_reduced_to_text(self):
        payload = self.valid_ai_payload()
        payload["reel"] = {
            "idea": "Drei Ausbildungsfragen",
            "format": "9:16 Reel",
            "hook": "Was braucht ein guter Lernschritt?",
            "script": [
                {"scene": "Einstieg", "voiceover": "Problem benennen"},
                {"scene": "Prüfung", "voiceover": "Beleg prüfen"},
            ],
            "shot_list": [{"shot": "Talking Head", "action": "Frage einblenden"}],
            "on_screen_text": [{"text": "Problem"}, {"text": "Beleg"}],
            "caption": "Drei Fragen für einen strukturierten Lernschritt.",
            "cta": "QA-Risikoaudit anfragen",
            "editing_notes": "Ruhige Schnitte.",
        }

        class NestedReelClient:
            provider = "local_qwen"
            model = "qwen-nested"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return payload

        generated = ContentGenerator([NestedReelClient()]).generate(
            self.make_brief(channel="Instagram", format="reel", hashtags=["QA"])
        )

        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertEqual(generated.reel["script"][0], "Einstieg — Problem benennen")
        self.assertEqual(generated.reel["shot_list"][0], "Talking Head — Frage einblenden")

    def test_invalid_model_shape_records_a_safe_diagnostic_reason(self):
        payload = self.valid_ai_payload()
        payload["channel_copy"]["body"] = {"unexpected": "object"}

        class InvalidClient:
            provider = "local_qwen"
            model = "qwen-invalid"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return payload

        generated = ContentGenerator([InvalidClient()]).generate(self.make_brief())

        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertIn("body must be text", generated.provenance["failures"][0]["detail"])

    def test_semantic_claim_violation_is_repaired_by_same_model(self):
        unsafe = self.valid_ai_payload()
        unsafe["channel_copy"]["body"] = (
            "Diese Architektur ermöglicht Prozessautomatisierung, ohne auf Datenhoheit zu verzichten."
        )
        unsafe["channel_copy"]["carousel_slides"] = ["Problem", "Architektur", "Ergebnis"]
        repaired = self.valid_ai_payload()
        repaired["channel_copy"]["body"] = (
            "Sokrates Private AI positioniert KI-Nutzung für den Mittelstand mit Fokus auf "
            "Datenschutz und internes Wissen."
        )
        repaired["channel_copy"]["carousel_slides"] = [
            "Private KI im Mittelstand",
            "Datenschutz und internes Wissen im Fokus",
            "Private-KI-Erstgespräch anfragen",
        ]

        class RepairingClient:
            provider = "local_qwen"
            model = "qwen-repair"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = []

            def complete_json(self, **kwargs):
                self.calls.append(kwargs)
                return unsafe if len(self.calls) == 1 else repaired

        client = RepairingClient()
        generated = ContentGenerator([client]).generate(
            self.make_brief(
                campaign_id="k2",
                campaign="KI (Sokrates)",
                format="carousel",
                objective="Sokrates sachlich positionieren.",
                cta="Private-KI-Erstgespräch anfragen",
            )
        )

        self.assertEqual(len(client.calls), 2)
        self.assertIn("validation_feedback", client.calls[1]["user_prompt"])
        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertTrue(generated.provenance["semantic_repair_used"])
        self.assertEqual(generated.provenance["validation_failures"], 1)
        self.assertNotIn("Architektur", generated.public_copy)

    def test_raw_stqb_source_typo_is_normalized_and_public_output_is_repaired(self):
        source_one = "https://www.qytera.de/blog/testautomatisierung-tipps-goldene-regeln"
        source_two = "https://glossary.istqb.org/de_DE/search/testautomatisierung"
        unsafe = self.valid_ai_payload()
        unsafe["channel_copy"]["body"] = "Die STQB-Definition ordnet Testautomatisierung ein."
        unsafe["citations"] = [
            {"url": source_one, "label": "STQB-Regeln", "supports": "STQB-Definition"},
            {"url": source_two, "label": "ISTQB-Glossar", "supports": "ISTQB-Definition"},
        ]
        repaired = self.valid_ai_payload()
        repaired["channel_copy"]["body"] = "Die ISTQB-Definition ordnet Testautomatisierung ein."
        repaired["citations"] = list(unsafe["citations"])

        class AcronymRepairClient:
            provider = "local_qwen"
            model = "qwen-acronym-repair"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = []

            def complete_json(self, **kwargs):
                self.calls.append(kwargs)
                return unsafe if len(self.calls) == 1 else repaired

        client = AcronymRepairClient()
        generated = ContentGenerator([client]).generate(
            self.make_brief(
                trend_id="trend-istqb",
                trend_summary="Testautomatisierung: 6 Regeln + STQB-Definition",
                trend_sources=[source_one, source_two],
                citations=[
                    {
                        "url": source_one,
                        "title": "Testautomatisierung: 6 Regeln + STQB-Definition",
                        "snippet": "Die STQB-Definition und sechs Regeln.",
                    },
                    {
                        "url": source_two,
                        "title": "ISTQB Glossary",
                        "snippet": "ISTQB definition of test automation.",
                    },
                ],
            )
        )

        prompt_context = json.loads(client.calls[0]["user_prompt"])
        self.assertIsNone(re.search(r"(?i)\bSTQB\b", json.dumps(prompt_context, ensure_ascii=False)))
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(generated.provenance["semantic_repair_used"])
        self.assertIsNone(re.search(r"(?i)\bSTQB\b", generated.public_copy))
        self.assertTrue(
            all(
                re.search(r"(?i)\bSTQB\b", json.dumps(citation, ensure_ascii=False)) is None
                for citation in generated.citations
            )
        )

    def test_semantic_repair_is_bounded_to_three_model_calls(self):
        unsafe = self.valid_ai_payload()
        unsafe["channel_copy"]["body"] = "Diese Architektur ermöglicht Prozessautomatisierung."
        unsafe["channel_copy"]["carousel_slides"] = ["Problem", "Architektur", "Ergebnis"]

        class AlwaysUnsafeClient:
            provider = "local_qwen"
            model = "qwen-bounded"
            route_name = "local_content_draft"

            def __init__(self):
                self.calls = 0

            def complete_json(self, **kwargs):
                self.calls += 1
                return unsafe

        client = AlwaysUnsafeClient()
        generated = ContentGenerator([client]).generate(
            self.make_brief(
                campaign_id="k2",
                campaign="KI (Sokrates)",
                format="carousel",
                cta="Private-KI-Erstgespräch anfragen",
            )
        )

        self.assertEqual(client.calls, 3)
        self.assertEqual(generated.provenance["status"], "deterministic_fallback")
        self.assertEqual(len(generated.provenance["failures"]), 3)

    def test_safe_carousel_structure_fill_is_explicitly_recorded(self):
        payload = self.valid_ai_payload()
        payload["channel_copy"]["headline"] = "Portfolio-Nachweis"
        payload["channel_copy"]["body"] = (
            "Die Dokumentation führt ein Portfolio von mehr als 50 Anwendungen in sieben Kategorien."
        )
        payload["channel_copy"]["carousel_slides"] = []

        class SafePortfolioClient:
            provider = "local_qwen"
            model = "qwen-portfolio"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return payload

        generated = ContentGenerator([SafePortfolioClient()]).generate(
            self.make_brief(
                campaign_id="k5",
                campaign="App-Entwicklung (50+ Portfolio)",
                format="portfolio_carousel",
                cta="App-Modernisierungscheck anfragen",
            )
        )

        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertTrue(generated.provenance["deterministic_structure_fill"])
        self.assertEqual(len(generated.channel_copy["carousel_slides"]), 3)
        self.assertTrue(generated.review_notes[0].startswith("Carousel-Struktur"))

    def test_thin_lfa_reel_gets_safe_production_structure_and_cta(self):
        payload = self.valid_ai_payload()
        payload["reel"] = {
            "idea": "LFA kurz einordnen",
            "format": "9:16 Reel",
            "hook": "LFA",
            "script": ["LFA ist ein digitales Lernsystem für Fachinformatiker-Azubis und Ausbilder."],
            "shot_list": ["Textkarte"],
            "on_screen_text": ["LFA"],
            "caption": "LFA ist ein digitales Lernsystem für Fachinformatiker-Azubis und Ausbilder.",
            "cta": "",
            "editing_notes": "",
        }

        class ThinReelClient:
            provider = "local_qwen"
            model = "qwen-thin-reel"
            route_name = "local_content_draft"

            def complete_json(self, **kwargs):
                return payload

        generated = ContentGenerator([ThinReelClient()]).generate(
            self.make_brief(
                campaign_id="k3",
                campaign="LFA - Lernzentrum Für Azubis",
                channel="Instagram",
                format="reel",
                cta="LFA-Demo anfragen",
                hashtags=["Ausbildung", "FIAE"],
            )
        )

        self.assertEqual(generated.provenance["status"], "ai_generated")
        self.assertTrue(generated.provenance["deterministic_structure_fill"])
        self.assertIn("LFA-Demo anfragen", generated.reel["script"])
        self.assertIn("LFA-Demo anfragen", generated.reel["on_screen_text"])
        self.assertIn("für Fachinformatiker-Azubis", generated.public_copy)


if __name__ == "__main__":
    unittest.main()

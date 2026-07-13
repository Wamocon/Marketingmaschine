from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.api import create_content, trend_intake_policy_status
from marketing_machine.storage import JsonStore


class TrendIntakePolicyTests(unittest.TestCase):
    @staticmethod
    def _generated_state(brief):
        return {
            "brief": brief.to_dict(),
            "approval": None,
            "errors": [],
            "next_step": "human_review",
            "requires_human_review": True,
            "evidence_records": [],
            "scheduler_payload": {},
        }

    @staticmethod
    def _verified_run(*, campaign_id: str = "kampagne_1_consulting_qa") -> dict:
        now = datetime.now(timezone.utc)
        published = (now - timedelta(days=1)).isoformat()
        checked = now.isoformat()
        topic = "Software quality release risk"
        urls = [
            "https://publisher-one.com/software-quality-release-risk",
            "https://publisher-two.net/software-quality-release-risk",
        ]
        citations = [
            {
                "url": url,
                "title": f"Software quality release risk report {index}",
                "snippet": "Software quality and release risk remain the exact subject.",
                "published": published,
                "retrieved": checked,
            }
            for index, url in enumerate(urls, start=1)
        ]
        return {
            "id": "trend-run-manual-intake",
            "status": "verified_sources",
            "run_started_at": checked,
            "campaigns": [
                {
                    "campaign": {"id": campaign_id, "name": "K1 QA & Testing"},
                    "trends": [
                        {
                            "id": "trend-software-quality-risk",
                            "topic": topic,
                            "trend_type": "current_trend",
                            "source_urls": urls,
                            "citations": citations,
                            "verification": {
                                "status": "verified_recent",
                                "verified": True,
                                "last_checked_at": checked,
                                "evidence_count": 2,
                            },
                        }
                    ],
                }
            ],
        }

    def test_enabled_policy_requires_an_explicit_content_mode(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "MARKETING_MACHINE_DATA_DIR": tmp,
                    "MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE": "true",
                },
                clear=False,
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            create_content({"id": "missing-mode", "campaign_id": "k1"})

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("content_mode is required", str(raised.exception.detail))

    def test_invalid_policy_configuration_blocks_intake(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "MARKETING_MACHINE_DATA_DIR": tmp,
                    "MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE": "sometimes",
                },
                clear=False,
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            create_content(
                {
                    "id": "invalid-policy",
                    "campaign_id": "k1",
                    "content_mode": "evergreen",
                }
            )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("policy is invalid", str(raised.exception.detail))

    def test_invalid_policy_configuration_is_not_ready(self):
        with patch.dict(
            os.environ,
            {"MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE": "sometimes"},
            clear=False,
        ):
            status = trend_intake_policy_status()

        self.assertFalse(status["safe"])
        self.assertEqual(status["status"], "blocked_invalid_trend_intake_policy")

    def test_explicit_evergreen_is_stored_without_trend_provenance(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "MARKETING_MACHINE_DATA_DIR": tmp,
                    "MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE": "true",
                },
                clear=False,
            ),
            patch(
                "marketing_machine.api.create_state_for_brief",
                side_effect=self._generated_state,
            ),
        ):
            result = create_content(
                {
                    "id": "explicit-evergreen",
                    "campaign_id": "k1",
                    "content_mode": "evergreen",
                }
            )

        brief = result["state"]["brief"]
        self.assertEqual(brief["content_mode"], "evergreen")
        self.assertEqual(brief["campaign_context"]["content_mode"], "evergreen")
        self.assertEqual(brief["trend_run_id"], "")
        self.assertEqual(brief["trend_id"], "")
        self.assertEqual(brief["trend_sources"], [])
        self.assertEqual(brief["citations"], [])

    def test_disabled_explicitness_policy_only_defaults_to_evergreen(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "MARKETING_MACHINE_DATA_DIR": tmp,
                    "MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE": "false",
                },
                clear=True,
            ),
            patch(
                "marketing_machine.api.create_state_for_brief",
                side_effect=self._generated_state,
            ),
        ):
            result = create_content({"id": "legacy-evergreen", "campaign_id": "k1"})

        self.assertEqual(result["state"]["brief"]["content_mode"], "evergreen")
        self.assertEqual(result["state"]["brief"]["trend_id"], "")

    def test_deprecated_verified_trends_name_is_only_an_explicit_mode_alias(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "MARKETING_MACHINE_DATA_DIR": tmp,
                    "MARKETING_MACHINE_REQUIRE_VERIFIED_TRENDS": "false",
                },
                clear=True,
            ),
            patch(
                "marketing_machine.api.create_state_for_brief",
                side_effect=self._generated_state,
            ),
        ):
            result = create_content({"id": "alias-evergreen", "campaign_id": "k1"})
            status = trend_intake_policy_status()

        self.assertEqual(result["state"]["brief"]["content_mode"], "evergreen")
        self.assertTrue(status["safe"])
        self.assertTrue(status["deprecated_alias_in_use"])
        self.assertFalse(status["unverified_current_trends_allowed"])

    def test_conflicting_preferred_and_deprecated_settings_fail_closed(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "MARKETING_MACHINE_DATA_DIR": tmp,
                    "MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE": "true",
                    "MARKETING_MACHINE_REQUIRE_VERIFIED_TRENDS": "false",
                },
                clear=True,
            ),
        ):
            status = trend_intake_policy_status()
            with self.assertRaises(HTTPException) as raised:
                create_content(
                    {
                        "id": "conflicting-policy",
                        "campaign_id": "k1",
                        "content_mode": "evergreen",
                    }
                )

        self.assertFalse(status["safe"])
        self.assertEqual(status["status"], "blocked_invalid_trend_intake_policy")
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn(
            "explicit content-mode policy is invalid", str(raised.exception.detail)
        )

    def test_disabling_explicit_mode_never_allows_unverified_current_trend(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "MARKETING_MACHINE_DATA_DIR": tmp,
                    "MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE": "false",
                },
                clear=True,
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            create_content(
                {
                    "id": "unverified-current-trend",
                    "campaign_id": "k1",
                    "content_mode": "current_trend",
                    "trend_run_id": "missing-trend-run",
                    "trend_id": "missing-trend",
                }
            )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn(
            "stored trend selection was not found", str(raised.exception.detail)
        )

    def test_evergreen_rejects_any_trend_reference_or_assertion(self):
        invalid_payloads = (
            {"trend_run_id": "trend-run-manual-intake"},
            {"trend_id": "trend-software-quality-risk"},
            {"trend_sources": []},
            {"trend_verification_status": ""},
            {"citations": []},
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "MARKETING_MACHINE_DATA_DIR": tmp,
                    "MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE": "true",
                },
                clear=False,
            ),
        ):
            for index, extra in enumerate(invalid_payloads):
                with (
                    self.subTest(extra=extra),
                    self.assertRaises(HTTPException) as raised,
                ):
                    create_content(
                        {
                            "id": f"evergreen-with-trend-{index}",
                            "campaign_id": "k1",
                            "content_mode": "evergreen",
                            **extra,
                        }
                    )
                self.assertEqual(raised.exception.status_code, 422)

    def test_evergreen_cannot_smuggle_a_current_trend_claim_in_generation_fields(self):
        claim_fields = (
            {"objective": "Explain the latest software quality trend this week."},
            {"cta": "Read the current trend report"},
            {"format": "Trending topic explainer"},
            {"hashtags": ["#B2B", "#LatestTrend"]},
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "MARKETING_MACHINE_DATA_DIR": tmp,
                    "MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE": "true",
                },
                clear=False,
            ),
        ):
            for index, fields in enumerate(claim_fields):
                with (
                    self.subTest(fields=fields),
                    self.assertRaises(HTTPException) as raised,
                ):
                    create_content(
                        {
                            "id": f"evergreen-latest-claim-{index}",
                            "campaign_id": "k1",
                            "content_mode": "evergreen",
                            **fields,
                        }
                    )

                self.assertEqual(raised.exception.status_code, 422)
                self.assertIn(
                    "must not request a current or trending claim",
                    str(raised.exception.detail),
                )

    def test_current_trend_rebuilds_provenance_from_the_stored_run(self):
        run = self._verified_run()
        with tempfile.TemporaryDirectory() as tmp:
            JsonStore(Path(tmp)).save_trend_run(run)
            with (
                patch.dict(
                    os.environ,
                    {
                        "MARKETING_MACHINE_DATA_DIR": tmp,
                        "MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE": "true",
                    },
                    clear=False,
                ),
                patch(
                    "marketing_machine.api.create_state_for_brief",
                    side_effect=self._generated_state,
                ),
            ):
                result = create_content(
                    {
                        "id": "stored-current-trend",
                        "campaign_id": "k1",
                        "content_mode": "current_trend",
                        "trend_run_id": run["id"],
                        "trend_id": "trend-software-quality-risk",
                    }
                )

        brief = result["state"]["brief"]
        stored_trend = run["campaigns"][0]["trends"][0]
        self.assertEqual(brief["content_mode"], "current_trend")
        self.assertEqual(brief["trend_summary"], stored_trend["topic"])
        self.assertEqual(brief["trend_sources"], stored_trend["source_urls"])
        self.assertEqual(brief["trend_verification_status"], "verified_recent")
        self.assertEqual(
            [item["url"] for item in brief["citations"]],
            stored_trend["source_urls"],
        )

    def test_unverified_or_cross_campaign_stored_trends_are_blocked(self):
        cases = []
        unverified = self._verified_run()
        unverified["campaigns"][0]["trends"][0]["verification"]["verified"] = False
        cases.append(unverified)
        cases.append(self._verified_run(campaign_id="kampagne_2_ki_sokrates"))

        for index, run in enumerate(cases):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                JsonStore(Path(tmp)).save_trend_run(run)
                with (
                    patch.dict(
                        os.environ,
                        {
                            "MARKETING_MACHINE_DATA_DIR": tmp,
                            "MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE": "true",
                        },
                        clear=False,
                    ),
                    patch("marketing_machine.api.create_state_for_brief") as generate,
                ):
                    with self.assertRaises(HTTPException) as raised:
                        create_content(
                            {
                                "id": f"blocked-current-trend-{index}",
                                "campaign_id": "k1",
                                "content_mode": "current_trend",
                                "trend_run_id": run["id"],
                                "trend_id": "trend-software-quality-risk",
                            }
                        )
                self.assertEqual(raised.exception.status_code, 422)
                generate.assert_not_called()

    def test_current_trend_rejects_caller_supplied_evidence_even_when_references_exist(
        self,
    ):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "MARKETING_MACHINE_DATA_DIR": tmp,
                    "MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE": "true",
                },
                clear=False,
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            create_content(
                {
                    "id": "caller-asserted-evidence",
                    "campaign_id": "k1",
                    "content_mode": "current_trend",
                    "trend_run_id": "trend-run-manual-intake",
                    "trend_id": "trend-software-quality-risk",
                    "trend_sources": ["https://caller.invalid/claim"],
                }
            )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("cannot assert trend evidence", str(raised.exception.detail))


if __name__ == "__main__":
    unittest.main()

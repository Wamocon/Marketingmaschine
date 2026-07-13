import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.analytics import evaluate_performance, validate_performance_record
from marketing_machine.schemas import OptimizationAction, PerformanceRecord
from marketing_machine.storage import JsonStore, StateRevisionConflict


class AnalyticsTests(unittest.TestCase):
    @staticmethod
    def valid_record(**overrides):
        values = {
            "content_id": "c1",
            "review_window": "7d",
            "impressions": 1000,
            "clicks": 50,
            "leads": 2,
            "qualified_leads": 1,
            "booked_calls": 1,
            "pipeline_value_eur": 500.0,
            "landing_page_visits": 40,
            "landing_page_conversions": 2,
            "source_system": "manual",
            "source_ref": "postiz-export-2026-07-10.csv",
            "period_start": "2026-07-01T00:00:00+00:00",
            "period_end": "2026-07-08T00:00:00+00:00",
            "retrieved_at": "2026-07-08T01:00:00+00:00",
            "operator": "M. Beispiel",
            "attribution_rule": "utm_last_touch_30d",
            "evidence": [
                {
                    "system": "manual",
                    "ref": "postiz-export-2026-07-10.csv",
                    "retrieved_at": "2026-07-08T01:00:00+00:00",
                    "sha256": "a" * 64,
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
        values.update(overrides)
        return PerformanceRecord(**values)

    def test_clicks_without_leads_fix_landing_page(self):
        decision = evaluate_performance(
            PerformanceRecord(content_id="c1", review_window="7d", impressions=1000, clicks=50, leads=0)
        )
        self.assertEqual(decision.action, OptimizationAction.FIX_LANDING_PAGE)

    def test_qualified_lead_scales(self):
        decision = evaluate_performance(
            PerformanceRecord(content_id="c1", review_window="14d", impressions=1000, clicks=20, leads=2, qualified_leads=1)
        )
        self.assertEqual(decision.action, OptimizationAction.SCALE)

    def test_no_signal_after_14_days_stops(self):
        decision = evaluate_performance(
            PerformanceRecord(content_id="c1", review_window="14d", impressions=100, clicks=0, leads=0)
        )
        self.assertEqual(decision.action, OptimizationAction.STOP)

    def test_funnel_invariants_reject_impossible_metrics(self):
        cases = {
            "qualified_leads": self.valid_record(leads=1, qualified_leads=2, booked_calls=0, pipeline_value_eur=0),
            "booked_calls": self.valid_record(qualified_leads=1, booked_calls=2),
            "landing_page_conversions": self.valid_record(landing_page_visits=1, landing_page_conversions=2),
            "pipeline_value_eur": self.valid_record(leads=0, qualified_leads=0, booked_calls=0, pipeline_value_eur=1),
        }
        for expected, record in cases.items():
            with self.subTest(expected=expected):
                self.assertTrue(any(expected in item for item in validate_performance_record(record)))

    def test_analytics_requires_auditable_provenance(self):
        record = self.valid_record(
            source_system="manual",
            source_ref="",
            period_start="",
            period_end="bad-date",
            retrieved_at="2026-07-01T00:00:00",
            operator="",
            attribution_rule="",
            snapshot_sha256="not-a-digest",
        )

        errors = validate_performance_record(record)

        self.assertTrue(any("source_ref" in item for item in errors))
        self.assertTrue(any("operator" in item for item in errors))
        self.assertTrue(any("period_start" in item for item in errors))
        self.assertTrue(any("period_end" in item for item in errors))
        self.assertTrue(any("retrieved_at" in item for item in errors))
        self.assertTrue(any("attribution_rule" in item for item in errors))
        self.assertTrue(any("snapshot_sha256" in item for item in errors))

    def test_each_evidence_timestamp_must_cover_the_period_and_precede_submission(self):
        before_period = self.valid_record(
            evidence=[
                {
                    **self.valid_record().evidence[0],
                    "retrieved_at": "2026-07-07T23:59:59+00:00",
                }
            ]
        )
        after_submission = self.valid_record(
            evidence=[
                {
                    **self.valid_record().evidence[0],
                    "retrieved_at": "2026-07-08T01:00:01+00:00",
                }
            ]
        )

        self.assertTrue(
            any("cannot be before period_end" in error for error in validate_performance_record(before_period))
        )
        self.assertTrue(
            any(
                "cannot be after the submission" in error
                for error in validate_performance_record(after_submission)
            )
        )

    def test_performance_natural_key_is_idempotent_and_conflict_safe(self):
        payload = {
            "record": asdict(self.valid_record()),
            "action": "scale",
            "reason": "qualified commercial signal detected",
            "request_fingerprint": "same-fingerprint",
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            first, first_retry = store.save_performance_once(payload)
            retry, exact_retry = store.save_performance_once(dict(payload))
            conflicting = {**payload, "request_fingerprint": "different-fingerprint"}
            with self.assertRaises(StateRevisionConflict):
                store.save_performance_once(conflicting)

            self.assertFalse(first_retry)
            self.assertTrue(exact_retry)
            self.assertEqual(first, retry)
            self.assertEqual(len(store.list_performance(limit=10)), 1)

    def test_correction_timestamp_cannot_precede_the_current_revision(self):
        original = {
            "record": asdict(self.valid_record()),
            "action": "scale",
            "reason": "qualified commercial signal detected",
            "request_fingerprint": "a" * 64,
        }
        corrected = {
            **original,
            "record": {**original["record"], "impressions": 1001},
            "request_fingerprint": "b" * 64,
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.save_performance_once(original)
            with self.assertRaisesRegex(ValueError, "cannot be before"):
                store.save_performance_correction(
                    corrected,
                    supersedes_fingerprint="a" * 64,
                    correction_reason="Corrected source export after review.",
                    operator="M. Beispiel",
                    corrected_at="2020-01-01T00:00:00+00:00",
                )

    def test_later_correction_cannot_precede_superseded_revision_creation(self):
        record = asdict(self.valid_record())
        record["created_at"] = "2026-07-01T10:00:00+00:00"
        original = {
            "record": record,
            "action": "scale",
            "reason": "initial measurement",
            "request_fingerprint": "a" * 64,
        }
        first_revision = {
            **original,
            "record": {
                **record,
                "impressions": 1001,
                "created_at": "2026-07-10T10:00:00+00:00",
            },
            "request_fingerprint": "b" * 64,
        }
        second_revision = {
            **first_revision,
            "record": {
                **first_revision["record"],
                "impressions": 1002,
                "created_at": "2026-07-10T12:00:00+00:00",
            },
            "request_fingerprint": "c" * 64,
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.save_performance_once(original)
            store.save_performance_correction(
                first_revision,
                supersedes_fingerprint="a" * 64,
                correction_reason="First corrected source export.",
                operator="M. Beispiel",
                corrected_at="2026-07-10T09:00:00+00:00",
            )
            with self.assertRaisesRegex(ValueError, "cannot be before"):
                store.save_performance_correction(
                    second_revision,
                    supersedes_fingerprint="b" * 64,
                    correction_reason="Second corrected source export.",
                    operator="M. Beispiel",
                    corrected_at="2026-07-10T09:30:00+00:00",
                )


if __name__ == "__main__":
    unittest.main()

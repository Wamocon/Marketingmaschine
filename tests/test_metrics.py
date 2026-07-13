import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.metrics import render_prometheus_metrics
from marketing_machine.storage import JsonStore


class MetricsTests(unittest.TestCase):
    def test_metrics_expose_operational_counts_without_content_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.save_state(
                {
                    "brief": {
                        "id": "k1-metrics-item",
                        "campaign_id": "k1",
                        "campaign": "Sensitive campaign title must not leak",
                        "status": "needs_human_review",
                        "updated_at": "2026-07-10T12:00:00+00:00",
                        "generation": {"status": "ai_generated", "provider": "local_qwen"},
                    },
                    "next_step": "human_review",
                    "requires_human_review": True,
                }
            )
            store.save_trend_run(
                {
                    "id": "trend-metrics-run",
                    "status": "needs_source_verification",
                    "run_started_at": "2026-07-10T12:01:00+00:00",
                    "campaigns": [],
                }
            )

            output = render_prometheus_metrics(store)

        self.assertIn("marketing_machine_up 1", output)
        self.assertIn("marketing_machine_campaign_catalog_total 5", output)
        self.assertIn("marketing_machine_campaign_catalog_load_error 0", output)
        self.assertIn('campaign_id="k1",status="needs_human_review"} 1', output)
        self.assertIn("marketing_machine_review_attention_items 1", output)
        self.assertIn("marketing_machine_ai_generated_items 1", output)
        self.assertIn('status="needs_source_verification"} 1', output)
        self.assertNotIn("Sensitive campaign title", output)

    def test_catalog_load_failure_is_visible_instead_of_reporting_static_five(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "marketing_machine.metrics.load_campaign_catalog",
            side_effect=ValueError("invalid campaign document"),
        ):
            output = render_prometheus_metrics(JsonStore(Path(tmp)))

        self.assertIn("marketing_machine_campaign_catalog_total 0", output)
        self.assertIn("marketing_machine_campaign_catalog_load_error 1", output)


if __name__ == "__main__":
    unittest.main()

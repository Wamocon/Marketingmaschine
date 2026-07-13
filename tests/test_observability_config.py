import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ObservabilityConfigTests(unittest.TestCase):
    def test_supported_images_are_pinned_and_admin_ports_are_loopback_only(self):
        compose = (ROOT / "deploy" / "observability" / "docker-compose.hardened.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("prom/prometheus:v3.13.0@sha256:c6b27ea", compose)
        self.assertIn("grafana/grafana:13.1.0@sha256:121a7a9", compose)
        self.assertNotIn("prom/prometheus:v2.55.0", compose)
        self.assertNotIn("grafana/grafana:11.2.0", compose)
        self.assertIn("127.0.0.1:9091:9090", compose)
        self.assertIn("127.0.0.1:3030:3000", compose)
        self.assertIn("SHARED_GRAFANA_DATA_VOLUME:-shared-infra-stage_", compose)
        self.assertNotIn("SHARED_REDIS_PASSWORD", compose)
        self.assertNotIn("shared-redis:", compose)

        optional_cache = (
            ROOT / "deploy" / "observability" / "docker-compose.optional-cache.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("shared_redis_password", optional_cache)
        self.assertIn("/tmp/redis.conf", optional_cache)
        self.assertNotIn("SHARED_REDIS_PASSWORD:", optional_cache)
        self.assertNotIn("--requirepass", optional_cache)

    def test_campaign_catalog_alert_includes_load_failures(self):
        rules = (
            ROOT / "deploy" / "observability" / "rules" / "marketing-machine.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("marketing_machine_campaign_catalog_total != 5", rules)
        self.assertIn("marketing_machine_campaign_catalog_load_error == 1", rules)

    def test_marketing_dashboard_is_valid_and_has_no_edit_mode(self):
        path = (
            ROOT
            / "deploy"
            / "observability"
            / "grafana"
            / "provisioning"
            / "dashboards"
            / "marketing-machine.json"
        )
        dashboard = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(dashboard["uid"], "wamocon-marketing")
        self.assertFalse(dashboard["editable"])
        self.assertGreaterEqual(len(dashboard["panels"]), 7)


if __name__ == "__main__":
    unittest.main()

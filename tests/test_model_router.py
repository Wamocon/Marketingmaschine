import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.model_router import ModelRouter


class ModelRouterTests(unittest.TestCase):
    def router(self):
        return ModelRouter.from_json_file(Path(__file__).resolve().parents[1] / "config" / "model-routing.json")

    def test_kimi_backup_route_is_networked_and_human_approved(self):
        route = self.router().route("cloud_kimi_backup")
        self.assertEqual(route.provider, "kimi_backup")
        self.assertTrue(route.requires_network)
        self.assertTrue(route.requires_human_final_approval)

    def test_resolves_local_endpoint_and_model_from_environment(self):
        route = self.router().resolve(
            "local_content_draft",
            environ={
                "LOCAL_OPENAI_BASE_URL": "http://qwen.test/v1",
                "LOCAL_OPENAI_MODEL_NAME": "qwen-runtime",
            },
        )

        self.assertTrue(route.configured)
        self.assertEqual(route.base_url, "http://qwen.test/v1")
        self.assertEqual(route.model, "qwen-runtime")
        self.assertEqual(route.api_key, "")

    def test_route_chain_marks_unconfigured_cloud_fallback_without_exposing_secret(self):
        routes = self.router().resolve_chain(
            "local_content_draft",
            environ={
                "LOCAL_OPENAI_BASE_URL": "http://qwen.test/v1",
                "LOCAL_MODEL_NAME": "qwen-local",
                "KIMI_BASE_URL": "https://api.example.invalid/v1",
                "KIMI_MODEL_NAME": "kimi-test",
            },
        )

        self.assertEqual([route.name for route in routes], ["local_content_draft", "cloud_kimi_backup"])
        self.assertTrue(routes[0].configured)
        self.assertFalse(routes[1].configured)
        self.assertIn("api_key_not_configured", routes[1].configuration_errors)


if __name__ == "__main__":
    unittest.main()

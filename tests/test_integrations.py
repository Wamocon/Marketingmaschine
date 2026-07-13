import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.integrations import (
    check_comfyui_generation_readiness,
    check_firecrawl_configuration,
    check_growth_service,
    check_openai_compatible_models,
    disabled_cloud_model_status,
)
from marketing_machine.comfyui_qualification import (
    QUALIFICATION_NODE_INPUTS,
    QUALIFICATION_REQUIRED_PACKAGES,
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _size=None):
        return json.dumps(self.payload).encode("utf-8")


def comfy_stats(*, packages=None):
    rows = packages
    if rows is None:
        rows = [
            {"name": name, "installed": version, "required": version}
            for name, version in sorted(QUALIFICATION_REQUIRED_PACKAGES.items())
        ]
    return {
        "system": {
            "comfyui_version": "0.25.0",
            "python_version": "3.12.13 (main)",
            "pytorch_version": "2.11.0+cu130",
            "comfy_package_versions": rows,
            "argv": ["main.py", "--listen", "127.0.0.1", "--port", "18189"],
            "deploy_environment": "manual",
        },
        "devices": [{"name": "NVIDIA GB10", "type": "cuda", "index": 0}],
    }


def comfy_node_schema(node_name, *, model_available=True):
    inputs = {name: ["ANY"] for name in QUALIFICATION_NODE_INPUTS[node_name]}
    if node_name == "UNETLoader":
        inputs["unet_name"] = [["flux1-schnell.safetensors"] if model_available else []]
    elif node_name == "DualCLIPLoader":
        inputs["clip_name1"] = [["t5xxl_fp8_e4m3fn.safetensors"]]
        inputs["clip_name2"] = [["clip_l.safetensors"]]
    elif node_name == "VAELoader":
        inputs["vae_name"] = [["ae.safetensors"]]
    return {node_name: {"input": {"required": inputs}}}


def comfy_read_only_get(stats, *, model_available=True, history=None):
    def fake_get(url):
        if url.endswith("/system_stats"):
            return stats
        if "/object_info/" in url:
            return comfy_node_schema(url.rsplit("/", 1)[1], model_available=model_available)
        if "/view_metadata/vae?" in url:
            return {"format": "pt"}
        if url.endswith("/history?max_items=64"):
            return history or {}
        raise AssertionError(f"unexpected ComfyUI probe: {url}")

    return fake_get


class IntegrationTests(unittest.TestCase):
    def test_deployment_checks_qdrant_on_the_shared_docker_network(self):
        root = Path(__file__).resolve().parents[1]
        compose = (root / "deploy" / "docker-compose.existing-stack.yml").read_text(encoding="utf-8")

        self.assertIn("QDRANT_BASE_URL: ${QDRANT_BASE_URL:-http://core-qdrant:6333}", compose)
        self.assertNotIn("QDRANT_BASE_URL: http://host.docker.internal:6333", compose)

    def test_operator_comfyui_proxy_uses_the_approved_private_target(self):
        root = Path(__file__).resolve().parents[1]
        nginx = (root / "deploy" / "network-access" / "nginx.conf").read_text(encoding="utf-8")

        self.assertIn("proxy_pass http://__WAMOCON_COMFYUI_UPSTREAM__", nginx)
        self.assertNotIn("10.100.104.2", nginx)
        self.assertNotIn("proxy_pass http://host.docker.internal:8188", nginx)

    def test_network_edge_is_patched_and_reaches_grafana_on_its_docker_network(self):
        root = Path(__file__).resolve().parents[1]
        compose = (root / "deploy" / "docker-compose.network-access.yml").read_text(encoding="utf-8")
        nginx = (root / "deploy" / "network-access" / "nginx.conf").read_text(encoding="utf-8")

        self.assertIn("nginx:1.30.3-alpine@sha256:0d3b804", compose)
        self.assertIn("shared-network", compose)
        grafana_server = nginx.split("listen 3030 ssl;", 1)[1]
        self.assertIn("set $upstream http://shared-grafana:3000;", grafana_server)
        self.assertIn("proxy_pass $upstream;", grafana_server)
        self.assertNotIn("proxy_pass http://shared-grafana:3000", grafana_server)
        self.assertIn(
            "include /etc/nginx/conf.d/01-wamocon-client-access.conf;",
            grafana_server,
        )
        self.assertNotIn("192.168.178.39", nginx)
        self.assertNotIn("192.168.178.81", nginx)

    def test_mautic_healthcheck_follows_redirects_before_reporting_healthy(self):
        root = Path(__file__).resolve().parents[1]
        compose = (root / "deploy" / "docker-compose.growth-tools.yml").read_text(encoding="utf-8")

        self.assertIn("curl --fail --location", compose)

    def test_growth_tool_reachability_does_not_claim_api_configuration(self):
        with patch(
            "marketing_machine.integrations.urlopen",
            return_value=FakeResponse({"register": False}, status=200),
        ):
            result = check_growth_service(
                "postiz",
                "http://postiz:5000",
                probe_path="/api/auth/can-register",
                endpoint_path="/api/public/v1/posts",
                api_key="",
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["reachable"])
        self.assertFalse(result["configured"])
        self.assertFalse(result["write_ready"])
        self.assertFalse(result["used_successfully"])

    def test_postiz_open_registration_is_reachable_but_unsafe_for_writes(self):
        with patch(
            "marketing_machine.integrations.urlopen",
            return_value=FakeResponse({"register": True}, status=200),
        ):
            result = check_growth_service(
                "postiz",
                "http://postiz:5000",
                probe_path="/api/auth/can-register",
                endpoint_path="/api/public/v1/posts",
                api_key="configured-key",
                contract_verified=True,
            )

        self.assertTrue(result["reachable"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["registration_open"])
        self.assertFalse(result["security_safe"])
        self.assertFalse(result["write_ready"])

    def test_growth_tool_write_preflight_never_claims_successful_use(self):
        with patch("marketing_machine.integrations.urlopen", return_value=FakeResponse({}, status=200)):
            result = check_growth_service(
                "twenty",
                "http://twenty:3000",
                probe_path="/healthz",
                endpoint_path="/rest/people",
                api_key="configured-but-not-sent",
            )

        self.assertTrue(result["configured"])
        self.assertFalse(result["write_ready"])
        self.assertFalse(result["contract_verified"])
        self.assertFalse(result["used_successfully"])
        self.assertEqual(result["capability"], "read_only_api_preflight")

    def test_comfyui_process_without_recognized_model_is_not_generation_ready(self):
        with patch(
            "marketing_machine.integrations._get_json",
            side_effect=comfy_read_only_get(comfy_stats(), model_available=False),
        ):
            result = check_comfyui_generation_readiness("http://comfyui:18189", required=True)

        self.assertTrue(result["reachable"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["recognized_model_count"], 0)
        self.assertEqual(result["package_mismatches"], [])
        self.assertTrue(result["runtime_compatible"])

    def test_comfyui_recognized_unet_passes_read_only_generation_preflight(self):
        with patch(
            "marketing_machine.integrations._get_json",
            side_effect=comfy_read_only_get(comfy_stats()),
        ):
            result = check_comfyui_generation_readiness("http://comfyui:18189")

        self.assertTrue(result["ok"])
        self.assertTrue(result["model_bundle_ready"])
        self.assertTrue(result["runtime_compatible"])
        self.assertTrue(result["package_telemetry_complete"])
        self.assertTrue(result["node_schemas_compatible"])
        self.assertEqual(result["workflow_qualification"], "history_not_verified")
        self.assertEqual(result["recognized_models"], ["flux1-schnell.safetensors"])
        self.assertFalse(result["used_successfully"])

    def test_comfyui_package_mismatch_blocks_readiness_without_hiding_reachability(self):
        rows = [
            {"name": name, "installed": version, "required": version}
            for name, version in sorted(QUALIFICATION_REQUIRED_PACKAGES.items())
        ]
        rows[0]["installed"] = "0.0.0"
        with patch(
            "marketing_machine.integrations._get_json",
            side_effect=comfy_read_only_get(comfy_stats(packages=rows)),
        ):
            result = check_comfyui_generation_readiness("http://comfyui:18189", required=True)

        self.assertTrue(result["reachable"])
        self.assertTrue(result["model_bundle_ready"])
        self.assertFalse(result["runtime_compatible"])
        self.assertFalse(result["package_telemetry_complete"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["workflow_qualification"], "history_not_verified")
        self.assertIn("package telemetry", result["action"])

    def test_comfyui_candidate_manifest_is_isolated_and_internally_consistent(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (root / "deploy" / "comfyui" / "flux-schnell-candidate-manifest.json").read_text(
                encoding="utf-8"
            )
        )

        guard = manifest["production_guard"]
        model_bundle = manifest["model_bundle"]
        files = model_bundle["files"]
        self.assertEqual(manifest["scope"], "isolated-candidate-only")
        self.assertNotIn(guard["candidate_root"], guard["forbidden_roots"])
        self.assertEqual(guard["candidate_bind"], "127.0.0.1")
        self.assertNotEqual(guard["candidate_port"], 8188)
        self.assertFalse(guard["allow_model_symlinks_to_production"])
        self.assertFalse(guard["allow_custom_nodes"])
        self.assertFalse(guard["allow_production_service_restart"])
        self.assertEqual(sum(item["bytes"] for item in files), model_bundle["expected_total_bytes"])
        self.assertTrue(all(len(item["sha256"]) == 64 for item in files))
        self.assertEqual(manifest["runtime"]["core_loader_node"], "UNETLoader")
        self.assertTrue(manifest["readiness"]["package_mismatches_must_be_empty"])

    def test_growth_tool_images_are_pinned_and_postiz_has_a_real_healthcheck(self):
        root = Path(__file__).resolve().parents[1]
        compose = (root / "deploy" / "docker-compose.growth-tools.yml").read_text(encoding="utf-8")

        self.assertNotIn("postiz-app:latest", compose)
        self.assertNotIn("twenty:${TWENTY_TAG:-latest}", compose)
        self.assertNotIn("mautic/mautic:latest", compose)
        self.assertIn("/api/auth/can-register", compose)
        self.assertIn("POSTIZ_DISABLE_REGISTRATION:-true", compose)
        self.assertIn("j.register!==false", compose)

    def test_firecrawl_health_is_truthful_without_spending_search_credit(self):
        missing = check_firecrawl_configuration("https://api.firecrawl.dev/v2", "")
        configured = check_firecrawl_configuration("https://api.firecrawl.dev/v2", "secret-not-used")
        self_hosted = check_firecrawl_configuration(
            "http://firecrawl:3002/v2",
            "",
            allow_unauthenticated_self_hosted=True,
        )
        unsafe_public_no_auth = check_firecrawl_configuration(
            "https://firecrawl.public.example.com/v2",
            "",
            allow_unauthenticated_self_hosted=True,
        )

        self.assertFalse(missing["ok"])
        self.assertFalse(missing["configured"])
        self.assertFalse(configured["ok"])
        self.assertTrue(configured["configured"])
        self.assertIsNone(configured["reachable"])
        self.assertFalse(configured["used_successfully"])
        self.assertEqual(configured["capability"], "configuration_only")
        self.assertEqual(configured["authentication_mode"], "api_key")
        self.assertTrue(self_hosted["configured"])
        self.assertEqual(self_hosted["authentication_mode"], "private_self_hosted_no_auth")
        self.assertFalse(unsafe_public_no_auth["configured"])

    def test_firecrawl_self_hosted_no_auth_is_explicit_and_defaults_off_in_compose(self):
        root = Path(__file__).resolve().parents[1]
        for relative in (
            "deploy/docker-compose.candidate.yml",
            "deploy/docker-compose.existing-stack.yml",
        ):
            compose = (root / relative).read_text(encoding="utf-8")
            self.assertIn(
                "FIRECRAWL_ALLOW_UNAUTHENTICATED_SELF_HOSTED: ${FIRECRAWL_ALLOW_UNAUTHENTICATED_SELF_HOSTED:-false}",
                compose,
            )

    def test_openai_compatible_check_does_not_pass_without_key(self):
        result = check_openai_compatible_models("kimi", "https://api.example.invalid/v1", "")
        self.assertFalse(result["ok"])
        self.assertFalse(result["configured"])
        self.assertEqual(result["error"], "API key not configured")

    def test_openai_compatible_check_verifies_configured_model(self):
        payload = {"data": [{"id": "kimi-best"}, {"id": "kimi-safe-review"}]}
        with patch("marketing_machine.integrations.urlopen", return_value=FakeResponse(payload)):
            result = check_openai_compatible_models(
                "kimi",
                "https://api.example.invalid/v1",
                "secret-value",
                "kimi-safe-review",
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["configured"])
        self.assertTrue(result["model_present"])
        self.assertEqual(result["available_models"], ["kimi-best", "kimi-safe-review"])

    def test_disabled_cloud_model_status_is_local_and_explicit(self):
        result = disabled_cloud_model_status("kimi", configured=True, model_name="configured-model")

        self.assertFalse(result["ok"])
        self.assertTrue(result["configured"])
        self.assertIsNone(result["reachable"])
        self.assertFalse(result["used_successfully"])
        self.assertTrue(result["disabled_by_policy"])
        self.assertIn("endpoint", result["action"])
        self.assertIn("API key", result["action"])


if __name__ == "__main__":
    unittest.main()

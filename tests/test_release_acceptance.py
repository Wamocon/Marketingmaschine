from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "release_acceptance.py"
SPEC = importlib.util.spec_from_file_location("release_acceptance", SCRIPT_PATH)
assert SPEC and SPEC.loader
release_acceptance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_acceptance
SPEC.loader.exec_module(release_acceptance)


class FakeClient:
    def __init__(self) -> None:
        self.plain_probes: list[str] = []
        self.now = datetime.now(timezone.utc)
        self.extra_workflow: dict | None = None
        self.workflow_mutator = None
        self.execution_mutator = None
        self.state_mutator = None
        fixture = json.loads(
            (
                release_acceptance.REPOSITORY_ROOT
                / "tests"
                / "fixtures"
                / "content_quality"
                / "golden_pass_k1_k5.json"
            ).read_text(encoding="utf-8")
        )
        self.full_states: dict[str, dict] = {}
        for item in fixture["items"]:
            brief = deepcopy(item["brief"])
            campaign_id = brief["campaign_id"]
            content_id = f"{campaign_id}-current-draft"
            brief.update(
                {
                    "id": content_id,
                    "status": "needs_human_review",
                    "updated_at": self.now.isoformat(),
                }
            )
            brief["generation"]["provider"] = "local_qwen"
            brief["generation"]["model"] = "qwen3.6:35b"
            quality = release_acceptance.evaluate_content_quality(
                {"brief": brief},
                repo_root=release_acceptance.REPOSITORY_ROOT,
            )
            quality["evaluated_at"] = self.now.isoformat()
            brief["quality_evaluation"] = quality
            self.full_states[content_id] = {
                "brief": brief,
                "next_step": "human_review",
                "requires_human_review": True,
            }

    def prove_plain_http_closed(self, url: str):
        self.plain_probes.append(url)
        return {"url": url.replace("https://", "http://"), "outcome": "refused_or_closed"}

    @staticmethod
    def _actor(headers):
        encoded = headers["Authorization"].split(" ", 1)[1]
        return base64.b64decode(encoded).decode("utf-8").split(":", 1)[0]

    def get(self, url: str, *, headers=None):
        response_headers = {}
        body = b"{}"
        if url.endswith("/ui"):
            response_headers = {
                "content-security-policy": "frame-ancestors 'none'; base-uri 'self'",
                "x-frame-options": "DENY",
                "strict-transport-security": "max-age=31536000",
            }
        return release_acceptance.HttpResult(200, response_headers, body, url)

    def get_json(self, url: str, *, headers=None):
        now = self.now.isoformat()
        if url.endswith("/session"):
            return {"authenticated": True, "actor": self._actor(headers), "authentication": "edge_attested"}
        if url.endswith("/healthz") and ":18117" in url:
            return {"status": "ok", "instance": {"mode": "production", "disposable_data": False}}
        if url.endswith("/readyz"):
            return {
                "status": "ready",
                "mutation_authorization": {"safe": True},
                "actor_authentication": {"safe": True, "production_ready": True},
            }
        if url.endswith("/campaigns"):
            return {
                "count": 5,
                "demo_data_included": False,
                "items": [
                    {
                        "id": item,
                        "research": {
                            "status": "verified_recent",
                            "verified_trend_count": 1,
                            "run_id": "trend-real-five",
                        },
                        "content": {
                            "latest": {
                                "content_id": f"{item}-current-draft",
                                "campaign_id": item,
                                "quality_evaluation": {"release_ready": True},
                            }
                        },
                    }
                    for item in ("k1", "k2", "k3", "k4", "k5")
                ],
            }
        if "/workflows/states?" in url:
            return {
                "demo_data_included": False,
                "items": [
                    {
                        "content_id": state["brief"]["id"],
                        "campaign_id": state["brief"]["campaign_id"],
                        "status": state["brief"]["status"],
                        "updated_at": state["brief"]["updated_at"],
                        "generation": deepcopy(state["brief"]["generation"]),
                    }
                    for state in self.full_states.values()
                ],
            }
        if "/workflows/states/" in url:
            content_id = url.rsplit("/", 1)[1]
            payload = deepcopy(self.full_states[content_id])
            if self.state_mutator is not None:
                self.state_mutator(content_id, payload)
            return payload
        if "/workflows/trend-research/runs/trend-real-five" in url:
            source_ids = release_acceptance.CAMPAIGN_SOURCE_IDS
            return {
                "id": "trend-real-five",
                "run_started_at": now,
                "campaigns": [
                    {
                        "campaign": {"id": source_id},
                        "trends": [
                            {
                                "verification": {
                                    "status": "verified_recent",
                                    "eligible_for_content": True,
                                },
                                "citations": [
                                    {
                                        "url": f"https://source-{campaign_id}.example/a",
                                        "published": now,
                                    },
                                    {
                                        "url": f"https://independent-{campaign_id}.test/b",
                                        "published": "",
                                    },
                                ],
                            }
                        ],
                    }
                    for campaign_id, source_id in source_ids.items()
                ],
            }
        if url.endswith("/integrations/status"):
            checks = [
                {
                    "name": "n8n",
                    "ok": True,
                    "used_successfully": True,
                    "verification_basis": "persisted_trend_workflow_execution",
                    "last_execution_id": "174306",
                },
                {
                    "name": "comfyui",
                    "ok": True,
                    "model_bundle_ready": True,
                    "runtime_compatible": True,
                    "package_mismatches": [],
                    "used_successfully": True,
                    "workflow_qualification": "history_verified",
                    "last_output_artifact": "wamocon-release-qualification/example.png",
                    "last_output_sha256": "a" * 64,
                    "qualification_prompt_id": "68d55e04-86a2-40f8-a2d3-50223ec8349f",
                    "qualified_workflow_sha256": "b" * 64,
                    "qualification_runtime_identity_sha256": "c" * 64,
                    "qualification_model_files_sha256": "d" * 64,
                    "qualification_completed_at": now,
                },
                {"name": "ollama", "ok": True},
                {
                    "name": "local_openai",
                    "ok": True,
                    "used_successfully": True,
                    "last_generation_model": "qwen3.6:35b",
                },
                {"name": "searxng", "ok": True, "reachable": True, "used_successfully": True},
            ]
            return {"status": "ok", "required": checks[:4], "checks": checks}
        if url.endswith("/workflows/phase-status"):
            return {
                "status": "operational_with_blockers",
                "phases": [
                    {"id": "08_lead_plane", "metadata": {"external_writes_enabled": False}},
                    {"id": "09_publishing_plane", "metadata": {"external_writes_enabled": False}},
                ],
            }
        if "/api/v1/workflows?" in url:
            data = [
                {"id": workflow_id, "active": True}
                for workflow_id in release_acceptance.EXPECTED_ACTIVE_WORKFLOW_IDS
            ] + [
                {"id": workflow_id, "active": False}
                for workflow_id in release_acceptance.EXPECTED_INACTIVE_WORKFLOW_IDS
            ]
            if self.extra_workflow is not None:
                data.append(self.extra_workflow)
            return {"data": data, "nextCursor": None}
        if "/api/v1/workflows/" in url:
            workflow_id = url.rsplit("/", 1)[1]
            filename = release_acceptance.EXPECTED_N8N_WORKFLOW_FILES[workflow_id]
            payload = json.loads(
                (release_acceptance.N8N_WORKFLOW_ROOT / filename).read_text(encoding="utf-8")
            )
            for node in payload["nodes"]:
                for reference in node.get("credentials", {}).values():
                    reference["id"] = f"credential-{workflow_id}"
            if self.workflow_mutator is not None:
                self.workflow_mutator(workflow_id, payload)
            return payload
        if "/api/v1/executions/" in url:
            payload = {
                "id": "174306",
                "workflowId": release_acceptance.N8N_EXECUTION_EVIDENCE_WORKFLOW_ID,
                "status": "success",
                "finished": True,
                "stoppedAt": now,
            }
            if self.execution_mutator is not None:
                self.execution_mutator(payload)
            return payload
        raise AssertionError(f"unexpected URL: {url}")


def valid_comfyui_approval(now: datetime) -> dict:
    binding = {
        "output_sha256": "a" * 64,
        "prompt_id": "68d55e04-86a2-40f8-a2d3-50223ec8349f",
        "workflow_sha256": "b" * 64,
        "runtime_identity_sha256": "c" * 64,
        "model_files_sha256": "d" * 64,
    }
    binding_sha256 = release_acceptance._canonical_json_sha256(binding)
    return {
        "schema_version": release_acceptance.COMFYUI_APPROVAL_SCHEMA_VERSION,
        "qualification_binding": binding,
        "visual_approval": {
            "approved": True,
            "reviewer": "carla.creative",
            "approved_at": now.isoformat(),
            "qualification_binding_sha256": binding_sha256,
            "evidence_ref": "visual-review/2026-07/comfy-flux-qualification",
        },
        "license_approval": {
            "approved": True,
            "reviewer": "daniel.legal",
            "approved_at": now.isoformat(),
            "qualification_binding_sha256": binding_sha256,
            "evidence_ref": "legal-review/2026-07/flux-schnell-apache-2",
            "license_identifier": release_acceptance.COMFYUI_LICENSE_IDENTIFIER,
            "source_repository": release_acceptance.COMFYUI_LICENSE_SOURCE,
        },
    }


class ReleaseAcceptanceTests(unittest.TestCase):
    def test_script_has_no_insecure_tls_or_cli_secret_value_escape_hatch(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertNotIn("--insecure", source)
        self.assertNotIn("--operator-password", source)
        self.assertNotIn("--n8n-api-key\"", source)
        self.assertNotIn('method="POST"', source)

    def test_plain_http_probe_never_accepts_usable_ui_or_auth_challenge(self):
        observations = []

        class Handler(BaseHTTPRequestHandler):
            status = 200

            def do_GET(self):
                observations.append(self.headers.get("Authorization"))
                self.send_response(self.status)
                if self.status == 401:
                    self.send_header("WWW-Authenticate", 'Basic realm="unsafe"')
                self.end_headers()
                self.wfile.write(b"not a release endpoint")

            def log_message(self, _format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = release_acceptance.ReadOnlyHttpClient(timeout=2)
        url = f"https://127.0.0.1:{server.server_port}/ui"
        try:
            with self.assertRaisesRegex(AssertionError, "remained usable"):
                client.prove_plain_http_closed(url)
            Handler.status = 401
            with self.assertRaisesRegex(AssertionError, "authentication challenge"):
                client.prove_plain_http_closed(url)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(observations, [None, None])

    def test_read_only_gate_requires_and_verifies_full_release_contract(self):
        client = FakeClient()
        checks = release_acceptance.run_acceptance(
            console_url="https://marketing.example:18117",
            n8n_url="https://marketing.example:15678",
            operators=[
                release_acceptance.OperatorCredential("alice.reviewer", "secret-a"),
                release_acceptance.OperatorCredential("bob.reviewer", "secret-b"),
            ],
            n8n_api_key="n8n-read-key",
            comfyui_approval_evidence=valid_comfyui_approval(client.now),
            client=client,
        )
        self.assertEqual(len(client.plain_probes), 2)
        self.assertIn("n8n_exact_marketing_workflow_state", {item["name"] for item in checks})
        self.assertIn("comfyui_technical_qualification", {item["name"] for item in checks})
        self.assertIn("comfyui_named_visual_and_license_approval", {item["name"] for item in checks})
        self.assertTrue(all("secret" not in json.dumps(item) for item in checks))

    def test_gate_refuses_one_or_duplicate_operator(self):
        client = FakeClient()
        with self.assertRaisesRegex(AssertionError, "at least two"):
            release_acceptance.run_acceptance(
                console_url="https://marketing.example:18117",
                n8n_url="https://marketing.example:15678",
                operators=[release_acceptance.OperatorCredential("alice.reviewer", "secret-a")],
                n8n_api_key="key",
                comfyui_approval_evidence=valid_comfyui_approval(client.now),
                client=client,
            )
        with self.assertRaisesRegex(AssertionError, "distinct"):
            release_acceptance.run_acceptance(
                console_url="https://marketing.example:18117",
                n8n_url="https://marketing.example:15678",
                operators=[
                    release_acceptance.OperatorCredential("alice.reviewer", "secret-a"),
                    release_acceptance.OperatorCredential("alice.reviewer", "secret-b"),
                ],
                n8n_api_key="key",
                comfyui_approval_evidence=valid_comfyui_approval(client.now),
                client=client,
            )

    def test_gate_refuses_enabled_external_writes(self):
        class WriteEnabledClient(FakeClient):
            def get_json(self, url: str, *, headers=None):
                payload = super().get_json(url, headers=headers)
                if url.endswith("/workflows/phase-status"):
                    payload["phases"][1]["metadata"]["external_writes_enabled"] = True
                return payload

        client = WriteEnabledClient()
        with self.assertRaisesRegex(AssertionError, "external provider writes are enabled"):
            release_acceptance.run_acceptance(
                console_url="https://marketing.example:18117",
                n8n_url="https://marketing.example:15678",
                operators=[
                    release_acceptance.OperatorCredential("alice.reviewer", "secret-a"),
                    release_acceptance.OperatorCredential("bob.reviewer", "secret-b"),
                ],
                n8n_api_key="key",
                comfyui_approval_evidence=valid_comfyui_approval(client.now),
                client=client,
            )

    def test_technical_comfyui_result_never_bypasses_named_visual_and_license_approvals(self):
        client = FakeClient()
        missing = {"schema_version": "1.0", "qualification_binding": {}}
        with self.assertRaisesRegex(AssertionError, "not bound to the live qualified output"):
            release_acceptance.run_acceptance(
                console_url="https://marketing.example:18117",
                n8n_url="https://marketing.example:15678",
                operators=[
                    release_acceptance.OperatorCredential("alice.reviewer", "secret-a"),
                    release_acceptance.OperatorCredential("bob.reviewer", "secret-b"),
                ],
                n8n_api_key="key",
                comfyui_approval_evidence=missing,
                client=client,
            )

        tampered = deepcopy(valid_comfyui_approval(client.now))
        tampered["qualification_binding"]["output_sha256"] = "e" * 64
        with self.assertRaisesRegex(AssertionError, "not bound to the live qualified output"):
            release_acceptance.run_acceptance(
                console_url="https://marketing.example:18117",
                n8n_url="https://marketing.example:15678",
                operators=[
                    release_acceptance.OperatorCredential("alice.reviewer", "secret-a"),
                    release_acceptance.OperatorCredential("bob.reviewer", "secret-b"),
                ],
                n8n_api_key="key",
                comfyui_approval_evidence=tampered,
                client=client,
            )

    def test_n8n_gate_rejects_extra_or_drifted_workflows_and_unverified_execution(self):
        def run(client):
            return release_acceptance.run_acceptance(
                console_url="https://marketing.example:18117",
                n8n_url="https://marketing.example:15678",
                operators=[
                    release_acceptance.OperatorCredential("alice.reviewer", "secret-a"),
                    release_acceptance.OperatorCredential("bob.reviewer", "secret-b"),
                ],
                n8n_api_key="key",
                comfyui_approval_evidence=valid_comfyui_approval(client.now),
                client=client,
            )

        extra = FakeClient()
        extra.extra_workflow = {"id": "unapproved-workflow", "active": False}
        with self.assertRaisesRegex(AssertionError, "exactly match the ten-definition"):
            run(extra)

        drifted = FakeClient()
        drifted.workflow_mutator = lambda workflow_id, payload: (
            payload["settings"].update({"saveDataSuccessExecution": "none"})
            if workflow_id == "WMCTrendResearch01"
            else None
        )
        with self.assertRaisesRegex(AssertionError, "definition, settings, or credential references drifted"):
            run(drifted)

        credential_drift = FakeClient()

        def change_credential(workflow_id, payload):
            if workflow_id != "lYfpV4r4oeEzPtuO":
                return
            for node in payload["nodes"]:
                references = node.get("credentials", {})
                if references:
                    next(iter(references.values()))["name"] = "Unapproved Credential"
                    return

        credential_drift.workflow_mutator = change_credential
        with self.assertRaisesRegex(AssertionError, "definition, settings, or credential references drifted"):
            run(credential_drift)

        wrong_execution = FakeClient()
        wrong_execution.execution_mutator = lambda payload: payload.update(
            {"workflowId": "GqGVw06F64o7rvjI"}
        )
        with self.assertRaisesRegex(AssertionError, "not from the required verified-trend workflow"):
            run(wrong_execution)

    def test_current_head_full_content_is_recomputed_even_when_stored_summary_claims_green(self):
        client = FakeClient()

        def tamper(content_id, state):
            if content_id == "k1-current-draft":
                state["brief"]["public_copy"] = "API_KEY=secret"
                self.assertTrue(state["brief"]["quality_evaluation"]["release_ready"])

        client.state_mutator = tamper
        with self.assertRaisesRegex(AssertionError, "current full content fails the deterministic release rubric"):
            release_acceptance.run_acceptance(
                console_url="https://marketing.example:18117",
                n8n_url="https://marketing.example:15678",
                operators=[
                    release_acceptance.OperatorCredential("alice.reviewer", "secret-a"),
                    release_acceptance.OperatorCredential("bob.reviewer", "secret-b"),
                ],
                n8n_api_key="key",
                comfyui_approval_evidence=valid_comfyui_approval(client.now),
                client=client,
            )
    def test_operator_credentials_are_file_only_named_and_private_on_posix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            credential = Path(temp_dir) / "operator"
            credential.write_text("alice.reviewer:correct horse battery staple\n", encoding="utf-8")
            if release_acceptance.os.name == "posix":
                credential.chmod(0o600)
            loaded = release_acceptance.load_operator(str(credential))
            self.assertEqual(loaded.actor, "alice.reviewer")
            self.assertNotIn("correct horse", repr(loaded))

            credential.write_text("admin:password\n", encoding="utf-8")
            if release_acceptance.os.name == "posix":
                credential.chmod(0o600)
            with self.assertRaisesRegex(RuntimeError, "named person"):
                release_acceptance.load_operator(str(credential))

    def test_https_urls_cannot_embed_credentials_or_disable_tls(self):
        with self.assertRaisesRegex(RuntimeError, "https URL"):
            release_acceptance._https_base("http://marketing.example:18117", label="console URL")
        with self.assertRaisesRegex(RuntimeError, "embedded credentials"):
            release_acceptance._https_base(
                "https://alice:password@marketing.example:18117",
                label="console URL",
            )


if __name__ == "__main__":
    unittest.main()

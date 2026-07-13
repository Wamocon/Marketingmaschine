import json
import sys
import unittest
from pathlib import Path

import yaml


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class N8nWorkflowSecurityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.workflow_root = self.root / "deploy" / "n8n" / "workflows"

    def _http_nodes(self):
        for path in sorted(self.workflow_root.glob("*.json")):
            workflow = json.loads(path.read_text(encoding="utf-8"))
            for node in workflow.get("nodes", []):
                if node.get("type") == "n8n-nodes-base.httpRequest":
                    yield path.name, node

    def test_versioned_catalog_counts_exclude_retired_human_approval(self):
        workflows = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(self.workflow_root.glob("*.json"))
        ]
        http_nodes = [
            node
            for workflow in workflows
            for node in workflow.get("nodes", [])
            if node.get("type") == "n8n-nodes-base.httpRequest"
            and "wmc-marketing-agent:8080"
            in str(node.get("parameters", {}).get("url", ""))
        ]
        webhook_nodes = [
            node
            for workflow in workflows
            for node in workflow.get("nodes", [])
            if node.get("type") == "n8n-nodes-base.webhook"
        ]
        self.assertEqual(len(workflows), 10)
        self.assertEqual(
            sum(workflow.get("active") is True for workflow in workflows), 8
        )
        self.assertEqual(len(http_nodes), 10)
        self.assertEqual(len(webhook_nodes), 2)

    @staticmethod
    def _headers(node):
        parameters = node.get("parameters", {})
        raw_headers = (parameters.get("headerParameters") or {}).get("parameters", [])
        return {
            str(item.get("name", "")).casefold(): str(item.get("value", ""))
            for item in raw_headers
            if isinstance(item, dict)
        }

    def test_all_state_changing_agent_calls_use_named_encrypted_header_auth(self):
        mutating_nodes = []
        for filename, node in self._http_nodes():
            parameters = node.get("parameters", {})
            method = str(parameters.get("method", "GET")).upper()
            url = str(parameters.get("url", ""))
            if "wmc-marketing-agent:8080" not in url or method not in {
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
            }:
                continue
            mutating_nodes.append((filename, node.get("name", "")))
            self.assertEqual(parameters.get("authentication"), "genericCredentialType")
            self.assertEqual(parameters.get("genericAuthType"), "httpHeaderAuth")
            credential = (node.get("credentials") or {}).get("httpHeaderAuth") or {}
            self.assertEqual(credential, {"name": "WAMOCON Agent Access Token"})
            self.assertNotIn("id", credential)

        self.assertEqual(
            {filename for filename, _ in mutating_nodes},
            {
                "lead-retention-daily.json",
                "manual-content-intake.json",
                "trend-research-intake.json",
                "weekly-planning.json",
            },
        )

    def test_inbound_mutating_webhooks_require_named_header_auth(self):
        protected = []
        for path in sorted(self.workflow_root.glob("*.json")):
            workflow = json.loads(path.read_text(encoding="utf-8"))
            for node in workflow.get("nodes", []):
                if node.get("type") != "n8n-nodes-base.webhook":
                    continue
                protected.append((path.name, node.get("name", "")))
                self.assertEqual(
                    node.get("parameters", {}).get("authentication"), "headerAuth"
                )
                credential = (node.get("credentials") or {}).get("httpHeaderAuth") or {}
                self.assertEqual(credential, {"name": "WAMOCON Inbound Webhook Token"})
                self.assertNotIn("id", credential)

        self.assertEqual(
            {filename for filename, _ in protected},
            {"manual-content-intake.json", "trend-research-intake.json"},
        )

    def test_shared_credential_approval_webhook_is_permanently_retired(self):
        workflow = json.loads(
            (self.workflow_root / "approval-webhook.json").read_text(encoding="utf-8")
        )
        self.assertFalse(workflow["active"])
        self.assertEqual(workflow["nodes"], [])
        self.assertEqual(workflow["connections"], {})
        self.assertTrue(workflow["meta"]["must_not_activate"])
        self.assertIn("cannot prove which person", workflow["meta"]["retired_reason"])
        self.assertNotIn("/workflows/approve-content", json.dumps(workflow))

    def test_read_only_agent_calls_use_access_credentials_without_changing_method(self):
        read_only_nodes = []
        for filename, node in self._http_nodes():
            parameters = node.get("parameters", {})
            method = str(parameters.get("method", "GET")).upper()
            url = str(parameters.get("url", ""))
            if "wmc-marketing-agent:8080" not in url or method != "GET":
                continue
            read_only_nodes.append((filename, node.get("name", "")))
            self.assertNotIn("x-wamocon-mutation-token", self._headers(node))
            self.assertEqual(parameters.get("authentication"), "genericCredentialType")
            self.assertEqual(parameters.get("genericAuthType"), "httpHeaderAuth")
            credential = (node.get("credentials") or {}).get("httpHeaderAuth") or {}
            self.assertEqual(credential, {"name": "WAMOCON Agent Access Token"})
            self.assertNotIn("id", credential)

        self.assertGreaterEqual(len(read_only_nodes), 5)

    def test_trend_webhook_has_no_automatic_mutating_retry(self):
        workflow = json.loads(
            (self.workflow_root / "trend-research-intake.json").read_text(
                encoding="utf-8"
            )
        )
        node = next(
            item for item in workflow["nodes"] if item.get("id") == "run-research"
        )

        self.assertIs(node.get("retryOnFail"), False)
        self.assertEqual(node.get("maxTries"), 1)
        self.assertNotIn("waitBetweenTries", node)
        self.assertIn("request_id: $execution.id", node["parameters"]["jsonBody"])

    def test_manual_intake_supplies_the_fail_closed_content_mode_contract(self):
        workflow = json.loads(
            (self.workflow_root / "manual-content-intake.json").read_text(
                encoding="utf-8"
            )
        )
        metadata = workflow["meta"]
        self.assertIs(metadata["inbound_content_mode_required"], False)
        self.assertIs(metadata["content_mode_supplied_to_api"], True)
        self.assertEqual(metadata["missing_content_mode_default"], "evergreen")
        self.assertEqual(
            metadata["accepted_content_modes"], ["evergreen", "current_trend"]
        )
        self.assertEqual(
            metadata["trend_evidence_authority"],
            "stored_marketing_agent_trend_run",
        )
        self.assertIs(metadata["current_trend_evidence_revalidated_by_api"], True)
        node = next(
            item for item in workflow["nodes"] if item.get("id") == "create-content"
        )
        self.assertIn("omitted mode becomes evergreen", node["notes"])
        self.assertIn("API reconstructs and revalidates all evidence", node["notes"])
        body = node["parameters"]["jsonBody"]
        self.assertIn("...$json.body", body)
        self.assertIn("String($json.body.content_mode).trim().toLowerCase()", body)
        self.assertIn(": 'evergreen'", body)
        self.assertIn("content_mode:", body)

    def test_all_due_discovery_workflows_run_daily_and_stay_read_only(self):
        expected = {
            "analytics-72h.json": "0 7 * * *",
            "analytics-7d.json": "15 7 * * *",
            "analytics-14d.json": "30 7 * * *",
            "analytics-30d.json": "45 7 * * *",
        }
        for filename, cron in expected.items():
            workflow = json.loads(
                (self.workflow_root / filename).read_text(encoding="utf-8")
            )
            self.assertIn("Due Discovery (Read Only)", workflow["name"])
            schedule = next(
                node
                for node in workflow["nodes"]
                if node.get("type") == "n8n-nodes-base.scheduleTrigger"
            )
            interval = schedule["parameters"]["rule"]["interval"]
            self.assertEqual(
                interval, [{"field": "cronExpression", "expression": cron}]
            )
            request = next(
                node
                for node in workflow["nodes"]
                if node.get("type") == "n8n-nodes-base.httpRequest"
            )
            self.assertEqual(
                str(request.get("parameters", {}).get("method", "GET")).upper(), "GET"
            )
            credential = (request.get("credentials") or {}).get("httpHeaderAuth") or {}
            self.assertEqual(credential, {"name": "WAMOCON Agent Access Token"})

    def test_staged_lead_retention_is_daily_local_and_deterministically_idempotent(
        self,
    ):
        workflow = json.loads(
            (self.workflow_root / "lead-retention-daily.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIs(workflow["active"], False)
        self.assertIn("(Staged)", workflow["name"])

        schedule = next(
            node
            for node in workflow["nodes"]
            if node.get("type") == "n8n-nodes-base.scheduleTrigger"
        )
        self.assertEqual(
            schedule["parameters"]["rule"]["interval"],
            [{"field": "cronExpression", "expression": "20 2 * * *"}],
        )

        requests = {
            str(node.get("parameters", {}).get("method", "GET")).upper(): node
            for node in workflow["nodes"]
            if node.get("type") == "n8n-nodes-base.httpRequest"
        }
        self.assertEqual(set(requests), {"GET", "POST"})
        self.assertEqual(
            requests["GET"]["parameters"]["url"],
            "http://wmc-marketing-agent:8080/workflows/leads/retention-due",
        )
        self.assertEqual(
            requests["POST"]["parameters"]["url"],
            "http://wmc-marketing-agent:8080/workflows/lead-lifecycle",
        )
        for request in requests.values():
            self.assertEqual(
                request["parameters"]["authentication"], "genericCredentialType"
            )
            self.assertEqual(request["parameters"]["genericAuthType"], "httpHeaderAuth")
            self.assertEqual(
                request["credentials"]["httpHeaderAuth"],
                {"name": "WAMOCON Agent Access Token"},
            )

        split = next(
            node
            for node in workflow["nodes"]
            if node.get("type") == "n8n-nodes-base.splitOut"
        )
        self.assertEqual(split["parameters"]["fieldToSplitOut"], "items")
        body = requests["POST"]["parameters"]["jsonBody"]
        self.assertIn("lead_id: $json.lead_id", body)
        self.assertIn("action: 'expire_retention'", body)
        self.assertIn("operator: 'automation:n8n-retention'", body)
        self.assertIn("reason_code: 'retention_expired'", body)
        self.assertNotIn("reason:", body)
        self.assertIn("occurred_at: $now.toUTC().toISO()", body)
        self.assertIn("effective_expiry_at: $json.effective_expiry_at", body)
        self.assertNotIn("occurred_at: $json.effective_expiry_at", body)
        # occurred_at is intentionally the actual execution time; API
        # idempotency is bound to the separate stable effective_expiry_at.
        for nondeterministic_value in ("$execution", "Date.now", "randomUUID"):
            self.assertNotIn(nondeterministic_value, body)

        encoded = json.dumps(workflow).lower()
        self.assertNotIn('"method": "delete"', encoded)
        self.assertNotIn("wmc-twenty", encoded)
        self.assertNotIn("wmc-mautic", encoded)
        self.assertNotIn("external crm", encoded)

    def test_workflow_json_contains_no_literal_or_environment_secret_expression(self):
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(self.workflow_root.glob("*.json"))
        )
        self.assertNotIn("$env", combined)
        self.assertNotIn("X-WAMOCON-Mutation-Token", combined)
        self.assertNotIn('"id": "WAMOCON Agent Access Token"', combined)

    def test_n8n_runtime_templates_require_protected_canonical_urls_only(self):
        for relative_path in (
            "deploy/n8n/core-stack.release1-postgres.yml",
            "deploy/n8n/core-stack.release2-queue.yml",
        ):
            text = (self.root / relative_path).read_text(encoding="utf-8")
            self.assertIn(
                "N8N_WEBHOOK_URL:?Set N8N_WEBHOOK_URL to the protected canonical webhook URL",
                text,
                relative_path,
            )
            self.assertNotIn("MARKETING_MACHINE_MUTATION_TOKEN", text)
            self.assertIn('N8N_BLOCK_ENV_ACCESS_IN_NODE: "true"', text)
            self.assertIn('N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES: "true"', text)
            self.assertIn(
                "N8N_RESTRICT_FILE_ACCESS_TO: /data/knowledge;/data/files", text
            )
            self.assertIn("n8n-nodes-base.code", text)
            self.assertIn("n8n-nodes-base.executeCommand", text)
            self.assertIn("n8n-nodes-base.readWriteFile", text)
            self.assertIn('N8N_SSRF_PROTECTION_ENABLED: "true"', text)
            self.assertIn("N8N_SSRF_ALLOWED_HOSTNAMES: wmc-marketing-agent", text)
            self.assertNotIn("N8N_SSRF_ALLOWED_IP_RANGES", text)
            self.assertIn("EXECUTIONS_DATA_SAVE_ON_SUCCESS: none", text)
            self.assertIn('EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS: "false"', text)
            self.assertIn('N8N_VERSION_NOTIFICATIONS_ENABLED: "true"', text)
            self.assertIn("core-n8n-postgres-app-data", text)
            self.assertNotIn("lokal-ai-stack_n8n-data", text)

        migration_env = (
            self.root / "deploy" / "n8n" / ".env.migration.example"
        ).read_text(encoding="utf-8")
        self.assertIn("N8N_WEBHOOK_URL=\n", migration_env)
        self.assertIn("N8N_EDITOR_BASE_URL=\n", migration_env)
        self.assertNotIn("MARKETING_MACHINE_MUTATION_TOKEN", migration_env)
        self.assertNotIn("example.invalid", migration_env)

    def test_queue_redis_never_exposes_password_in_process_arguments(self):
        queue_compose = (
            self.root / "deploy" / "n8n" / "core-stack.release2-queue.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("/tmp/redis.conf", queue_compose)
        self.assertIn("n8n_redis_password", queue_compose)
        self.assertNotIn('--requirepass "$$(cat', queue_compose)
        self.assertIn("QUEUE_BULL_REDIS_PASSWORD_FILE", queue_compose)
        self.assertIn("maxmemory 384mb", queue_compose)
        self.assertIn("maxmemory-policy noeviction", queue_compose)

    def test_queue_worker_has_a_real_readiness_healthcheck(self):
        payload = yaml.safe_load(
            (self.root / "deploy" / "n8n" / "core-stack.release2-queue.yml").read_text(
                encoding="utf-8"
            )
        )
        worker = payload["services"]["core-n8n-worker"]
        healthcheck = worker["healthcheck"]
        self.assertIn("/healthz/readiness", healthcheck["test"][1])
        self.assertEqual(healthcheck["interval"], "15s")

    def test_only_source_evidence_workflow_retains_success_payloads(self):
        retained = []
        for path in sorted(self.workflow_root.glob("*.json")):
            workflow = json.loads(path.read_text(encoding="utf-8"))
            if workflow.get("settings", {}).get("saveDataSuccessExecution") == "all":
                retained.append(path.name)
        self.assertEqual(retained, ["trend-research-intake.json"])


if __name__ == "__main__":
    unittest.main()

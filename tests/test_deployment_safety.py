import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class DeploymentSafetyTests(unittest.TestCase):
    def test_retired_core_compose_can_never_start_legacy_services(self):
        payload = yaml.safe_load(
            (ROOT / "deploy" / "docker-compose.core.yml").read_text(encoding="utf-8")
        )

        self.assertEqual(payload.get("services"), {})

    def test_production_documentation_does_not_direct_operators_to_legacy_compose(self):
        references = []
        for path in (ROOT / "docs").glob("*.md"):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                normalized = line.casefold()
                if "docker-compose.core.yml" in normalized and "do not deploy" not in normalized:
                    references.append(f"{path.name}: {line.strip()}")

        # The deprecation page names the file in an explicit warning on the
        # preceding line; no run command or maintained path may reference it.
        self.assertFalse(
            [item for item in references if "legacy development" not in item],
            references,
        )

    def test_marketing_edge_requires_tls_named_accounts_and_server_side_headers(self):
        nginx = (ROOT / "deploy" / "network-access" / "nginx.conf").read_text(
            encoding="utf-8"
        )
        compose = (
            ROOT / "deploy" / "docker-compose.network-access.yml"
        ).read_text(encoding="utf-8")
        entrypoint = (
            ROOT / "deploy" / "network-access" / "entrypoint.sh"
        ).read_text(encoding="utf-8")
        agent_env = (ROOT / "deploy" / "marketing-agent.env.example").read_text(
            encoding="utf-8"
        )

        self.assertIn("listen 8117 ssl;", nginx)
        for port in (5678, 4007, 4019, 4020, 8188, 3030):
            self.assertIn(f"listen {port} ssl;", nginx)
        self.assertIn("auth_basic_user_file /run/secrets/marketing_operator_htpasswd", nginx)
        self.assertIn("proxy_set_header X-WAMOCON-Actor $remote_user", nginx)
        self.assertIn("default-src 'self'", nginx)
        self.assertIn("script-src 'self'", nginx)
        self.assertIn("connect-src 'self'", nginx)
        self.assertIn("style-src 'self' 'unsafe-inline'", nginx)
        self.assertIn("frame-ancestors 'none'", nginx)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", nginx)
        self.assertIn("add_header Permissions-Policy", nginx)
        self.assertIn('add_header Cross-Origin-Opener-Policy "same-origin" always;', nginx)
        self.assertIn('add_header Cross-Origin-Resource-Policy "same-origin" always;', nginx)
        self.assertIn("server_tokens off;", nginx)
        self.assertIn("ssl_session_tickets off;", nginx)
        self.assertIn('add_header X-Frame-Options "DENY" always;', nginx)
        self.assertIn("proxy_set_header X-Forwarded-For $remote_addr;", nginx)
        self.assertNotIn("$proxy_add_x_forwarded_for", nginx)
        self.assertIn('proxy_set_header X-Forwarded-Port "";', nginx)
        self.assertNotIn("X-Forwarded-Port $server_port", nginx)
        self.assertIn("proxy_set_header Host wmc-marketing-agent;", nginx)
        self.assertIn("if ($wamocon_allowed_host = 0) { return 421; }", nginx)
        console_server = nginx.split("listen 8117 ssl;", 1)[1].split(
            "listen 5678 ssl;", 1
        )[0]
        self.assertIn(
            'add_header Strict-Transport-Security "max-age=31536000" always;',
            console_server,
        )
        self.assertIn("client_max_body_size 1m;", console_server)
        n8n_server = nginx.split("listen 5678 ssl;", 1)[1].split("listen 4007 ssl;", 1)[0]
        self.assertIn("set $upstream http://core-n8n:5678;", n8n_server)
        self.assertIn("proxy_pass $upstream;", n8n_server)
        self.assertNotIn("proxy_pass http://core-n8n:5678;", n8n_server)
        grafana_server = nginx.split("listen 3030 ssl;", 1)[1]
        self.assertIn("set $upstream http://shared-grafana:3000;", grafana_server)
        self.assertNotIn("proxy_pass http://shared-grafana:3000;", grafana_server)
        self.assertIn("marketing_operator_htpasswd", compose)
        self.assertIn("marketing_tls_certificate", compose)
        self.assertIn("marketing_tls_private_key", compose)
        self.assertIn("MARKETING_MACHINE_ALLOWED_HOSTS:?Set exact", compose)
        self.assertIn("MARKETING_MACHINE_ALLOWED_CLIENT_CIDRS:?Set approved", compose)
        self.assertIn("MARKETING_COMFYUI_UPSTREAM:?Set the approved", compose)
        self.assertIn("at least two distinct named marketing operator accounts", entrypoint)
        self.assertIn("map $host $wamocon_allowed_host", entrypoint)
        self.assertIn("MARKETING_MACHINE_ALLOWED_HOSTS must list", entrypoint)
        self.assertIn("MARKETING_MACHINE_ALLOWED_CLIENT_CIDRS must list", entrypoint)
        self.assertIn("01-wamocon-client-access.conf", entrypoint)
        self.assertIn("MARKETING_COMFYUI_UPSTREAM must be an exact", entrypoint)
        self.assertIn("MARKETING_MACHINE_BUSINESS_TIMEZONE=Europe/Berlin", agent_env)
        self.assertIn("MARKETING_MACHINE_ALLOWED_HOSTS=", agent_env)
        self.assertIn("MARKETING_MACHINE_ALLOWED_CLIENT_CIDRS=", agent_env)
        self.assertIn("MARKETING_COMFYUI_UPSTREAM=", agent_env)
        self.assertIn("nginx -t", entrypoint)

    def test_staged_n8n_releases_require_secure_session_cookies(self):
        for filename in (
            "core-stack.release1-postgres.yml",
            "core-stack.release2-queue.yml",
        ):
            compose = (ROOT / "deploy" / "n8n" / filename).read_text(encoding="utf-8")
            self.assertIn(
                "N8N_HOST: ${N8N_CANONICAL_HOST:?Set N8N_CANONICAL_HOST to the protected canonical hostname}",
                compose,
                filename,
            )
            self.assertIn("N8N_LISTEN_ADDRESS: 0.0.0.0", compose, filename)
            self.assertNotIn("N8N_HOST: 0.0.0.0", compose, filename)
            self.assertIn('N8N_SECURE_COOKIE: "true"', compose, filename)
            self.assertIn('N8N_PROXY_HOPS: "1"', compose, filename)
            self.assertNotIn('N8N_SECURE_COOKIE: "false"', compose, filename)

    def test_production_agent_uses_only_the_mutation_token_docker_secret(self):
        compose = (ROOT / "deploy" / "docker-compose.existing-stack.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "MARKETING_MACHINE_MUTATION_TOKEN_FILE: /run/secrets/marketing_mutation_token",
            compose,
        )
        self.assertNotIn("MARKETING_MACHINE_MUTATION_TOKEN:", compose)

    def test_record_creating_smoke_tools_refuse_known_production_ports(self):
        smoke = (ROOT / "scripts" / "smoke_api.py").read_text(encoding="utf-8")
        mock = (ROOT / "scripts" / "mock_pipeline_test.py").read_text(encoding="utf-8")
        browser = (
            ROOT / "scripts" / "trend_studio_user_flow_smoke.js"
        ).read_text(encoding="utf-8")

        self.assertIn("--allow-mutations", smoke)
        self.assertIn("{8117, 18117}", smoke)
        self.assertIn("--isolated-candidate", mock)
        self.assertIn("{8117, 18117}", mock)
        self.assertIn("MARKETING_MACHINE_ISOLATED_CANDIDATE", browser)
        self.assertIn('["8117", "18117"]', browser)
        self.assertIn('instance.get("mode") == "isolated-candidate"', smoke)
        self.assertIn('instance.get("mode") == "isolated-candidate"', mock)
        self.assertIn('health?.instance?.mode, "isolated-candidate"', browser)
        self.assertIn("mutating n8n smoke is retired", smoke)
        self.assertIn("mutating n8n smoke is retired", mock)

    def test_candidate_compose_is_disposable_isolated_and_cannot_write_externally(self):
        candidate = yaml.safe_load(
            (ROOT / "deploy" / "docker-compose.candidate.yml").read_text(encoding="utf-8")
        )
        service = candidate["services"]["wmc-marketing-candidate"]
        self.assertEqual(candidate["name"], "wamocon-marketing-candidate")
        environment = service["environment"]
        self.assertEqual(environment["MARKETING_MACHINE_INSTANCE_MODE"], "isolated-candidate")
        self.assertEqual(environment["MARKETING_MACHINE_DISPOSABLE_DATA"], "true")
        self.assertEqual(environment["MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES"], "false")
        self.assertEqual(environment["MARKETING_MACHINE_ACTOR_AUTH_MODE"], "required")
        self.assertEqual(service["volumes"], ["candidate_runtime:/data"])
        self.assertEqual(
            candidate["volumes"]["candidate_runtime"]["name"],
            "wamocon_marketing_candidate_validation_data",
        )
        self.assertIn("candidate_mutation_token", service["secrets"])
        self.assertIn("candidate_edge_attestation", service["secrets"])

    def test_queue_redis_healthcheck_keeps_password_out_of_process_arguments(self):
        compose = (ROOT / "deploy" / "n8n" / "core-stack.release2-queue.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("REDISCLI_AUTH=", compose)
        self.assertNotIn('redis-cli -a', compose)

    def test_growth_datastores_are_isolated_from_edge_and_other_profiles(self):
        growth = yaml.safe_load(
            (ROOT / "deploy" / "docker-compose.growth-tools.yml").read_text(
                encoding="utf-8"
            )
        )
        edge = yaml.safe_load(
            (ROOT / "deploy" / "docker-compose.network-access.yml").read_text(
                encoding="utf-8"
            )
        )
        services = growth["services"]
        expected = {
            "wmc-postiz": {"core-net", "postiz-data-net"},
            "wmc-postiz-postgres": {"postiz-data-net"},
            "wmc-postiz-redis": {"postiz-data-net"},
            "wmc-twenty-server": {"core-net", "twenty-data-net"},
            "wmc-twenty-db": {"twenty-data-net"},
            "wmc-twenty-redis": {"twenty-data-net"},
            "wmc-mautic-web": {"core-net", "mautic-data-net"},
            "wmc-mautic-db": {"mautic-data-net"},
        }
        for service, networks in expected.items():
            self.assertEqual(set(services[service]["networks"]), networks, service)
        for name in ("postiz-data-net", "postiz-temporal-net", "twenty-data-net", "mautic-data-net"):
            self.assertTrue(growth["networks"][name]["internal"], name)
        self.assertEqual(
            set(edge["services"]["wmc-marketing-access"]["networks"]),
            {"core-net", "shared-network"},
        )
        self.assertNotIn("growth-net", edge["networks"])

    def test_generated_secret_bearing_configs_live_only_on_tmpfs(self):
        agent = yaml.safe_load(
            (ROOT / "deploy" / "docker-compose.existing-stack.yml").read_text(
                encoding="utf-8"
            )
        )["services"]["wmc-marketing-agent"]
        candidate = yaml.safe_load(
            (ROOT / "deploy" / "docker-compose.candidate.yml").read_text(
                encoding="utf-8"
            )
        )["services"]["wmc-marketing-candidate"]
        edge = yaml.safe_load(
            (ROOT / "deploy" / "docker-compose.network-access.yml").read_text(
                encoding="utf-8"
            )
        )["services"]["wmc-marketing-access"]
        queue = yaml.safe_load(
            (ROOT / "deploy" / "n8n" / "core-stack.release2-queue.yml").read_text(
                encoding="utf-8"
            )
        )["services"]["core-n8n-redis"]
        optional_cache = yaml.safe_load(
            (ROOT / "deploy" / "observability" / "docker-compose.optional-cache.yml").read_text(
                encoding="utf-8"
            )
        )["services"]["shared-redis"]

        for service in (agent, candidate):
            self.assertTrue(
                any(item.startswith("/run/wamocon-agent-secrets:") for item in service["tmpfs"])
            )
        self.assertTrue(any(item.startswith("/etc/nginx/conf.d:") for item in edge["tmpfs"]))
        self.assertTrue(any(item.startswith("/tmp:") for item in queue["tmpfs"]))
        self.assertTrue(any(item.startswith("/tmp:") for item in optional_cache["tmpfs"]))


if __name__ == "__main__":
    unittest.main()

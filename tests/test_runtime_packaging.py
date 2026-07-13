import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimePackagingTests(unittest.TestCase):
    def test_production_dependencies_match_imported_runtime_surface(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        production = set(pyproject["project"]["optional-dependencies"]["prod"])

        self.assertEqual(
            production,
            {
                "fastapi==0.139.0",
                "uvicorn[standard]==0.51.0",
                "langgraph==1.2.9",
            },
        )

    def test_runtime_lock_contains_exact_core_versions_only(self):
        lock = (ROOT / "requirements" / "runtime.lock").read_text(encoding="utf-8").lower()

        for requirement in (
            "fastapi==0.139.0",
            "uvicorn==0.51.0",
            "langgraph==1.2.9",
            "pydantic==2.13.4",
        ):
            self.assertRegex(lock, rf"(?m)^{re.escape(requirement)}(?:\s|$)")

        for unused_package in ("langchain==", "langgraph-checkpoint-postgres==", "openai==", "psycopg=="):
            self.assertNotIn(unused_package, lock)

    def test_container_build_uses_locked_dependencies_and_pinned_base(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("python:3.12.13-alpine3.24@sha256:", dockerfile)
        self.assertEqual(dockerfile.count("FROM ${PYTHON_IMAGE}"), 2)
        self.assertIn("--require-hashes", dockerfile)
        self.assertIn("--no-compile", dockerfile)
        self.assertIn("requirements/runtime.lock", dockerfile)
        self.assertIn("/healthz", dockerfile)
        self.assertIn("ENTRYPOINT", dockerfile)
        self.assertIn('"--no-proxy-headers"', dockerfile)
        self.assertNotIn('"--forwarded-allow-ips", "*"', dockerfile)
        self.assertIn("adduser -S -D -H -u 10001", dockerfile)
        self.assertIn("su-exec=0.3-r0", dockerfile)
        entrypoint = (ROOT / "deploy" / "marketing-agent-entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("setpriv", entrypoint)
        self.assertIn("--no-new-privs", entrypoint)
        self.assertIn("su-exec marketing:marketing", entrypoint)
        self.assertIn('chown -R marketing:marketing "$data_dir"', entrypoint)
        self.assertIn('find "$data_dir" -type d -exec chmod 0700', entrypoint)
        self.assertIn('find "$data_dir" -type f -exec chmod 0600', entrypoint)
        self.assertIn("/run/wamocon-agent-secrets", entrypoint)
        self.assertIn('chmod 0400 "$target_path"', entrypoint)
        self.assertIn("MARKETING_MACHINE_MUTATION_TOKEN_FILE", entrypoint)
        self.assertIn("MARKETING_MACHINE_EDGE_ATTESTATION_FILE", entrypoint)
        self.assertNotIn("$data_dir/mutation_token", entrypoint)
        self.assertNotIn('pip install --no-cache-dir -e ".[prod]"', dockerfile)

    def test_build_context_excludes_private_runtime_material(self):
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

        for private_path in (
            "deploy/secrets/",
            "deploy/n8n/secrets/",
            "deploy/**/secrets/",
            "deploy/*.generated.env",
            "config/integrations.local.env",
            "runtime-data/",
        ):
            self.assertIn(private_path, dockerignore)

    def test_linux_entrypoints_keep_lf_line_endings_on_windows_checkouts(self):
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")

        self.assertRegex(attributes, r"(?m)^\*\.sh text eol=lf$")
        self.assertRegex(attributes, r"(?m)^Dockerfile text eol=lf$")
        for entrypoint in (
            ROOT / "deploy" / "marketing-agent-entrypoint.sh",
            ROOT / "deploy" / "network-access" / "entrypoint.sh",
        ):
            self.assertTrue(entrypoint.read_bytes().startswith(b"#!/"))
            self.assertNotIn(b"\r\n", entrypoint.read_bytes())

    def test_candidate_qa_tunnels_are_loopback_only_and_fail_closed(self):
        tunnel_script = (ROOT / "scripts" / "start_candidate_qa_tunnels.ps1").read_text(
            encoding="utf-8"
        )

        for port in (18090, 18114, 18189):
            self.assertIn(f"http://127.0.0.1:{port}", tunnel_script)
        self.assertIn('"ExitOnForwardFailure=yes"', tunnel_script)
        self.assertIn('"ServerAliveInterval=30"', tunnel_script)
        self.assertIn("-WindowStyle Hidden", tunnel_script)
        self.assertNotIn("0.0.0.0", tunnel_script)

    def test_production_compose_has_a_retained_image_rollback_selector(self):
        compose = (ROOT / "deploy" / "docker-compose.existing-stack.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "image: ${MARKETING_MACHINE_IMAGE:-wamocon-marketing-machine:production}",
            compose,
        )
        self.assertIn("no-new-privileges:true", compose)


if __name__ == "__main__":
    unittest.main()

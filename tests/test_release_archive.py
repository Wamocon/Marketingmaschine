import hashlib
import importlib.util
import json
import os
import sys
import tarfile
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "build_release_archive.py"
SPEC = importlib.util.spec_from_file_location("build_release_archive", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
release_archive = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_archive
SPEC.loader.exec_module(release_archive)


def _write(path: Path, content: str | bytes = "safe\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _minimal_docx(path: Path, *, external_relationship: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    relationship = (
        '<Relationship Id="rId1" Type="example" '
        'Target="https://external.invalid/template" TargetMode="External"/>'
        if external_relationship
        else '<Relationship Id="rId1" Type="example" Target="document.xml"/>'
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as document:
        document.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="content-types"/>',
        )
        document.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><document xmlns="word"><body><p>Handbook</p></body></document>',
        )
        document.writestr(
            "word/_rels/document.xml.rels",
            f'<?xml version="1.0"?><Relationships>{relationship}</Relationships>',
        )


def _minimal_docx_with_safe_hyperlink(
    path: Path,
    target: str = "https://www.example.com/reference",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as document:
        document.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="content-types"/>',
        )
        document.writestr("word/document.xml", "<document><body>Handbook</body></document>")
        document.writestr(
            "word/_rels/document.xml.rels",
            '<Relationships><Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
            f'Target="{target}" TargetMode="External"/></Relationships>',
        )


def _seed_repository(root: Path) -> None:
    _write(root / ".gitattributes", "*.sh text eol=lf\nDockerfile text eol=lf\n")
    _write(root / "README.md", "# Release fixture\n")
    _write(root / "pyproject.toml", "[project]\nname='fixture'\n")
    _write(root / "src" / "marketing_machine" / "app.py", "VALUE = 1\n")
    _write(root / "tests" / "test_app.py", "def test_value():\n    assert 1 == 1\n")
    _write(root / "deploy" / "docker-compose.yml", "services: {}\n")
    _write(root / "deploy" / "entrypoint.sh", "#!/bin/sh\nexec true\n")
    _write(root / "docs" / "guide.md", "# Guide\n")
    _minimal_docx(root / release_archive.SAFE_DOCX_PATH)
    _write(root / "config" / "settings.json", '{"mode":"production"}\n')
    _write(root / "db" / "schema.sql", "SELECT 1;\n")
    _write(root / "requirements" / "runtime.lock", "example==1.0\n")
    _write(root / "scripts" / "helper.py", "print('safe')\n")
    _write(root / "Kampagnen" / "campaign.json", '{"id":"K1"}\n')
    _write(root / "Zielgruppen" / "audience.json", '{"id":"A1"}\n')


class ReleaseArchiveTests(unittest.TestCase):
    def test_ci_builds_and_verifies_the_real_release_archive(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertIn("python scripts/build_release_archive.py", workflow)
        self.assertIn("--root .", workflow)
        self.assertIn("sha256sum --check wamocon-marketing-machine.tar.gz.sha256", workflow)
        self.assertIn("tar -tzf wamocon-marketing-machine.tar.gz", workflow)

    def test_archive_is_reproducible_and_has_normalized_posix_metadata(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            _seed_repository(root)
            output_one = root / "dist" / "release-one.tar.gz"
            output_two = root / "dist" / "release-two.tar.gz"

            result_one = release_archive.build_release(
                root,
                output_one,
                source_date_epoch=42,
            )
            changed_file = root / "src" / "marketing_machine" / "app.py"
            os.utime(changed_file, (time.time() + 3600, time.time() + 3600))
            result_two = release_archive.build_release(
                root,
                output_two,
                source_date_epoch=42,
            )

            self.assertEqual(output_one.read_bytes(), output_two.read_bytes())
            self.assertEqual(result_one.archive_sha256, result_two.archive_sha256)
            expected_hash = hashlib.sha256(output_one.read_bytes()).hexdigest()
            self.assertEqual(result_one.archive_sha256, expected_hash)
            self.assertEqual(
                output_one.with_name(output_one.name + ".sha256").read_text(encoding="ascii"),
                f"{expected_hash}  {output_one.name}\n",
            )

            with tarfile.open(output_one, "r:gz") as archive:
                members = archive.getmembers()
                names = {member.name for member in members}
                self.assertIn(
                    "wamocon-marketing-machine/docs/WAMOCON-Marketing-Handbuch.docx",
                    names,
                )
                self.assertIn("wamocon-marketing-machine/.gitattributes", names)
                self.assertIn("wamocon-marketing-machine/src/marketing_machine/app.py", names)
                self.assertIn("wamocon-marketing-machine/RELEASE-INVENTORY.json", names)
                self.assertTrue(all("\\" not in member.name for member in members))
                self.assertTrue(all(member.mtime == 42 for member in members))
                self.assertTrue(all(member.uid == 0 and member.gid == 0 for member in members))
                self.assertTrue(all(member.uname == "" and member.gname == "" for member in members))
                for member in members:
                    if member.isdir():
                        self.assertEqual(member.mode, 0o755)
                    elif member.name.endswith("entrypoint.sh"):
                        self.assertEqual(member.mode, 0o755)
                    else:
                        self.assertEqual(member.mode, 0o644)
                embedded = json.load(
                    archive.extractfile(
                        "wamocon-marketing-machine/RELEASE-INVENTORY.json"
                    )
                )

            self.assertEqual(embedded["source_date_epoch"], 42)
            embedded_paths = {item["path"] for item in embedded["files"]}
            self.assertIn(".gitattributes", embedded_paths)
            self.assertIn("docs/WAMOCON-Marketing-Handbuch.docx", embedded_paths)
            self.assertIn("Kampagnen/campaign.json", embedded_paths)
            external = json.loads(result_one.inventory.read_text(encoding="utf-8"))
            self.assertEqual(external["archive"]["sha256"], expected_hash)
            self.assertEqual(external["archive"]["size"], output_one.stat().st_size)

    def test_runtime_private_and_generated_artifacts_are_excluded_without_being_read(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            _seed_repository(root)
            generated_token = "sk-" + "A1b2C3d4" * 6
            _write(
                root / "deploy" / "marketing-agent.generated.env",
                f"OPENAI_API_KEY={generated_token}\n",
            )
            _write(root / "deploy" / "secrets" / "operator.key", b"\x00private")
            _write(root / "runtime-data" / "state.json", '{"private":true}\n')
            _write(root / "candidate-runtime-data" / "state.json", "candidate\n")
            _write(root / "qa_output" / "dashboard.pdf", b"%PDF-QA")
            _write(root / "docs" / "qa-report.pdf", b"%PDF-QA")
            _write(root / "docs" / "previous-release.tar.gz", b"archive")
            _write(root / "src" / "marketing_machine" / "state.sqlite3", b"runtime")
            _write(root / "node_modules" / "dependency.js", "module.exports = {}\n")
            _write(root / "src" / "marketing_machine" / "__pycache__" / "app.pyc", b"\x00")
            _write(root / "config" / "integrations.example.env", "OPENAI_API_KEY=\n")
            _write(root / "deploy" / "n8n" / ".env.migration.example", "N8N_KEY=\n")

            output = root / "dist" / "release.tar.gz"
            release_archive.build_release(root, output)
            with tarfile.open(output, "r:gz") as archive:
                names = {member.name for member in archive.getmembers()}

            for forbidden_fragment in (
                "generated.env",
                "/secrets/",
                "runtime-data",
                "qa_output",
                ".pdf",
                ".tar.gz",
                ".sqlite3",
                "node_modules",
                "__pycache__",
            ):
                self.assertFalse(
                    any(forbidden_fragment in name for name in names),
                    forbidden_fragment,
                )
            self.assertIn(
                "wamocon-marketing-machine/config/integrations.example.env",
                names,
            )
            self.assertIn(
                "wamocon-marketing-machine/deploy/n8n/.env.migration.example",
                names,
            )

    def test_rejects_private_env_secret_names_and_key_or_certificate_files(self):
        cases = (
            ("config/.env.production", "VALUE=safe\n", "private environment file"),
            ("docs/client-password.txt", "not-a-password\n", "secret-looking file name"),
            ("deploy/client-cert.pem", "public-looking\n", "private key or certificate file"),
        )
        for relative_path, content, expected_message in cases:
            with self.subTest(relative_path=relative_path):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory) / "repo"
                    _seed_repository(root)
                    _write(root / relative_path, content)
                    with self.assertRaisesRegex(
                        release_archive.ReleaseBuildError,
                        expected_message,
                    ):
                        release_archive.build_release(root, root / "dist" / "release.tar.gz")

    def test_rejects_embedded_high_entropy_credentials(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            _seed_repository(root)
            credential = "sk-" + "Q7w9Er2T" * 5
            _write(root / "config" / "provider.txt", f"OPENAI_API_KEY={credential}\n")

            with self.assertRaisesRegex(
                release_archive.ReleaseBuildError,
                "credential material",
            ):
                release_archive.build_release(root, root / "dist" / "release.tar.gz")
            self.assertFalse((root / "dist" / "release.tar.gz").exists())

    def test_secret_scan_rejects_jwt_secret_and_placeholder_substring_bypasses(self):
        # Build adversarial examples at runtime so the release test suite can
        # verify the archive scanner without itself shipping strings that a
        # downstream credential scanner must (correctly) flag.
        jwt_value = ".".join(
            (
                "eyJhbGciOiJIUzI1NiJ9",
                "eyJzdWIiOiJwcm9kdWN0aW9uLXVzZXIifQ",
                "SflKxwRJSMeK" + "KF2QT4fwpMeJ" + "f36POk6yJV_" + "adQssw5c",
            )
        )
        random_suffix = "".join(
            ("Q7w9Er2T", "y6Ui4Op8", "As3Df5Gh", "1Jk9Lz7X")
        )
        adversarial_values = (
            ("POSTIZ_JWT_SECRET", jwt_value),
            ("DATABASE_PASSWORD", f"mytest-{random_suffix}"),
            (
                "SERVICE_PASSWORD",
                f"replace-with-random-password-{random_suffix}",
            ),
            ("APPLICATION_SECRET", f"contest-{random_suffix}"),
        )
        for key, value in adversarial_values:
            with self.subTest(key=key):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory) / "repo"
                    _seed_repository(root)
                    _write(root / "config" / "provider.env.example", f"{key}={value}\n")

                    with self.assertRaisesRegex(
                        release_archive.ReleaseBuildError,
                        "credential material|high-entropy credential assignment",
                    ):
                        release_archive.build_release(
                            root,
                            root / "dist" / "release.tar.gz",
                        )

    def test_secret_scan_allows_only_exact_declared_placeholders(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            _seed_repository(root)
            _write(
                root / "config" / "provider.env.example",
                "\n".join(
                    (
                        "POSTIZ_JWT_SECRET=replace-with-64-random-characters",
                        "POSTIZ_POSTGRES_PASSWORD=replace-with-random-password",
                        "UPSTREAM_API_KEY=${UPSTREAM_API_KEY}",
                        "SERVICE_TOKEN=<SERVICE_TOKEN>",
                    )
                )
                + "\n",
            )

            result = release_archive.build_release(
                root,
                root / "dist" / "release.tar.gz",
            )

            self.assertTrue(result.archive.is_file())

    def test_allows_runtime_secret_lookup_without_packaging_a_literal_secret(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            _seed_repository(root)
            _write(
                root / "scripts" / "provider.py",
                'import os\napi_key = os.environ.get("PROVIDER_API_KEY", "")\n',
            )

            result = release_archive.build_release(
                root,
                root / "dist" / "release.tar.gz",
            )

            self.assertGreater(result.file_count, 0)

    def test_rejects_symlinks_in_release_roots(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            _seed_repository(root)
            target = root / "src" / "marketing_machine" / "app.py"
            link = root / "src" / "marketing_machine" / "linked.py"
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlinks are unavailable on this host: {exc}")

            with self.assertRaisesRegex(release_archive.ReleaseBuildError, "symlink"):
                release_archive.build_release(root, root / "dist" / "release.tar.gz")

    def test_rejects_word_documents_with_external_relationships(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            _seed_repository(root)
            _minimal_docx(
                root / release_archive.SAFE_DOCX_PATH,
                external_relationship=True,
            )

            with self.assertRaisesRegex(
                release_archive.ReleaseBuildError,
                "unsafe external Word relationship",
            ):
                release_archive.build_release(root, root / "dist" / "release.tar.gz")

    def test_allows_https_hyperlinks_in_the_generated_handbook(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            _seed_repository(root)
            _minimal_docx_with_safe_hyperlink(root / release_archive.SAFE_DOCX_PATH)

            result = release_archive.build_release(root, root / "dist" / "release.tar.gz")

            with tarfile.open(result.archive, "r:gz") as archive:
                names = {member.name for member in archive.getmembers()}
            self.assertIn(
                "wamocon-marketing-machine/docs/WAMOCON-Marketing-Handbuch.docx",
                names,
            )

    def test_allows_local_handbook_links_that_stay_inside_the_release(self):
        for target in (
            "system-validation-2026-07-13.md",
            "../src/marketing_machine/campaign_catalog.py",
            "#operator-workflow",
        ):
            with self.subTest(target=target):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory) / "repo"
                    _seed_repository(root)
                    _minimal_docx_with_safe_hyperlink(
                        root / release_archive.SAFE_DOCX_PATH,
                        target,
                    )

                    result = release_archive.build_release(
                        root,
                        root / "dist" / "release.tar.gz",
                    )

                    self.assertTrue(result.archive.is_file())

    def test_rejects_local_handbook_links_that_escape_or_use_file_paths(self):
        for target in (
            "../../outside.txt",
            "%2fetc/passwd",
            "%43%3a%5cUsers%5coperator%5csecret.txt",
            "file:///etc/passwd",
        ):
            with self.subTest(target=target):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory) / "repo"
                    _seed_repository(root)
                    _minimal_docx_with_safe_hyperlink(
                        root / release_archive.SAFE_DOCX_PATH,
                        target,
                    )

                    with self.assertRaisesRegex(
                        release_archive.ReleaseBuildError,
                        "unsafe external Word relationship",
                    ):
                        release_archive.build_release(
                            root,
                            root / "dist" / "release.tar.gz",
                        )

    def test_rejects_a_symlink_entry_even_when_host_cannot_create_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            source_directory = root / "src"
            source_directory.mkdir(parents=True)

            entry = mock.Mock()
            entry.name = "linked.py"
            entry.path = str(source_directory / entry.name)
            entry.is_symlink.return_value = True

            with mock.patch.object(release_archive.os, "scandir", return_value=[entry]):
                with self.assertRaisesRegex(release_archive.ReleaseBuildError, "symlink"):
                    list(
                        release_archive._walk_directory(
                            source_directory,
                            root,
                            set(),
                        )
                    )

    def test_rejects_a_source_file_that_changes_while_it_is_read(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            _seed_repository(root)
            source = root / "src" / "marketing_machine" / "app.py"
            original_read_bytes = Path.read_bytes

            def changing_read_bytes(path):
                content = original_read_bytes(path)
                if path == source:
                    path.write_bytes(content + b"# changed\n")
                return content

            with mock.patch.object(Path, "read_bytes", changing_read_bytes):
                with self.assertRaisesRegex(
                    release_archive.ReleaseBuildError,
                    "changed while being read",
                ):
                    release_archive.build_release(
                        root,
                        root / "dist" / "release.tar.gz",
                    )

    def test_removes_partial_output_set_when_publication_fails(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            _seed_repository(root)
            output = root / "dist" / "release.tar.gz"
            real_replace = release_archive.os.replace
            replace_count = 0

            def fail_second_replace(source, destination):
                nonlocal replace_count
                replace_count += 1
                if replace_count == 2:
                    raise OSError("simulated sidecar publication failure")
                return real_replace(source, destination)

            with mock.patch.object(
                release_archive.os,
                "replace",
                side_effect=fail_second_replace,
            ):
                with self.assertRaisesRegex(OSError, "simulated sidecar"):
                    release_archive.build_release(root, output)

            self.assertFalse(output.exists())
            self.assertFalse(Path(f"{output}.sha256").exists())
            self.assertFalse(Path(f"{output}.inventory.json").exists())

    def test_refuses_to_replace_any_existing_release_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            _seed_repository(root)
            output = _write(root / "dist" / "release.tar.gz", b"existing")

            with self.assertRaisesRegex(
                release_archive.ReleaseBuildError,
                "release output already exists",
            ):
                release_archive.build_release(root, output)

            self.assertEqual(output.read_bytes(), b"existing")

    def test_rejects_invalid_archive_parameters_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            _seed_repository(root)
            output = root / "dist" / "release.tar.gz"

            for archive_root in (
                "",
                "/absolute",
                "../escape",
                "nested/root",
                "bad\\root",
                "root with spaces",
            ):
                with self.subTest(archive_root=archive_root):
                    with self.assertRaises(release_archive.ReleaseBuildError):
                        release_archive.build_release(root, output, archive_root=archive_root)
            with self.assertRaises(release_archive.ReleaseBuildError):
                release_archive.build_release(root, output, source_date_epoch=-1)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

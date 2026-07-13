from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup_comfyui_candidate.py"
MANIFEST = ROOT / "deploy" / "comfyui" / "flux-schnell-candidate-manifest.json"


def load_setup_module():
    spec = importlib.util.spec_from_file_location("setup_comfyui_candidate", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load candidate setup script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ComfyUiCandidateSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_setup_module()

    def test_release_manifest_passes_read_only_contract_check(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--manifest", str(MANIFEST), "--check-manifest-only"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "manifest_ok")

    def test_model_urls_are_immutable_hugging_face_resolves(self):
        manifest = self.module.load_manifest(MANIFEST)
        for row in manifest["model_bundle"]["files"]:
            url = self.module.model_source_url(row)
            self.assertTrue(url.startswith("https://huggingface.co/"))
            self.assertIn(f"/resolve/{row['source_revision']}/", url)
            self.assertNotIn("/main/", url)

    def test_manifest_with_unsafe_model_path_is_refused(self):
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        payload["model_bundle"]["files"][0]["path"] = "../production/model.safetensors"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(self.module.SetupRefused):
                self.module.load_manifest(path)

    def test_candidate_path_guard_refuses_production_and_unrelated_paths(self):
        for path in (
            Path("/home/wamocon/ComfyUI"),
            Path("/home/wamocon/comfyui"),
            Path("/tmp/comfy-candidate"),
        ):
            with self.assertRaises(self.module.SetupRefused):
                self.module.assert_candidate_path(path)

    def test_start_and_stop_are_mutually_exclusive(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--manifest",
                str(MANIFEST),
                "--start",
                "--stop",
                "--acknowledge-license-review-required",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--stop must be used alone", result.stderr)


if __name__ == "__main__":
    unittest.main()

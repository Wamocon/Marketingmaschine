import contextlib
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import call, patch
import zlib


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from marketing_machine.comfyui_qualification import (  # noqa: E402
    QUALIFICATION_BINDING_KEY,
    QUALIFICATION_CANDIDATE_ROOT,
    QUALIFICATION_CORE_COMMIT,
    QUALIFICATION_MODEL_FILES,
    QUALIFICATION_NODE_INPUTS,
    QUALIFICATION_OUTPUT_PREFIX,
    QUALIFICATION_REQUIRED_PACKAGES,
    QUALIFICATION_TEXT_ENCODERS,
    QUALIFICATION_WORKFLOW_SHA256,
    QUALIFICATION_XET_HASHES,
    build_qualification_binding,
    build_runtime_identity,
    canonical_workflow_sha256,
    find_qualified_history_evidence,
    inspect_qualification_png,
    observed_runtime_identity,
)
from marketing_machine.integrations import check_comfyui_generation_readiness  # noqa: E402


SCRIPT_PATH = ROOT / "scripts" / "qualify_comfyui_candidate.py"
SPEC = importlib.util.spec_from_file_location("qualify_comfyui_candidate", SCRIPT_PATH)
assert SPEC and SPEC.loader
QUALIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = QUALIFIER
SPEC.loader.exec_module(QUALIFIER)


def workflow() -> dict:
    return json.loads(
        (ROOT / "deploy" / "comfyui" / "flux-schnell-qualification-api.json").read_text(
            encoding="utf-8"
        )
    )


def runtime_stats(*, packages: list[dict] | None = None) -> dict:
    package_rows = packages
    if package_rows is None:
        package_rows = [
            {"name": name, "installed": version, "required": version}
            for name, version in sorted(QUALIFICATION_REQUIRED_PACKAGES.items())
        ]
    return {
        "system": {
            "comfyui_version": "0.25.0",
            "python_version": "3.12.13 (main, Jul 1 2026)",
            "pytorch_version": "2.11.0+cu130",
            "comfy_package_versions": package_rows,
            "argv": ["main.py", "--listen", "127.0.0.1", "--port", "18189"],
            "deploy_environment": "manual",
            "ram_free": 123,
        },
        "devices": [
            {
                "name": "NVIDIA GB10",
                "type": "cuda",
                "index": 0,
                "vram_free": 456,
            }
        ],
    }


def runtime_identity(stats: dict | None = None) -> dict:
    return build_runtime_identity(
        observed_runtime_identity(stats or runtime_stats()),
        candidate_root=QUALIFICATION_CANDIDATE_ROOT,
        core_commit=QUALIFICATION_CORE_COMMIT,
    )


def qualification_binding(
    graph: dict,
    *,
    prompt_id: str,
    submitted_at: datetime,
    stats: dict | None = None,
) -> dict:
    return build_qualification_binding(
        graph,
        prompt_id=prompt_id,
        submitted_at=submitted_at,
        runtime_identity=runtime_identity(stats),
        model_files=QUALIFICATION_MODEL_FILES,
    )


def history_record(
    graph: dict,
    *,
    prompt_id: str = "qualified-prompt",
    filename: str = f"{QUALIFICATION_OUTPUT_PREFIX}_00001_.png",
    subfolder: str = "",
    completed_at: datetime | None = None,
    binding: dict | None = None,
) -> dict:
    completed = completed_at or datetime.now(timezone.utc)
    bound = binding or qualification_binding(
        graph,
        prompt_id=prompt_id,
        submitted_at=completed - timedelta(seconds=30),
    )
    return {
        "prompt_id": prompt_id,
        "prompt": [
            1,
            prompt_id,
            graph,
            {QUALIFICATION_BINDING_KEY: bound},
            ["11"],
        ],
        "outputs": {
            "11": {
                "images": [
                    {
                        "filename": filename,
                        "subfolder": subfolder,
                        "type": "output",
                    }
                ]
            }
        },
        "status": {
            "status_str": "success",
            "completed": True,
            "messages": [
                ["execution_success", {"timestamp": int(completed.timestamp() * 1000)}]
            ],
        },
    }


def node_schema(node_name: str) -> dict:
    inputs = {name: ["ANY"] for name in QUALIFICATION_NODE_INPUTS[node_name]}
    if node_name == "UNETLoader":
        inputs["unet_name"] = [["flux1-schnell.safetensors"]]
    elif node_name == "DualCLIPLoader":
        inputs["clip_name1"] = [["t5xxl_fp8_e4m3fn.safetensors"]]
        inputs["clip_name2"] = [["clip_l.safetensors"]]
    elif node_name == "VAELoader":
        inputs["vae_name"] = [["ae.safetensors"]]
    return {node_name: {"input": {"required": inputs}}}


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def qualification_png(graph: dict) -> bytes:

    prompt = json.dumps(graph, separators=(",", ":"), sort_keys=True).encode("utf-8")
    padding = b"qa-padding\x00" + (b"x" * 1024)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)),
            png_chunk(b"tEXt", b"prompt\x00" + prompt),
            png_chunk(b"tEXt", padding),
            png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")),
            png_chunk(b"IEND", b""),
        )
    )


class ComfyUIQualificationTests(unittest.TestCase):
    def test_pinned_workflow_hash_and_core_nodes_are_exact(self):
        graph = workflow()
        node_types = {node["class_type"] for node in graph.values()}

        self.assertEqual(
            canonical_workflow_sha256(graph), QUALIFICATION_WORKFLOW_SHA256
        )
        self.assertEqual(graph["1"]["inputs"]["unet_name"], "flux1-schnell.safetensors")
        self.assertEqual(
            graph["2"]["inputs"]["clip_name1"],
            "t5xxl_fp8_e4m3fn.safetensors",
        )
        self.assertEqual(graph["2"]["inputs"]["clip_name2"], "clip_l.safetensors")
        self.assertEqual(
            QUALIFICATION_TEXT_ENCODERS,
            ("t5xxl_fp8_e4m3fn.safetensors", "clip_l.safetensors"),
        )
        self.assertEqual(graph["3"]["inputs"]["vae_name"], "ae.safetensors")
        self.assertEqual(
            graph["11"]["inputs"]["filename_prefix"], QUALIFICATION_OUTPUT_PREFIX
        )
        self.assertTrue(node_types.issubset(QUALIFIER.APPROVED_CORE_NODES))

    def test_preflight_enforces_official_dual_clip_loader_positions(self):
        graph = workflow()

        def fake_request(_method, _origin, path, _payload=None, **_kwargs):
            if path == "/queue":
                return {"queue_running": [], "queue_pending": []}
            if path == "/system_stats":
                return runtime_stats()
            if path.startswith("/object_info/"):
                return node_schema(path.rsplit("/", 1)[1])
            if path.startswith("/view_metadata/vae?"):
                return {"format": "pt"}
            raise AssertionError(f"unexpected qualifier probe: {path}")

        with patch.object(QUALIFIER, "request_json", side_effect=fake_request):
            result = QUALIFIER.preflight_candidate(
                "http://127.0.0.1:18189",
                graph,
                candidate_port=18189,
            )
        self.assertIn("DualCLIPLoader", result["node_schemas"])

        def reversed_request(_method, _origin, path, _payload=None, **_kwargs):
            payload = fake_request(_method, _origin, path, _payload, **_kwargs)
            if path == "/object_info/DualCLIPLoader":
                payload["DualCLIPLoader"]["input"]["required"]["clip_name1"] = [
                    ["clip_l.safetensors"]
                ]
                payload["DualCLIPLoader"]["input"]["required"]["clip_name2"] = [
                    ["t5xxl_fp8_e4m3fn.safetensors"]
                ]
            return payload

        with (
            patch.object(QUALIFIER, "request_json", side_effect=reversed_request),
            self.assertRaisesRegex(
                QUALIFIER.QualificationError,
                "both pinned text encoders",
            ),
        ):
            QUALIFIER.preflight_candidate(
                "http://127.0.0.1:18189",
                graph,
                candidate_port=18189,
            )

    def test_history_requires_fresh_exact_graph_runtime_weights_and_safe_output(self):
        graph = workflow()
        now = datetime.now(timezone.utc)
        changed_graph = copy.deepcopy(graph)
        changed_graph["9"]["inputs"]["seed"] += 1
        stale = history_record(
            graph, prompt_id="stale", completed_at=now - timedelta(days=2)
        )
        missing_binding = history_record(graph, prompt_id="unbound", completed_at=now)
        missing_binding["prompt"][3] = {}
        tampered_runtime = history_record(graph, prompt_id="tampered", completed_at=now)
        tampered_runtime["prompt"][3][QUALIFICATION_BINDING_KEY]["runtime"][
            "core_commit"
        ] = "0" * 40
        history = {
            "wrong-graph": history_record(
                changed_graph, prompt_id="wrong-graph", completed_at=now
            ),
            "stale": stale,
            "unbound": missing_binding,
            "tampered": tampered_runtime,
            "valid": history_record(
                graph,
                prompt_id="valid",
                subfolder="qualification",
                completed_at=now,
            ),
        }

        evidence = find_qualified_history_evidence(
            history,
            expected_runtime_observation=observed_runtime_identity(runtime_stats()),
            now=now,
        )

        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(evidence["prompt_id"], "valid")
        self.assertEqual(
            evidence["last_output_artifact"],
            f"qualification/{QUALIFICATION_OUTPUT_PREFIX}_00001_.png",
        )
        self.assertEqual(evidence["seed"], graph["9"]["inputs"]["seed"])

    def test_history_rejects_traversal_failed_execution_and_future_timestamp(self):
        graph = workflow()
        now = datetime.now(timezone.utc)
        traversal = history_record(graph, subfolder="../outside", completed_at=now)
        failed = history_record(graph, prompt_id="failed", completed_at=now)
        failed["status"] = {"status_str": "error", "completed": True, "messages": []}
        future = history_record(
            graph,
            prompt_id="future",
            completed_at=now + timedelta(minutes=10),
        )

        self.assertIsNone(
            find_qualified_history_evidence(
                {"one": traversal, "two": failed, "three": future},
                now=now,
            )
        )

    def test_fetched_png_must_embed_the_exact_graph(self):
        exact = inspect_qualification_png(qualification_png(workflow()))
        changed = workflow()
        changed["9"]["inputs"]["seed"] += 1

        self.assertEqual(
            exact["embedded_workflow_sha256"], QUALIFICATION_WORKFLOW_SHA256
        )
        self.assertEqual(
            exact["sha256"], hashlib.sha256(qualification_png(workflow())).hexdigest()
        )
        self.assertGreater(exact["bytes"], 1024)
        with self.assertRaises(ValueError):
            inspect_qualification_png(qualification_png(changed))
        with self.assertRaises(ValueError):
            inspect_qualification_png(b"not-a-png")

    def test_png_metadata_cannot_replace_a_decodable_image(self):
        graph = workflow()
        prompt = json.dumps(graph, separators=(",", ":"), sort_keys=True).encode()
        padding = png_chunk(b"tEXt", b"padding\x00" + b"x" * 1024)
        header = png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        metadata = png_chunk(b"tEXt", b"prompt\x00" + prompt)
        end = png_chunk(b"IEND", b"")
        cases = {
            "no_header": b"\x89PNG\r\n\x1a\n" + metadata + padding + end,
            "no_image_data": b"\x89PNG\r\n\x1a\n" + header + metadata + padding + end,
            "invalid_zlib": (
                b"\x89PNG\r\n\x1a\n"
                + header
                + metadata
                + padding
                + png_chunk(b"IDAT", b"not-zlib")
                + end
            ),
            "short_scanline": (
                b"\x89PNG\r\n\x1a\n"
                + header
                + metadata
                + padding
                + png_chunk(b"IDAT", zlib.compress(b"\x00\x00"))
                + end
            ),
            "bad_filter": (
                b"\x89PNG\r\n\x1a\n"
                + header
                + metadata
                + padding
                + png_chunk(b"IDAT", zlib.compress(b"\x05\x00\x00\x00"))
                + end
            ),
            "trailing_bytes": qualification_png(graph) + b"hidden",
        }

        for name, payload in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                inspect_qualification_png(payload)

    def test_png_rejects_unsafe_dimensions_encoding_and_split_idat(self):
        graph = workflow()
        prompt = json.dumps(graph, separators=(",", ":"), sort_keys=True).encode()
        metadata = png_chunk(b"tEXt", b"prompt\x00" + prompt)
        padding = png_chunk(b"tEXt", b"padding\x00" + b"x" * 1024)
        end = png_chunk(b"IEND", b"")

        def assembled(header_payload: bytes, chunks: bytes) -> bytes:
            return (
                b"\x89PNG\r\n\x1a\n"
                + png_chunk(b"IHDR", header_payload)
                + metadata
                + padding
                + chunks
                + end
            )

        cases = {
            "too_large": assembled(
                struct.pack(">IIBBBBB", 9000, 1, 8, 2, 0, 0, 0),
                png_chunk(b"IDAT", zlib.compress(b"")),
            ),
            "unsupported_bit_depth": assembled(
                struct.pack(">IIBBBBB", 1, 1, 16, 2, 0, 0, 0),
                png_chunk(b"IDAT", zlib.compress(b"\x00" * 7)),
            ),
            "interlaced": assembled(
                struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 1),
                png_chunk(b"IDAT", zlib.compress(b"\x00" * 4)),
            ),
            "split_idat": assembled(
                struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0),
                png_chunk(b"IDAT", zlib.compress(b"\x00\x00"))
                + png_chunk(b"tEXt", b"note\x00break")
                + png_chunk(b"IDAT", zlib.compress(b"\x00\x00")),
            ),
        }
        for name, payload in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                inspect_qualification_png(payload)

    def test_missing_or_wrong_package_telemetry_fails_closed(self):
        missing = runtime_stats(packages=[])
        wrong = runtime_stats(
            packages=[
                {"name": "comfyui-frontend-package", "installed": "1", "required": "1"}
            ]
        )

        with self.assertRaisesRegex(ValueError, "missing or empty"):
            observed_runtime_identity(missing)
        with self.assertRaisesRegex(ValueError, "exact pinned package set"):
            observed_runtime_identity(wrong)

    def test_readiness_verifies_current_bound_history_and_fetched_png_without_mutation(
        self,
    ):
        graph = workflow()
        stats = runtime_stats()
        history = {"qualified-prompt": history_record(graph)}
        requested: list[str] = []

        def fake_get(url: str) -> dict:
            requested.append(url)
            if url.endswith("/system_stats"):
                return stats
            if "/object_info/" in url:
                return node_schema(url.rsplit("/", 1)[1])
            if "/view_metadata/vae?" in url:
                return {"format": "pt", "size": 335304388}
            if url.endswith("/history?max_items=64"):
                return history
            raise AssertionError(f"unexpected read-only probe: {url}")

        with (
            patch("marketing_machine.integrations._get_json", side_effect=fake_get),
            patch(
                "marketing_machine.integrations._get_binary",
                return_value=qualification_png(graph),
            ) as binary,
        ):
            result = check_comfyui_generation_readiness(
                "http://comfyui:18189", required=True
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["used_successfully"])
        self.assertTrue(result["package_telemetry_complete"])
        self.assertEqual(result["workflow_qualification"], "history_verified")
        self.assertEqual(
            result["last_output_sha256"],
            hashlib.sha256(qualification_png(graph)).hexdigest(),
        )
        self.assertGreater(result["last_output_bytes"], 1024)
        self.assertTrue(result["human_visual_approval_required"])
        self.assertFalse(result["human_visual_approval_verified"])
        self.assertTrue(
            all("/prompt" not in url and "/queue" not in url for url in requested)
        )
        binary.assert_called_once()

    def test_candidate_url_accepts_only_loopback_pinned_port(self):
        rejected = (
            "https://8.8.8.8:18189",
            "http://192.168.178.75:18189",
            "http://127.0.0.1:8188",
            "http://user:secret@127.0.0.1:18189",
            "http://candidate.example.test:18189",
            "http://127.0.0.1:18189/api",
            "file://127.0.0.1:18189",
        )
        for url in rejected:
            with self.subTest(url=url), self.assertRaises(QUALIFIER.QualificationError):
                QUALIFIER.validate_isolated_candidate_url(url, expected_port=18189)

        self.assertEqual(
            QUALIFIER.validate_isolated_candidate_url(
                "http://127.0.0.1:18189", expected_port=18189
            ),
            ("http://127.0.0.1:18189", "loopback"),
        )

    def test_candidate_root_is_exact_resolved_checkout_and_symlinks_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / ".git").mkdir()
            manifest = {
                "production_guard": {
                    "candidate_root": str(root),
                    "forbidden_roots": [str(root.parent / "production")],
                }
            }
            self.assertEqual(
                QUALIFIER.resolve_candidate_root(str(root), manifest), root
            )
            with patch.object(
                QUALIFIER, "_path_has_symlink_component", return_value=True
            ):
                with self.assertRaisesRegex(
                    QUALIFIER.QualificationError, "symbolic link"
                ):
                    QUALIFIER.resolve_candidate_root(str(root), manifest)
            with self.assertRaisesRegex(QUALIFIER.QualificationError, "exactly match"):
                QUALIFIER.resolve_candidate_root(str(root.parent), manifest)

    def test_model_files_are_hashed_and_sized_from_candidate_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            expected: dict[str, dict[str, object]] = {}
            rows: list[dict[str, object]] = []
            for index, relative in enumerate(QUALIFICATION_MODEL_FILES, start=1):
                payload = f"model-{index}".encode()
                path = root.joinpath(*relative.split("/"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
                evidence = {
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                expected[relative] = evidence
                rows.append({"path": relative, **evidence})
            manifest = {"model_bundle": {"files": rows}}

            with patch.object(QUALIFIER, "QUALIFICATION_MODEL_FILES", expected):
                observed = QUALIFIER.verify_model_files(root, manifest)
            self.assertEqual(observed, dict(sorted(expected.items())))

            rows[0]["bytes"] = int(rows[0]["bytes"]) + 1
            with (
                patch.object(QUALIFIER, "QUALIFICATION_MODEL_FILES", expected),
                self.assertRaisesRegex(QUALIFIER.QualificationError, "size mismatch"),
            ):
                QUALIFIER.verify_model_files(root, manifest)

    def test_git_checkout_requires_full_commit_clean_tree_and_no_third_party_nodes(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            custom_nodes = root / "custom_nodes"
            custom_nodes.mkdir()
            (custom_nodes / "example_node.py.example").write_text(
                "example", encoding="utf-8"
            )
            (custom_nodes / "websocket_image_save.py").write_text(
                "core", encoding="utf-8"
            )
            with patch.object(
                QUALIFIER,
                "_run_git",
                side_effect=[QUALIFICATION_CORE_COMMIT, ""],
            ):
                evidence = QUALIFIER.verify_git_checkout(
                    root,
                    expected_commit=QUALIFICATION_CORE_COMMIT,
                )
            self.assertEqual(evidence["commit"], QUALIFICATION_CORE_COMMIT)
            self.assertFalse(evidence["third_party_custom_nodes_present"])

            (custom_nodes / "unreviewed-node").mkdir()
            with (
                patch.object(
                    QUALIFIER,
                    "_run_git",
                    side_effect=[QUALIFICATION_CORE_COMMIT, ""],
                ),
                self.assertRaisesRegex(QUALIFIER.QualificationError, "third-party"),
            ):
                QUALIFIER.verify_git_checkout(
                    root, expected_commit=QUALIFICATION_CORE_COMMIT
                )

    def test_submit_timeout_invokes_targeted_cleanup_for_its_prompt_id(self):
        graph = workflow()
        prompt_id = "68d55e04-86a2-40f8-a2d3-50223ec8349f"
        binding = qualification_binding(
            graph,
            prompt_id=prompt_id,
            submitted_at=datetime.now(timezone.utc),
        )
        with (
            patch.object(
                QUALIFIER,
                "request_json",
                return_value={"prompt_id": prompt_id},
            ),
            patch.object(QUALIFIER.time, "monotonic", side_effect=[0.0, 2.0]),
            patch.object(QUALIFIER, "cancel_submitted_prompt") as cleanup,
            self.assertRaisesRegex(QUALIFIER.QualificationError, "timed out"),
        ):
            QUALIFIER.submit_and_wait(
                "http://127.0.0.1:18189",
                graph,
                binding=binding,
                prompt_id=prompt_id,
                timeout_seconds=1.0,
                poll_seconds=1.0,
            )
        cleanup.assert_called_once_with("http://127.0.0.1:18189", prompt_id)

    def test_timeout_cleanup_targets_only_the_submitted_prompt(self):
        prompt_id = "68d55e04-86a2-40f8-a2d3-50223ec8349f"
        with patch.object(QUALIFIER, "request_action") as action:
            errors = QUALIFIER.cancel_submitted_prompt(
                "http://127.0.0.1:18189", prompt_id
            )

        self.assertEqual(errors, [])
        self.assertEqual(
            action.call_args_list,
            [
                call("http://127.0.0.1:18189", "/interrupt", {"prompt_id": prompt_id}),
                call("http://127.0.0.1:18189", "/queue", {"delete": [prompt_id]}),
                call("http://127.0.0.1:18189", "/history", {"delete": [prompt_id]}),
            ],
        )
        self.assertNotIn("clear", repr(action.call_args_list))

    def test_missing_attestation_refuses_before_assets_or_network(self):
        stderr = io.StringIO()
        with patch.object(QUALIFIER, "load_qualification_assets") as loader:
            with contextlib.redirect_stderr(stderr):
                exit_code = QUALIFIER.main(
                    [
                        "--base-url",
                        "http://127.0.0.1:18189",
                        "--candidate-root",
                        QUALIFICATION_CANDIDATE_ROOT,
                    ]
                )

        self.assertEqual(exit_code, 2)
        loader.assert_not_called()
        self.assertIn("attest-isolated-candidate", stderr.getvalue())

    def test_manifest_uses_full_pins_verified_ungated_sources_and_human_gate(self):
        manifest = json.loads(
            (
                ROOT / "deploy" / "comfyui" / "flux-schnell-candidate-manifest.json"
            ).read_text(encoding="utf-8")
        )
        files = {item["path"]: item for item in manifest["model_bundle"]["files"]}

        self.assertEqual(manifest["runtime"]["commit"], QUALIFICATION_CORE_COMMIT)
        self.assertEqual(len(manifest["runtime"]["commit"]), 40)
        self.assertEqual(
            manifest["runtime"]["required_packages"], QUALIFICATION_REQUIRED_PACKAGES
        )
        self.assertEqual(len(files), 4)
        self.assertEqual(
            {
                path: evidence["sha256"]
                for path, evidence in QUALIFICATION_MODEL_FILES.items()
            },
            {
                "models/diffusion_models/flux1-schnell.safetensors": "9403429e0052277ac2a87ad800adece5481eecefd9ed334e1f348723621d2a0a",
                "models/text_encoders/clip_l.safetensors": "660c6f5b1abae9dc498ac2d21e1347d2abdb0cf6c0c0c8576cd796491d9a6cdd",
                "models/text_encoders/t5xxl_fp8_e4m3fn.safetensors": "7d330da4816157540d6bb7838bf63a0f02f573fc48ca4d8de34bb0cbfd514f09",
                "models/vae/ae.safetensors": "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38",
            },
        )
        for relative, expected in QUALIFICATION_MODEL_FILES.items():
            self.assertEqual(files[relative]["bytes"], expected["bytes"])
            self.assertEqual(files[relative]["sha256"], expected["sha256"])
            self.assertEqual(
                files[relative]["xet_hash"], QUALIFICATION_XET_HASHES[relative]
            )
            self.assertNotEqual(files[relative]["sha256"], files[relative]["xet_hash"])
            self.assertEqual(len(files[relative]["source_revision"]), 40)
            self.assertFalse(files[relative]["gated_source"])
        self.assertTrue(manifest["readiness"]["human_visual_approval_required"])
        self.assertFalse(manifest["readiness"]["automated_visual_approval_allowed"])
        self.assertEqual(
            manifest["readiness"]["workflow_sha256"],
            QUALIFICATION_WORKFLOW_SHA256,
        )
        self.assertEqual(
            manifest["readiness"]["recognized_text_encoders"],
            list(QUALIFICATION_TEXT_ENCODERS),
        )
        self.assertEqual(
            manifest["readiness"]["dual_clip_loader_positions"],
            {
                "clip_name1": "t5xxl_fp8_e4m3fn.safetensors",
                "clip_name2": "clip_l.safetensors",
            },
        )

    def test_manifest_loader_rejects_xet_hash_used_as_file_sha256(self):
        manifest = json.loads(
            (
                ROOT / "deploy" / "comfyui" / "flux-schnell-candidate-manifest.json"
            ).read_text(encoding="utf-8")
        )
        manifest["model_bundle"]["files"][0]["sha256"] = manifest["model_bundle"][
            "files"
        ][0]["xet_hash"]
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with (
                patch.object(QUALIFIER, "MANIFEST_PATH", manifest_path),
                self.assertRaisesRegex(
                    QUALIFIER.QualificationError,
                    "confuses the informational Xet hash",
                ),
            ):
                QUALIFIER.load_qualification_assets()


if __name__ == "__main__":
    unittest.main()

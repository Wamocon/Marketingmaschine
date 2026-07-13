from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_PREFIXES = ("mock-", "smoke-", "ui-test-")


def has_test_prefix(value: Any, prefixes: tuple[str, ...]) -> bool:
    if isinstance(value, str):
        return value.startswith(prefixes)
    if isinstance(value, list):
        return any(has_test_prefix(item, prefixes) for item in value)
    if isinstance(value, dict):
        return any(has_test_prefix(item, prefixes) for item in value.values())
    return False


def safe_runtime_root(path: Path) -> Path:
    root = path.resolve()
    expected = ["states", "events", "performance", "leads", "outbox"]
    if not root.exists():
        raise FileNotFoundError(f"runtime data directory not found: {root}")
    missing = [name for name in expected if not (root / name).is_dir()]
    if missing:
        raise ValueError(f"refusing cleanup; missing expected runtime folders {missing} under {root}")
    return root


def cleanup_states(root: Path, prefixes: tuple[str, ...], apply: bool) -> int:
    removed = 0
    for path in sorted((root / "states").glob("*.json")):
        if path.stem.startswith(prefixes):
            removed += 1
            if apply:
                path.unlink()
    return removed


def cleanup_jsonl(path: Path, prefixes: tuple[str, ...], apply: bool) -> tuple[int, int]:
    if not path.exists():
        return (0, 0)

    kept_lines: list[str] = []
    removed = 0
    total = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        total += 1
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            kept_lines.append(line)
            continue
        if has_test_prefix(payload, prefixes):
            removed += 1
        else:
            kept_lines.append(json.dumps(payload, ensure_ascii=False))

    if apply:
        path.write_text(("\n".join(kept_lines) + "\n") if kept_lines else "", encoding="utf-8")
    return total, removed


def cleanup(root: Path, prefixes: tuple[str, ...], apply: bool) -> dict[str, Any]:
    if apply:
        raise RuntimeError(
            "in-place runtime cleanup is retired; never rewrite active audit JSONL files"
        )
    runtime_root = safe_runtime_root(root)
    removed_states = cleanup_states(runtime_root, prefixes, apply)
    jsonl_results = []
    for directory in ("events", "performance", "leads", "outbox"):
        for path in sorted((runtime_root / directory).glob("*.jsonl")):
            total, removed = cleanup_jsonl(path, prefixes, apply)
            jsonl_results.append({"file": str(path.relative_to(runtime_root)), "lines": total, "removed": removed})

    return {
        "mode": "apply" if apply else "dry_run",
        "root": str(runtime_root),
        "prefixes": list(prefixes),
        "removed_state_files": removed_states,
        "jsonl": jsonl_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely remove mock/smoke test data from runtime-data.")
    parser.add_argument("--root", default="runtime-data", help="Runtime data directory containing states/events/performance/leads/outbox.")
    parser.add_argument("--prefix", action="append", dest="prefixes", help="Content-id prefix to remove. Can be repeated.")
    parser.add_argument("--apply", action="store_true", help="Retired safety trap: always refuses in-place deletion.")
    args = parser.parse_args()

    prefixes = tuple(args.prefixes or DEFAULT_PREFIXES)
    result = cleanup(Path(args.root), prefixes, args.apply)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

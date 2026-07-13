#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from marketing_machine.content_quality import (  # noqa: E402
    EVALUATION_SCHEMA_VERSION,
    ContentQualityInputError,
    build_refinement_request,
    evaluate_content_payload,
    extract_content_candidates,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate captured K1-K5 marketing content with the deterministic "
            "WAMOCON release rubric. No model or network call is made."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="JSON file containing one state/brief, a list, or an object with items",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="repository root containing config and the five campaign files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional JSON report path; stdout is used when omitted",
    )
    parser.add_argument(
        "--refinement-attempt",
        type=int,
        choices=(0, 1),
        help=(
            "attach a bounded structured refinement request for failed results; "
            "0 and 1 are the only permitted attempts"
        ),
    )
    return parser


def _load_candidates(paths: Sequence[Path]) -> list[Any]:
    candidates: list[Any] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        candidates.extend(extract_content_candidates(payload))
    return candidates


def _render(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _emit(payload: Any, output: Path | None) -> None:
    rendered = _render(payload)
    if output is None:
        sys.stdout.write(rendered)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")


def _error_payload(exc: Exception) -> dict[str, Any]:
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "release_ready": False,
        "error": {
            "code": "invalid_input",
            "message": str(exc),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        candidates = _load_candidates(args.inputs)
        report = evaluate_content_payload(candidates, repo_root=args.repo_root.resolve())
        if args.refinement_attempt is not None:
            for result in report["results"]:
                if not result["release_ready"]:
                    result["refinement_request"] = build_refinement_request(
                        result,
                        attempt=args.refinement_attempt,
                    )
        _emit(report, args.output)
    except (ContentQualityInputError, json.JSONDecodeError, OSError, ValueError) as exc:
        _emit(_error_payload(exc), args.output)
        return 2
    return 0 if bool(report["release_ready"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

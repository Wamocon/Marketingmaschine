from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.storage import JsonStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely clean WAMOCON mock/smoke test records.")
    parser.add_argument("--root", default="runtime-data", help="Runtime data root. Defaults to ./runtime-data.")
    parser.add_argument("--prefix", action="append", default=["mock-", "smoke-"], help="Content ID prefix to delete.")
    parser.add_argument("--dry-run", action="store_true", help="Report matching records without changing files.")
    parser.add_argument("--confirm", default="", help="Deprecated; deletion is always refused.")
    args = parser.parse_args()

    if not args.dry_run:
        print(
            json.dumps(
                {
                    "status": "refused",
                    "reason": "in-place cleanup of active runtime audit files is retired; run only --dry-run and use a backed-up offline migration",
                },
                indent=2,
            )
        )
        return 2

    store = JsonStore(Path(args.root))
    summary = store.cleanup_test_data(tuple(args.prefix), dry_run=True)
    print(json.dumps({"status": "ok", "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

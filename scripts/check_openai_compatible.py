from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def check_models(base_url: str, api_key: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/models"
    try:
        request = Request(url, headers={"Authorization": f"Bearer {api_key}", "User-Agent": "wamocon-api-probe/0.1"})
        with urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
            models = sorted(item.get("id", "") for item in payload.get("data", []) if item.get("id"))
            return {"base_url": base_url, "ok": response.status == 200, "status": response.status, "models": models[:25]}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        return {"base_url": base_url, "ok": False, "status": exc.code, "error": body}
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return {"base_url": base_url, "ok": False, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe OpenAI-compatible /models endpoints without printing API keys.")
    parser.add_argument("--env-file", default="", help="Optional env file containing the API key.")
    parser.add_argument("--api-key-var", default="KIMI_API_KEY")
    parser.add_argument("base_urls", nargs="+")
    args = parser.parse_args()

    if args.env_file:
        load_env_file(Path(args.env_file))
    api_key = os.environ.get(args.api_key_var, "")
    if not api_key:
        print(json.dumps({"status": "failed", "error": f"{args.api_key_var} is not configured"}, indent=2))
        return 1

    results = [check_models(base_url, api_key) for base_url in args.base_urls]
    ok = any(result.get("ok") for result in results)
    print(json.dumps({"status": "ok" if ok else "failed", "results": results}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

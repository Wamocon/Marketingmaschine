import json
import socket
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.ai_client import AIClientError, OpenAICompatibleClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size=None):
        payload = json.dumps(self.payload).encode("utf-8")
        return payload if size is None else payload[:size]


def completion_payload(content=None):
    return {
        "id": "chatcmpl-test",
        "choices": [{"message": {"content": json.dumps(content or {"ok": True})}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
    }


class AIClientTests(unittest.TestCase):
    def make_client(self, **overrides):
        values = {
            "provider": "local_qwen",
            "model": "qwen-test",
            "base_url": "http://model.test/v1",
            "api_key": "secret-value",
            "timeout_seconds": 3,
            "max_retries": 1,
            "sleep": lambda _: None,
        }
        values.update(overrides)
        return OpenAICompatibleClient(**values)

    def test_posts_chat_completion_with_reasoning_disabled_and_strict_schema(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["authorization"] = request.headers.get("Authorization")
            return FakeResponse(completion_payload({"channel_copy": {}}))

        with patch("marketing_machine.ai_client.urlopen", side_effect=fake_urlopen):
            result = self.make_client().complete_json(
                system_prompt="Return JSON.",
                user_prompt="Create content.",
                json_schema={"type": "object"},
            )

        self.assertEqual(captured["url"], "http://model.test/v1/chat/completions")
        self.assertEqual(captured["timeout"], 3.0)
        self.assertEqual(captured["payload"]["reasoning_effort"], "none")
        self.assertEqual(captured["payload"]["response_format"]["type"], "json_schema")
        self.assertTrue(captured["payload"]["response_format"]["json_schema"]["strict"])
        self.assertEqual(captured["authorization"], "Bearer secret-value")
        self.assertEqual(result.data, {"channel_copy": {}})
        self.assertEqual(result.usage["total_tokens"], 18)

    def test_retries_transient_failure_then_succeeds(self):
        failure = HTTPError("http://model.test", 503, "unavailable", {}, BytesIO(b"temporary"))
        sleeps = []
        client = self.make_client(sleep=sleeps.append)

        with patch(
            "marketing_machine.ai_client.urlopen",
            side_effect=[failure, FakeResponse(completion_payload())],
        ):
            result = client.complete_json(
                system_prompt="Return JSON.",
                user_prompt="Create content.",
                json_schema={"type": "object"},
            )

        self.assertEqual(result.attempts, 2)
        self.assertEqual(sleeps, [0.25])

    def test_downgrades_optional_schema_parameters_after_http_400(self):
        failure = HTTPError("http://model.test", 400, "unsupported", {}, BytesIO(b"unsupported response_format"))
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            if len(requests) == 1:
                raise failure
            return FakeResponse(completion_payload())

        with patch("marketing_machine.ai_client.urlopen", side_effect=fake_urlopen):
            result = self.make_client().complete_json(
                system_prompt="Return JSON.",
                user_prompt="Create content.",
                json_schema={"type": "object"},
            )

        self.assertEqual(requests[0]["response_format"]["type"], "json_schema")
        self.assertEqual(requests[1]["response_format"]["type"], "json_object")
        self.assertEqual(requests[1]["reasoning_effort"], "none")
        self.assertEqual(result.compatibility_mode, "json_object")
        self.assertEqual(result.attempts, 2)

    def test_timeout_is_classified_without_endpoint_or_secret_in_error(self):
        client = self.make_client(max_retries=0)

        with patch("marketing_machine.ai_client.urlopen", side_effect=URLError(socket.timeout("slow"))):
            with self.assertRaises(AIClientError) as raised:
                client.complete_json(
                    system_prompt="Return JSON.",
                    user_prompt="Create content.",
                    json_schema={"type": "object"},
                )

        self.assertEqual(raised.exception.code, "timeout")
        self.assertNotIn("secret-value", str(raised.exception))
        self.assertNotIn("model.test", str(raised.exception))


if __name__ == "__main__":
    unittest.main()

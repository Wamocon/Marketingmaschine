import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine import ai_client, integrations, trend_sources
from marketing_machine.ai_client import AIClientError, OpenAICompatibleClient
from marketing_machine.http_safety import read_limited
from marketing_machine.trend_sources import ConfiguredTrendSearchClient


class _SinkHandler(BaseHTTPRequestHandler):
    requests = []

    def do_GET(self):
        type(self).requests.append(
            {"path": self.path, "authorization": self.headers.get("Authorization")}
        )
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, _format, *_args):
        return


class _RedirectHandler(BaseHTTPRequestHandler):
    target = ""

    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", type(self).target)
        self.end_headers()

    def log_message(self, _format, *_args):
        return


class _OversizedResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size=None):
        payload = b"x" * (size or 32)
        return payload if size is None else payload[:size]


class HttpSafetyTests(unittest.TestCase):
    def test_all_credentialed_clients_refuse_cross_origin_redirects(self):
        _SinkHandler.requests = []
        sink = ThreadingHTTPServer(("127.0.0.1", 0), _SinkHandler)
        redirect = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
        _RedirectHandler.target = f"http://127.0.0.1:{sink.server_port}/credential-sink"
        threads = [
            threading.Thread(target=sink.serve_forever, daemon=True),
            threading.Thread(target=redirect.serve_forever, daemon=True),
        ]
        for thread in threads:
            thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{redirect.server_port}/provider",
                headers={"Authorization": "Bearer must-not-be-forwarded"},
            )
            for opener in (ai_client.urlopen, integrations.urlopen, trend_sources.urlopen):
                with self.subTest(opener=opener.__module__):
                    with self.assertRaises(HTTPError) as raised:
                        opener(request, timeout=2)
                    self.assertEqual(raised.exception.code, 302)
            self.assertEqual(_SinkHandler.requests, [])
        finally:
            redirect.shutdown()
            sink.shutdown()
            redirect.server_close()
            sink.server_close()

    def test_limited_reader_rejects_oversized_body(self):
        with self.assertRaisesRegex(ValueError, "safe size limit"):
            read_limited(_OversizedResponse(), max_bytes=8, label="test response")

    def test_model_integration_and_trend_paths_all_enforce_body_limits(self):
        client = OpenAICompatibleClient(
            provider="local",
            model="qwen-test",
            base_url="http://model.invalid/v1",
            api_key="secret",
            max_retries=0,
        )
        with patch("marketing_machine.ai_client.urlopen", return_value=_OversizedResponse()):
            with self.assertRaises(AIClientError) as model_error:
                client.complete_json(
                    system_prompt="Return JSON",
                    user_prompt="Return JSON",
                    json_schema={"type": "object"},
                )
        self.assertEqual(model_error.exception.code, "invalid_response")

        with patch("marketing_machine.integrations.urlopen", return_value=_OversizedResponse()):
            integration = integrations.check_openai_compatible_models(
                "local_openai",
                "http://model.invalid/v1",
                "secret",
                "qwen-test",
            )
        self.assertFalse(integration["ok"])
        self.assertNotIn("secret", str(integration))

        trend = ConfiguredTrendSearchClient(env={"SEARXNG_BASE_URL": "http://search.invalid"})
        with patch("marketing_machine.trend_sources.urlopen", return_value=_OversizedResponse()):
            result = trend._request_json(
                Request("http://search.invalid/search"),
                adapter="searxng",
            )
        self.assertEqual(result, {})
        telemetry = trend.telemetry()[0]
        self.assertIn("safe size limit", telemetry["errors"][0]["message"])


if __name__ == "__main__":
    unittest.main()

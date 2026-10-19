"""Real HTTP serialization and bounded-transport contract tests, NO internet/API."""
import io
import json
from unittest.mock import patch
import urllib.error

from django.test import SimpleTestCase

from agentforge.llm import LLMError
from agentforge_django.guard import BoundaryDenied
from agentforge_django.v05_broker import BoundedDeepSeek


class _Response:
    def __init__(self, payload):
        self.data = json.dumps(payload).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, n):
        return self.data[:n]


class BrokerHttpTests(SimpleTestCase):
    def make(self, max_requests=3):
        return BoundedDeepSeek(
            api_key="fixture-only", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_requests=max_requests,
        )

    def test_serialized_request_and_real_provider_usage_accounting(self):
        captured = []
        payload = {"choices": [{"message": {"content": '{"decision":"BLOCKED"}'}}],
                   "usage": {"prompt_tokens": 140, "completion_tokens": 30,
                             "total_tokens": 170}}
        class Opener:
            def open(self, req, timeout):
                captured.append((req, timeout))
                return _Response(payload)
        client = self.make()
        with patch("agentforge_django.v05_broker.urllib.request.build_opener",
                   return_value=Opener()):
            self.assertEqual(client._request("system", "fixture"),
                             '{"decision":"BLOCKED"}')
        request, timeout = captured[0]
        body = json.loads(request.data)
        self.assertEqual(body["model"], "deepseek-chat")
        self.assertEqual(body["max_tokens"], 2048)
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertIn("Bearer fixture-only", request.get_header("Authorization"))
        self.assertEqual(client.calls, 1)
        self.assertEqual(client.remaining, 2)
        self.assertEqual(client.usage["total_tokens"], 170)
        self.assertEqual(client.usage_reports, 1)

    def test_missing_provider_usage_stays_unknown(self):
        class Opener:
            def open(self, req, timeout):
                return _Response({"choices": [{"message": {"content": "{}"}}]})
        client = self.make()
        with patch("agentforge_django.v05_broker.urllib.request.build_opener",
                   return_value=Opener()):
            client._request("system", "fixture")
        self.assertEqual(client.usage_reports, 0)
        self.assertEqual(client.usage["total_tokens"], 0)

    def test_api_failure_consumes_one_attempt_and_never_retries(self):
        class Opener:
            def open(self, req, timeout):
                raise urllib.error.HTTPError(req.full_url, 429, "rate limit",
                                             {}, io.BytesIO(b"private"))
        client = self.make(max_requests=1)
        with patch("agentforge_django.v05_broker.urllib.request.build_opener",
                   return_value=Opener()):
            with self.assertRaises(LLMError) as captured:
                client._request("system", "fixture")
        self.assertEqual(str(captured.exception),
                         "DeepSeek request failed (redacted)")
        self.assertEqual(client.calls, 1)
        self.assertEqual(client.remaining, 0)
        with self.assertRaises(BoundaryDenied):
            client._request("system", "fixture")

    def test_invalid_usage_values_not_trusted(self):
        class Opener:
            def open(self, req, timeout):
                return _Response({"choices":[{"message":{"content":"{}"}}],
                                  "usage":{"prompt_tokens":-1,
                                           "completion_tokens":15,
                                           "total_tokens":14}})
        client = self.make()
        with patch("agentforge_django.v05_broker.urllib.request.build_opener",
                   return_value=Opener()):
            client._request("system","fixture")
        self.assertEqual(client.usage_reports, 0)

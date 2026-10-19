"""Critical V0.7 regression: V0.6 Broker must accept 5 real role calls over HTTPS."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from agentforge_django.guard import BoundaryDenied
from agentforge_django.v05_broker import create_v05_broker


class BrokerContractTests(SimpleTestCase):
    def make(self, url="https://api.deepseek.com"):
        return SimpleNamespace(base_url=url, api_key="offline-synthetic-placeholder",
                               model="deepseek-chat")

    @override_settings(AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER=True)
    def test_v06_five_role_budget_is_actually_constructible(self):
        with patch("agentforge_django.v05_broker.ExternalLLMSettings.from_env",
                   return_value=self.make()):
            client = create_v05_broker(max_requests=5)
            self.assertEqual(client.remaining, 5)
            self.assertEqual(client.max_attempts, 1)
            self.assertEqual(client.model, "deepseek-chat")

    @override_settings(AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER=True)
    def test_redirect_http_credentials_query_port_disallowed(self):
        bad = [
            "http://api.deepseek.com",
            "https://api.deepseek.com:444",
            "https://user:pass@api.deepseek.com",
            "https://api.deepseek.com/?token=secret",
            "https://attacker.invalid",
            "https://api.deepseek.com.evil.test",
        ]
        for address in bad:
            with self.subTest(address=address), patch(
                "agentforge_django.v05_broker.ExternalLLMSettings.from_env",
                return_value=self.make(address)
            ), self.assertRaises(BoundaryDenied):
                create_v05_broker(max_requests=5)

    @override_settings(AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER=True)
    def test_bad_model_budget_rejected(self):
        with self.assertRaises(BoundaryDenied):
            create_v05_broker(max_requests=10)

    @override_settings(AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER=False)
    def test_explicit_source_transfer_gate(self):
        with self.assertRaises(BoundaryDenied):
            create_v05_broker(max_requests=5)

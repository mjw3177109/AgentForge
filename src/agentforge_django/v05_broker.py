"""Trusted-side DeepSeek broker. No credentials are ever sent to Docker.

Limits are per-run HTTP requests, prompts, responses and output tokens.
Token *cost* is not observed/billed; do not claim a monetary spending ceiling.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from agentforge.llm import LLMError, OpenAICompatibleClient
from agentforge.runtime_config import ExternalLLMSettings

from .guard import BoundaryDenied


class _DenyRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward model-provider credentials to a redirected origin."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class BoundedDeepSeek(OpenAICompatibleClient):
    def __init__(self, *, api_key, base_url, model, max_requests=3, seconds=150):
        super().__init__(
            base_url=base_url, model=model, api_key=api_key,
            timeout=30, max_attempts=1,
        )
        self.remaining = max_requests
        self.calls = 0
        self.deadline = time.monotonic() + seconds
        self.seconds = seconds

    def _request(self, system, user):
        if self.remaining <= 0 or time.monotonic() >= self.deadline:
            raise BoundaryDenied("V0.5 model call/time budget exhausted")
        if len(system) > 3500 or len(user) > 45000:
            raise BoundaryDenied("V0.5 model prompt exceeds allowed size")
        self.remaining -= 1
        self.calls += 1
        body = json.dumps({
            "model": self.model,
            "temperature": 0,
            "max_tokens": 2048,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint(), data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            }, method="POST",
        )
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise BoundaryDenied("V0.5 model wall-time limit exceeded")
        try:
            opener = urllib.request.build_opener(_DenyRedirect)
            with opener.open(
                request, timeout=min(30, remaining)
            ) as response:
                bounded = response.read(128001)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMError("DeepSeek request failed (redacted)") from exc
        if len(bounded) > 128000:
            raise BoundaryDenied("Model response byte limit exceeded")
        try:
            content = json.loads(bounded)["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError("DeepSeek response structure invalid") from exc
        if not isinstance(content, str) or len(content) > 45000:
            raise BoundaryDenied("Model content limit exceeded")
        return content


def create_v05_broker():
    if not getattr(settings, "AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER", False):
        raise BoundaryDenied("Sending source to the LLM is not authorized")
    config = ExternalLLMSettings.from_env()
    host = urllib.parse.urlparse(config.base_url).hostname
    hosts = getattr(settings, "AGENTFORGE_V05_ALLOWED_LLM_HOSTS", ("api.deepseek.com",))
    if host not in hosts or config.model != "deepseek-chat" or not config.api_key:
        raise BoundaryDenied("V0.5 requires an explicitly allowed DeepSeek model and API key")
    return BoundedDeepSeek(
        api_key=config.api_key, base_url=config.base_url, model=config.model
    )

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from agentforge.llm import OpenAICompatibleClient


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class ExternalLLMSettings:
    base_url: str
    model: str
    api_key: str = ""
    allow_anonymous: bool = False
    timeout: float = 45.0
    max_attempts: int = 3

    @classmethod
    def from_env(cls) -> "ExternalLLMSettings":
        base_url = os.getenv("AGENTFORGE_LLM_BASE_URL", "").strip()
        model = os.getenv("AGENTFORGE_LLM_MODEL", "").strip()
        api_key = os.getenv("AGENTFORGE_LLM_API_KEY", "")
        if not base_url or not model:
            raise RuntimeError("AGENTFORGE_LLM_BASE_URL and AGENTFORGE_LLM_MODEL are required")
        settings = cls(
            base_url=base_url,
            model=model,
            api_key=api_key,
            allow_anonymous=_truthy(os.getenv("AGENTFORGE_LLM_ALLOW_ANONYMOUS")),
            timeout=float(os.getenv("AGENTFORGE_LLM_TIMEOUT", "45")),
            max_attempts=int(os.getenv("AGENTFORGE_LLM_MAX_ATTEMPTS", "3")),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("LLM base URL must be an absolute http(s) URL")
        is_local = parsed.hostname.lower() in _LOCAL_HOSTS
        if parsed.scheme != "https" and not is_local:
            raise ValueError("External LLM endpoints must use HTTPS; plain HTTP is only allowed for loopback testing")
        if not self.api_key and not self.allow_anonymous and not is_local:
            raise ValueError("External LLM endpoint requires AGENTFORGE_LLM_API_KEY unless anonymous mode is explicitly enabled")
        if not 1 <= self.max_attempts <= 5:
            raise ValueError("AGENTFORGE_LLM_MAX_ATTEMPTS must be between 1 and 5")
        if not 1 <= self.timeout <= 180:
            raise ValueError("AGENTFORGE_LLM_TIMEOUT must be between 1 and 180 seconds")

    def client(self) -> OpenAICompatibleClient:
        self.validate()
        return OpenAICompatibleClient(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            timeout=self.timeout,
            max_attempts=self.max_attempts,
        )

    def safe_summary(self) -> dict[str, object]:
        parsed = urlparse(self.base_url)
        return {
            "endpoint": f"{parsed.scheme}://{parsed.netloc}",
            "model": self.model,
            "api_key_configured": bool(self.api_key),
            "allow_anonymous": self.allow_anonymous,
            "timeout": self.timeout,
            "max_attempts": self.max_attempts,
        }

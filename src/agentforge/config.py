from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import os


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in {None, ""} else default


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value is not None else default


@dataclass(frozen=True)
class Settings:
    github_app_id: str | None = field(default_factory=lambda: _env("AGENTFORGE_GITHUB_APP_ID"))
    github_installation_id: str | None = field(default_factory=lambda: _env("AGENTFORGE_GITHUB_INSTALLATION_ID"))
    github_private_key_path: str | None = field(default_factory=lambda: _env("AGENTFORGE_GITHUB_PRIVATE_KEY_PATH"))
    github_api_base: str = field(default_factory=lambda: _env("AGENTFORGE_GITHUB_API_BASE", "https://api.github.com") or "https://api.github.com")
    github_api_version: str = field(default_factory=lambda: _env("AGENTFORGE_GITHUB_API_VERSION", "2026-03-10") or "2026-03-10")
    github_timeout: int = field(default_factory=lambda: _env_int("AGENTFORGE_GITHUB_TIMEOUT", 30))

    llm_base_url: str | None = field(default_factory=lambda: _env("AGENTFORGE_LLM_BASE_URL"))
    llm_api_key: str | None = field(default_factory=lambda: _env("AGENTFORGE_LLM_API_KEY"))
    llm_model: str | None = field(default_factory=lambda: _env("AGENTFORGE_LLM_MODEL"))

    def github_private_key(self) -> str:
        if not self.github_private_key_path:
            raise ValueError("AGENTFORGE_GITHUB_PRIVATE_KEY_PATH is not configured")
        path = Path(self.github_private_key_path)
        if not path.is_file():
            raise ValueError(f"GitHub private key file does not exist: {path}")
        return path.read_text(encoding="utf-8")

    def require_github_app(self) -> None:
        missing = [
            name
            for name, value in (
                ("AGENTFORGE_GITHUB_APP_ID", self.github_app_id),
                ("AGENTFORGE_GITHUB_INSTALLATION_ID", self.github_installation_id),
                ("AGENTFORGE_GITHUB_PRIVATE_KEY_PATH", self.github_private_key_path),
            )
            if not value
        ]
        if missing:
            raise ValueError("Missing GitHub App configuration: " + ", ".join(missing))

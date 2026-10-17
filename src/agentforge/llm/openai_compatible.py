from __future__ import annotations
import json
import time
from typing import Any
import httpx
from pydantic import ValidationError
from agentforge.llm.base import AgentDriver
from agentforge.models import AgentAction


class OpenAICompatibleDriver(AgentDriver):
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 180, retries: int = 2, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.retries = max(0, retries)
        self._client = client

    @staticmethod
    def _extract_json(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("LLM response did not contain a JSON object")
            value = json.loads(text[start:end + 1])
        if not isinstance(value, dict):
            raise ValueError("LLM response must be a JSON object")
        return value

    def execute(self, prompt: str, context: dict) -> AgentAction:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are an AgentForge constrained software agent. Return only valid AgentAction JSON. Never claim you executed tools."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                if self._client is not None:
                    response = self._client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                else:
                    with httpx.Client(timeout=self.timeout) as client:
                        response = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return AgentAction.model_validate(self._extract_json(content))
            except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(min(0.25 * (2 ** attempt), 1.0))
        raise RuntimeError(f"LLM request/response validation failed after {self.retries + 1} attempt(s): {last_error}") from last_error

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError


class LLMError(RuntimeError):
    pass


def _strip_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return value


def _schema_prompt(user: str, schema: type[BaseModel]) -> str:
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
    return (
        f"{user}\n\n"
        "Return exactly one JSON object that matches the JSON Schema below. "
        "All required fields must be present. Do not add Markdown, commentary, questions, or prose outside the JSON object. "
        "If the request does not provide a business fact, preserve that uncertainty inside an allowed string/list field instead of omitting required fields.\n"
        f"JSON Schema:\n{schema_json}"
    )


def _retry_feedback(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        payload = exc.errors(include_url=False, include_input=False)
        return json.dumps(payload, ensure_ascii=False, default=str)[:3000]
    if isinstance(exc, json.JSONDecodeError):
        return "The previous response was not valid JSON."
    return "The previous response could not be accepted. Return a fresh response that follows the JSON Schema exactly."


@dataclass(slots=True)
class OpenAICompatibleClient:
    base_url: str
    api_key: str
    model: str
    timeout: float = 30.0
    max_attempts: int = 3

    def _endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        return base if base.endswith("/chat/completions") else base + "/chat/completions"

    def _request(self, system: str, user: str) -> str:
        body = json.dumps({
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self._endpoint(), data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(f"LLM HTTP request failed: {exc}") from exc
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response is missing choices[0].message.content") from exc

    def complete_model(self, system: str, user: str, schema: type[BaseModel]) -> BaseModel:
        last_error: Exception | None = None
        base_user = _schema_prompt(user, schema)
        attempt_user = base_user
        for attempt in range(1, self.max_attempts + 1):
            try:
                raw = _strip_fence(self._request(system, attempt_user))
                data: Any = json.loads(raw)
                return schema.model_validate(data)
            except (LLMError, json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    if isinstance(exc, LLMError):
                        attempt_user = base_user
                    else:
                        feedback = _retry_feedback(exc)
                        attempt_user = (
                            f"{base_user}\n\n"
                            "The previous response failed strict validation. Correct the response and return the complete JSON object again.\n"
                            f"Validation feedback: {feedback}"
                        )
                    time.sleep(min(0.1 * attempt, 0.3))
        raise LLMError(f"LLM failed strict structured output after {self.max_attempts} attempts: {last_error}")

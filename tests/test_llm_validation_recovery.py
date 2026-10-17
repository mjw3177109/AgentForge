import json

import pytest
from pydantic import BaseModel, field_validator

from agentforge.llm import LLMError, OpenAICompatibleClient, _retry_feedback


class AgentActionFixture(BaseModel):
    status: str
    operations: list[str]

    @field_validator("operations")
    @classmethod
    def require_operation(cls, value):
        if not value:
            raise ValueError("SUCCESS action requires at least one operation")
        return value


def test_validation_feedback_serializes_value_error():
    with pytest.raises(Exception) as caught:
        AgentActionFixture.model_validate({"status": "SUCCESS", "operations": []})
    feedback = _retry_feedback(caught.value)
    assert "SUCCESS action requires at least one operation" in feedback
    assert isinstance(json.loads(feedback), list)


def test_invalid_success_is_retried_and_repaired(monkeypatch):
    responses = iter([
        '{"status":"SUCCESS","operations":[]}',
        '{"status":"SUCCESS","operations":["write_file"]}',
    ])
    prompts = []
    client = OpenAICompatibleClient("https://example.invalid", "test", "test", max_attempts=2)

    def fake_request(self, system, user):
        prompts.append(user)
        return next(responses)

    monkeypatch.setattr(OpenAICompatibleClient, "_request", fake_request)
    monkeypatch.setattr("agentforge.llm.time.sleep", lambda _: None)
    result = client.complete_model("system", "task", AgentActionFixture)
    assert result.operations == ["write_file"]
    assert len(prompts) == 2
    assert "Validation feedback:" in prompts[1]


def test_invalid_success_exhausts_retries_without_type_error(monkeypatch):
    client = OpenAICompatibleClient("https://example.invalid", "test", "test", max_attempts=2)
    monkeypatch.setattr(OpenAICompatibleClient, "_request", lambda self, system, user: '{"status":"SUCCESS","operations":[]}')
    monkeypatch.setattr("agentforge.llm.time.sleep", lambda _: None)
    with pytest.raises(LLMError, match="failed strict structured output"):
        client.complete_model("system", "task", AgentActionFixture)

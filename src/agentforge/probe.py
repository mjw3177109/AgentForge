from __future__ import annotations

from pydantic import BaseModel

from agentforge.llm import OpenAICompatibleClient


class ModelProbe(BaseModel):
    ok: bool
    message: str


def probe_model(client: OpenAICompatibleClient) -> ModelProbe:
    result = client.complete_model(
        system=(
            "You are the AgentForge external-model connectivity probe. "
            "Return JSON only with exactly two fields: ok=true and a short message."
        ),
        user="Confirm that strict structured JSON model output is working. Do not include secrets or environment data.",
        schema=ModelProbe,
    )
    if not isinstance(result, ModelProbe) or result.ok is not True:
        raise RuntimeError("External model probe did not return ok=true")
    return result

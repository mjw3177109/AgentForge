from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class RequirementDraft(BaseModel):
    id: str = Field(pattern=r"^REQ-[0-9]{6}$")
    title: str
    actors: list[str] = []
    modules: list[str] = []
    business_rules: list[str] = []
    acceptance: list[str] = Field(min_length=1)
    out_of_scope: list[str] = []


class ArchitectureDraft(BaseModel):
    id: str = Field(pattern=r"^ADR-[0-9]{6}$")
    requirement_ids: list[str] = Field(min_length=1)
    decision: dict[str, Any]
    evidence: list[str] = Field(min_length=1)


class TaskScope(BaseModel):
    read: list[str] = []
    write: list[str] = []
    deny: list[str] = []


class TaskDraft(BaseModel):
    id: str = Field(pattern=r"^TASK-[0-9]{6}$")
    requirement_ids: list[str] = Field(min_length=1)
    adr_ids: list[str] = []
    assigned_agent: str
    dependencies: list[str] = []
    scope: TaskScope
    acceptance: list[str] = Field(min_length=1)
    verification: list[str] = []


class TaskBundle(BaseModel):
    tasks: list[TaskDraft] = Field(min_length=1)

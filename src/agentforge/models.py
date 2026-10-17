from __future__ import annotations
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field, model_validator


class WriteFileOperation(BaseModel):
    type: Literal["write_file"]
    path: str
    content: str


class ReplaceTextOperation(BaseModel):
    type: Literal["replace_text"]
    path: str
    old: str
    new: str
    expected_replacements: int = 1


class DeleteFileOperation(BaseModel):
    type: Literal["delete_file"]
    path: str


FileOperation = Annotated[
    Union[WriteFileOperation, ReplaceTextOperation, DeleteFileOperation],
    Field(discriminator="type"),
]


class BlockInfo(BaseModel):
    type: str
    question: str
    affected_tasks: list[str] = []


class AgentAction(BaseModel):
    status: Literal["SUCCESS", "BLOCKED"]
    summary: str
    evidence: list[str] = []
    operations: list[FileOperation] = []
    block: BlockInfo | None = None

    @model_validator(mode="after")
    def validate_action(self):
        if self.status == "BLOCKED":
            if self.block is None:
                raise ValueError("BLOCKED action requires block information")
            if self.operations:
                raise ValueError("BLOCKED action cannot contain file operations")
        return self

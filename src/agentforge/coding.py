from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from agentforge.contracts import TaskDraft
from agentforge.evidence import EvidenceIndex
from agentforge.errors import EvidenceError, PolicyDenied
from agentforge.llm import OpenAICompatibleClient
from agentforge.policy import PolicyEngine, norm
from agentforge.workspace import SafeWorkspace


class FileOperation(BaseModel):
    op: Literal["write_text"]
    path: str = Field(min_length=1)
    content: str


class AgentAction(BaseModel):
    status: Literal["SUCCESS", "BLOCKED"]
    summary: str = ""
    evidence: list[str] = Field(default_factory=list)
    operations: list[FileOperation] = Field(default_factory=list)
    block_reason: str | None = None

    @model_validator(mode="after")
    def validate_action(self):
        if self.status == "SUCCESS":
            if not self.evidence:
                raise ValueError("SUCCESS action requires evidence")
            if not self.operations:
                raise ValueError("SUCCESS action requires at least one operation")
        if self.status == "BLOCKED" and self.operations:
            raise ValueError("BLOCKED action cannot contain file operations")
        return self


class VerificationSpec(BaseModel):
    argv: list[str] = Field(min_length=1)
    cwd: str = "."
    timeout_seconds: int = Field(default=60, ge=1, le=900)


class VerificationResult(BaseModel):
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    success: bool


class CodingResult(BaseModel):
    status: Literal["SUCCESS", "BLOCKED", "FAILED"]
    attempts: int
    actions: list[AgentAction]
    verification: list[VerificationResult] = Field(default_factory=list)
    message: str = ""


class TaskContextBuilder:
    def __init__(self, repo_root: Path, policy: PolicyEngine, max_file_chars: int = 20000):
        self.repo_root = repo_root.resolve()
        self.policy = policy
        self.max_file_chars = max_file_chars

    def build(self, task: TaskDraft, paths: list[str]) -> str:
        chunks = ["TASK:\n" + task.model_dump_json(indent=2)]
        seen: set[str] = set()
        for raw in paths:
            rel = norm(raw)
            if rel in seen:
                continue
            seen.add(rel)
            self.policy.require_read(rel)
            path = self.repo_root / rel
            if path.is_symlink():
                raise PolicyDenied(f"Context symlink denied: {rel}")
            if not path.exists():
                continue
            resolved = path.resolve()
            if resolved != self.repo_root and self.repo_root not in resolved.parents:
                raise PolicyDenied(f"Context path escapes repository: {rel}")
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")[: self.max_file_chars]
            chunks.append(f"FILE {rel}:\n{text}")
        return "\n\n".join(chunks)


def _verification_copy_ignore(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    base = Path(directory)
    for name in names:
        candidate = base / name
        if name in {".git", "__pycache__"} or name.endswith(".pyc") or candidate.is_symlink():
            ignored.add(name)
    return ignored


class VerificationRunner:
    def __init__(self, repo_root: Path, allowed_executables: set[str]):
        self.repo_root = repo_root.resolve()
        self.allowed_executables = set(allowed_executables)

    def run(self, specs: list[VerificationSpec]) -> list[VerificationResult]:
        for spec in specs:
            executable = Path(spec.argv[0]).name
            if executable not in self.allowed_executables:
                raise PolicyDenied(f"Verification executable denied: {executable}")
            norm(spec.cwd)

        results: list[VerificationResult] = []
        with tempfile.TemporaryDirectory(prefix="agentforge-verify-") as temp_dir:
            sandbox_root = Path(temp_dir) / "workspace"
            shutil.copytree(
                self.repo_root,
                sandbox_root,
                symlinks=False,
                ignore=_verification_copy_ignore,
            )
            for spec in specs:
                cwd_rel = norm(spec.cwd)
                cwd = (sandbox_root / cwd_rel).resolve()
                if cwd != sandbox_root and sandbox_root not in cwd.parents:
                    raise PolicyDenied(f"Verification cwd escapes sandbox: {spec.cwd}")
                if not cwd.is_dir():
                    raise PolicyDenied(f"Verification cwd does not exist: {spec.cwd}")
                completed = subprocess.run(
                    spec.argv,
                    cwd=cwd,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=spec.timeout_seconds,
                )
                results.append(VerificationResult(
                    argv=spec.argv,
                    returncode=completed.returncode,
                    stdout=completed.stdout[-12000:],
                    stderr=completed.stderr[-12000:],
                    success=completed.returncode == 0,
                ))
        return results


class LiveCodingRuntime:
    def __init__(
        self,
        client: OpenAICompatibleClient,
        repo_root: Path,
        allowed_verification_executables: set[str],
        max_attempts: int = 2,
    ):
        self.client = client
        self.repo_root = repo_root.resolve()
        self.max_attempts = max_attempts
        self.verifier = VerificationRunner(self.repo_root, allowed_verification_executables)

    @staticmethod
    def _policy(task: TaskDraft) -> PolicyEngine:
        return PolicyEngine(
            read=task.scope.read,
            write=task.scope.write,
            deny=task.scope.deny,
        )

    def _apply(self, task: TaskDraft, action: AgentAction) -> list[str]:
        EvidenceIndex(self.repo_root).build().require(action.evidence)
        policy = self._policy(task)
        workspace = SafeWorkspace(self.repo_root, policy)
        for operation in action.operations:
            workspace.preflight_write(operation.path)
        changed: list[str] = []
        for operation in action.operations:
            workspace.write_text(operation.path, operation.content)
            changed.append(norm(operation.path))
        return changed

    def execute(
        self,
        task: TaskDraft,
        context_paths: list[str],
        verification: list[VerificationSpec],
        initial_feedback: str = "",
    ) -> CodingResult:
        policy = self._policy(task)
        builder = TaskContextBuilder(self.repo_root, policy)
        active_paths = list(context_paths)
        actions: list[AgentAction] = []
        failure_feedback = initial_feedback
        latest_results: list[VerificationResult] = []

        for attempt in range(1, self.max_attempts + 1):
            context = builder.build(task, active_paths)
            evidence_ids = sorted(EvidenceIndex(self.repo_root).build().ids)
            context += (
                "\n\nAVAILABLE EVIDENCE IDS (evidence must contain ONLY exact IDs from this list; "
                "file paths are context, not evidence IDs):\n"
                + json_list(evidence_ids)
            )
            if failure_feedback:
                context += (
                    "\n\nREPAIR FEEDBACK FROM ORCHESTRATOR, REVIEWER, OR VERIFICATION. "
                    "Repair only the assigned task and stay inside its scope.\n"
                    + failure_feedback
                )
            action = self.client.complete_model(
                system=(
                    "You are a constrained coding agent. Return only JSON matching AgentAction. "
                    "You have no shell, git, network, or direct filesystem authority. "
                    "Only propose write_text operations inside the task write scope. "
                    "Every successful action must cite repository evidence IDs exactly from AVAILABLE EVIDENCE IDS. "
                    "Never use file paths, prose, or invented identifiers as evidence."
                ),
                user=context,
                schema=AgentAction,
            )
            actions.append(action)
            if action.status == "BLOCKED":
                return CodingResult(
                    status="BLOCKED",
                    attempts=attempt,
                    actions=actions,
                    message=action.block_reason or action.summary,
                )
            try:
                changed = self._apply(task, action)
            except (EvidenceError, PolicyDenied) as exc:
                failure_feedback = (
                    f"ACTION REJECTED BEFORE ANY FILE WRITE: {type(exc).__name__}: {exc}. "
                    "Use only the exact AVAILABLE EVIDENCE IDS and only paths allowed by the task write scope."
                )
                if attempt < self.max_attempts:
                    continue
                return CodingResult(
                    status="FAILED",
                    attempts=attempt,
                    actions=actions,
                    verification=latest_results,
                    message=failure_feedback,
                )
            active_paths.extend(changed)
            latest_results = self.verifier.run(verification)
            if all(result.success for result in latest_results):
                return CodingResult(
                    status="SUCCESS",
                    attempts=attempt,
                    actions=actions,
                    verification=latest_results,
                    message="All verification gates passed.",
                )
            failure_feedback = "\n".join(
                f"COMMAND: {result.argv}\nEXIT: {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
                for result in latest_results
                if not result.success
            )

        return CodingResult(
            status="FAILED",
            attempts=self.max_attempts,
            actions=actions,
            verification=latest_results,
            message="Verification still failing after repair attempts.",
        )


def json_list(values: list[str]) -> str:
    import json
    return json.dumps(values, ensure_ascii=False)
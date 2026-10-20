"""Read-only, fail-closed advisory preflight for changes against trusted V2 execution profiles.

An ALLOWED outcome only indicates that proposed paths appear within an existing
write policy. It is NEVER a signal of completed verification or merge safety.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agentforge.errors import PolicyDenied
from agentforge.policy import PolicyEngine, norm


@dataclass(frozen=True)
class ProposedChange:
    task_id: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class PreflightResult:
    status: str
    task_id: str
    agent: str
    findings: tuple[dict[str, str], ...]
    risk_level: str
    proposed_paths: tuple[str, ...]
    verification: str = "NOT_EXECUTED"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["findings"] = list(self.findings)
        data["proposed_paths"] = list(self.proposed_paths)
        return data


def _safe_relative_path(raw: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Path must be a nonempty string")
    raw = raw.replace("\\", "/")
    if any(segment in {"", ".", ".."} for segment in raw.split("/")):
        raise ValueError(f"Non-canonical or traversal path: {raw}")
    value = norm(raw)
    if value == "." or value.startswith("/"):
        raise ValueError(f"Invalid change target: {raw}")
    return value


def _symlink_in_chain(root: Path, rel: str) -> bool:
    cursor = root
    for part in rel.split("/"):
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


def _risk(path: str) -> str:
    tokens = set(path.lower().replace("-", "_").replace(".", "/").split("/"))
    if tokens & {"auth", "authentication", "permissions", "payment", "payments", "billing", "secrets", "migrations", "security", "deployment", "production"}:
        return "HIGH"
    if path.endswith((".sql", ".yml", ".yaml")) or "/config/" in f"/{path}/":
        return "MEDIUM"
    return "LOW"


def assess(*, repo_root: Path, task: ProposedChange, agent: str, trusted_profile: Any) -> PreflightResult:
    """Evaluate advisory risk against a profile loaded from a trusted file.

    Never accept task-provided scopes or executable lists. Caller supplies the
    trusted AgentExecutionProfile returned by load_execution_profiles().
    """
    root = repo_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Repository root must be a directory")
    if not task.task_id.startswith("TASK-") or not task.paths:
        raise ValueError("Task requires TASK-* id and one or more proposed paths")
    policy = PolicyEngine(
        read=trusted_profile.read_scope,
        write=trusted_profile.write_scope,
        deny=trusted_profile.deny_scope,
    )
    findings: list[dict[str, str]] = []
    normalized: list[str] = []
    risk_level = "LOW"
    ranking = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    for raw in task.paths:
        try:
            path = _safe_relative_path(raw)
            if _symlink_in_chain(root, path):
                raise ValueError(f"Symlink in target path: {path}")
            policy.require_write(path)
        except (PolicyDenied, ValueError) as exc:
            findings.append({"code": "SCOPE_OR_PATH_DENIED", "path": str(raw), "detail": str(exc)})
            continue
        normalized.append(path)
        level = _risk(path)
        if ranking[level] > ranking[risk_level]:
            risk_level = level
        if level == "HIGH":
            findings.append({"code": "HIGH_RISK_MANUAL_APPROVAL", "path": path, "detail": "Requires separate human authorization before execution"})
    if any(f["code"] == "SCOPE_OR_PATH_DENIED" for f in findings):
        status = "BLOCKED"
    elif risk_level == "HIGH":
        status = "MANUAL_REVIEW_REQUIRED"
    else:
        status = "SCOPE_PRECHECK_OK"
    return PreflightResult(
        status=status, task_id=task.task_id, agent=agent, findings=tuple(findings),
        risk_level=risk_level, proposed_paths=tuple(normalized),
    )

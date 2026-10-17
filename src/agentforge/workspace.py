from __future__ import annotations
from pathlib import Path
from agentforge.errors import AgentForgeError, PolicyDenied
from agentforge.models import AgentAction, DeleteFileOperation, ReplaceTextOperation, WriteFileOperation
from agentforge.policy import PolicyEngine, norm
from agentforge.util import ensure_within


class SafeWorkspace:
    def __init__(self, root: Path, policy: PolicyEngine):
        self.root = root.resolve()
        self.policy = policy

    def _target(self, rel: str) -> Path:
        rel = norm(rel)
        candidate = self.root / rel
        parent = candidate.parent
        parent.mkdir(parents=True, exist_ok=True)
        try:
            resolved_parent = ensure_within(self.root, parent)
        except ValueError as exc:
            raise PolicyDenied(f"Resolved path escapes repository: {rel}") from exc
        target = resolved_parent / candidate.name
        if target.exists() and target.is_symlink():
            raise PolicyDenied(f"Symlink target denied: {rel}")
        return target

    def write_text(self, rel: str, content: str) -> None:
        self.policy.require_write(rel)
        self._target(rel).write_text(content, encoding="utf-8")


class WorkspaceMutator:
    def __init__(self, root: Path, policy: PolicyEngine):
        self.root = root.resolve()
        self.policy = policy

    def _target(self, requested: str) -> tuple[Path, str]:
        normalized = norm(requested)
        try:
            target = ensure_within(self.root, self.root / normalized)
        except ValueError as exc:
            raise PolicyDenied(f"Path escapes repository: {requested}") from exc
        canonical = target.relative_to(self.root).as_posix()
        self.policy.require_write(canonical)
        if target.exists() and target.is_symlink():
            raise PolicyDenied(f"Symlink target denied: {canonical}")
        return target, canonical

    def apply(self, action: AgentAction) -> list[str]:
        changed: list[str] = []
        for op in action.operations:
            target, canonical = self._target(op.path)
            if isinstance(op, WriteFileOperation):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(op.content, encoding="utf-8")
            elif isinstance(op, ReplaceTextOperation):
                if not target.is_file():
                    raise AgentForgeError(f"replace_text target missing: {canonical}")
                text = target.read_text(encoding="utf-8")
                count = text.count(op.old)
                if count != op.expected_replacements:
                    raise AgentForgeError(f"replace_text expected {op.expected_replacements} occurrences in {canonical}, got {count}")
                target.write_text(text.replace(op.old, op.new), encoding="utf-8")
            elif isinstance(op, DeleteFileOperation):
                if target.exists():
                    target.unlink()
            changed.append(canonical)
        return changed

from pathlib import Path
from agentforge.errors import PolicyDenied
from agentforge.policy import PolicyEngine, norm


class SafeWorkspace:
    def __init__(self, root: Path, policy: PolicyEngine):
        self.root = root.resolve()
        self.policy = policy

    def preflight_write(self, rel: str) -> Path:
        self.policy.require_write(rel)
        rel = norm(rel)
        target = self.root / rel
        cursor = target.parent
        while cursor != self.root:
            if cursor.exists() and cursor.is_symlink():
                raise PolicyDenied(f"Symlink parent denied: {rel}")
            if self.root not in cursor.resolve(strict=False).parents and cursor.resolve(strict=False) != self.root:
                raise PolicyDenied(f"Resolved path escapes repository: {rel}")
            cursor = cursor.parent
        if target.exists() and target.is_symlink():
            raise PolicyDenied(f"Symlink target denied: {rel}")
        return target

    def _target(self, rel: str) -> Path:
        target = self.preflight_write(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = target.parent.resolve()
        if self.root != resolved_parent and self.root not in resolved_parent.parents:
            raise PolicyDenied(f"Resolved path escapes repository: {rel}")
        return target

    def write_text(self, rel: str, content: str) -> None:
        self._target(rel).write_text(content, encoding="utf-8")

    def delete_file(self, rel: str) -> None:
        target = self.preflight_write(rel)
        if not target.exists():
            raise PolicyDenied(f"Delete target does not exist: {norm(rel)}")
        if not target.is_file():
            raise PolicyDenied(f"Delete target is not a regular file: {norm(rel)}")
        target.unlink()

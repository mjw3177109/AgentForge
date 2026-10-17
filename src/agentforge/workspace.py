from pathlib import Path
from agentforge.errors import PolicyDenied
from agentforge.policy import PolicyEngine, norm

class SafeWorkspace:
    def __init__(self, root: Path, policy: PolicyEngine):
        self.root = root.resolve()
        self.policy = policy

    def _target(self, rel: str) -> Path:
        rel = norm(rel)
        target = self.root / rel
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = parent.resolve()
        if self.root != resolved_parent and self.root not in resolved_parent.parents:
            raise PolicyDenied(f"Resolved path escapes repository: {rel}")
        if target.exists() and target.is_symlink():
            raise PolicyDenied(f"Symlink target denied: {rel}")
        return target

    def write_text(self, rel: str, content: str) -> None:
        self.policy.require_write(rel)
        self._target(rel).write_text(content, encoding="utf-8")

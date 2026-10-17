from __future__ import annotations
from pathlib import PurePosixPath
import fnmatch
import posixpath
import re
from agentforge.errors import PolicyDenied

_DRIVE_RE = re.compile(r"^[A-Za-z]:/")


def norm(path: str) -> str:
    raw = str(path).replace("\\", "/").strip()
    if not raw:
        return "."
    if raw.startswith("/") or _DRIVE_RE.match(raw):
        raise PolicyDenied(f"Absolute paths are not allowed: {path}")
    normalized = posixpath.normpath(raw)
    if normalized == ".." or normalized.startswith("../"):
        raise PolicyDenied(f"Path escapes repository scope: {path}")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return str(PurePosixPath(normalized))


def matches(path: str, pattern: str) -> bool:
    try:
        path, pattern = norm(path), norm(pattern)
    except PolicyDenied:
        return False
    if pattern == "**":
        return True
    return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(path + "/", pattern)


class PolicyEngine:
    """Deny-first path policy.

    Direct mode keeps compatibility with the V1.3 safety core.
    Task+agent mode intersects task scope with agent capability, so neither side
    can grant itself broader access than the other.
    """

    def __init__(self, task: dict | None = None, agent: dict | None = None, *, read=None, write=None, deny=None):
        self.intersection = task is not None or agent is not None
        if self.intersection:
            task = task or {}
            agent = agent or {}
            ts = task.get("scope", {})
            ap = agent.get("permissions", {})
            self.read = list(ts.get("read", []))
            self.write = list(ts.get("write", []))
            self.agent_read = list(ap.get("read", []))
            self.agent_write = list(ap.get("write", []))
            self.deny = list(ts.get("deny", [])) + list(ap.get("deny", []))
        else:
            self.read = list(read or [])
            self.write = list(write or [])
            self.agent_read = ["**"]
            self.agent_write = ["**"]
            self.deny = list(deny or [])

    @staticmethod
    def _any(path: str, patterns: list[str]) -> bool:
        return any(matches(path, p) for p in patterns)

    def can_read(self, path: str) -> bool:
        try:
            path = norm(path)
        except PolicyDenied:
            return False
        if self._any(path, self.deny):
            return False
        return self._any(path, self.read) and self._any(path, self.agent_read)

    def can_write(self, path: str) -> bool:
        try:
            path = norm(path)
        except PolicyDenied:
            return False
        if self._any(path, self.deny):
            return False
        return self._any(path, self.write) and self._any(path, self.agent_write)

    def require_read(self, path: str) -> None:
        if not self.can_read(path):
            raise PolicyDenied(f"Read denied: {path}")

    def require_write(self, path: str) -> None:
        if not self.can_write(path):
            raise PolicyDenied(f"Write denied: {path}")

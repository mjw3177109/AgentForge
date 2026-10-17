import fnmatch
import posixpath
import re
from pathlib import PurePosixPath
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
    raw_pattern = str(pattern).replace("\\", "/").strip()
    directory_scope = raw_pattern.endswith("/") and raw_pattern != "/"
    try:
        path = norm(path)
        pattern = norm(raw_pattern)
    except PolicyDenied:
        return False
    if pattern == "**":
        return True
    if directory_scope:
        return path == pattern or fnmatch.fnmatchcase(path, pattern + "/**")
    return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(path + "/", pattern)


class PolicyEngine:
    def __init__(self, read=None, write=None, deny=None):
        self.read = read or []
        self.write = write or []
        self.deny = deny or []

    def _allowed(self, path: str, allowed: list[str]) -> bool:
        normalized = norm(path)
        if any(matches(normalized, p) for p in self.deny):
            return False
        return any(matches(normalized, p) for p in allowed)

    def require_read(self, path: str) -> None:
        if not self._allowed(path, self.read):
            raise PolicyDenied(f"Read denied: {path}")

    def require_write(self, path: str) -> None:
        if not self._allowed(path, self.write):
            raise PolicyDenied(f"Write denied: {path}")

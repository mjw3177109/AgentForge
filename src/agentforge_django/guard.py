"""Fail-closed boundaries. Python guards are NOT an OS/container security boundary."""

import os
import re
from pathlib import Path

from django.conf import settings


class BoundaryDenied(RuntimeError):
    pass


BLOCKED_SEGMENTS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    "site-packages", ".tox",
}
BLOCKED_FILES = {".env", "id_rsa", "id_ed25519", "secrets.json", "credentials.json"}
SAFE_GLOB = re.compile(r"^[A-Za-z0-9_.@/-]+(?:/\*\*)?$")


def checked_root(raw):
    if not raw or not Path(raw).is_absolute():
        raise BoundaryDenied("Project root must be an absolute path")
    root = Path(raw)
    if root.is_symlink() or not root.is_dir():
        raise BoundaryDenied("Project root must exist and must not be a symlink")
    root = root.resolve(strict=True)
    ceilings = getattr(settings, "AGENTFORGE_ALLOWED_ROOTS", ())
    if not ceilings:
        raise BoundaryDenied("AGENTFORGE_ALLOWED_ROOTS is empty (default deny)")
    permitted = False
    for entry in ceilings:
        base = Path(entry).resolve(strict=True)
        if root != base and base not in root.parents:
            continue
        permitted = True
        break
    if not permitted:
        raise BoundaryDenied("Project directory is outside configured allowlisted roots")
    if any(part in BLOCKED_SEGMENTS for part in root.parts):
        raise BoundaryDenied("Project root contains a blocked directory")
    return root


def safe_relative(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise BoundaryDenied("Unsafe relative path")
    path = Path(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise BoundaryDenied("Absolute/traversal paths are denied")
    if any(part in BLOCKED_SEGMENTS for part in path.parts):
        raise BoundaryDenied("Protected path segment")
    if path.name.lower() in BLOCKED_FILES or path.name.lower().startswith(".env"):
        raise BoundaryDenied("Secret-like file is protected")
    return value


def scoped_file(root, rel):
    safe_relative(rel)
    candidate = root / rel
    current = root
    for part in Path(rel).parts:
        current = current / part
        if current.is_symlink():
            raise BoundaryDenied("Symlink traversal is denied")
    resolved = candidate.resolve(strict=False)
    if root != resolved and root not in resolved.parents:
        raise BoundaryDenied("Path escapes project root")
    return candidate


def validate_write_scopes(scopes):
    if not isinstance(scopes, list) or not scopes:
        raise BoundaryDenied("Write scope must be a nonempty list")
    if len(scopes) > 32:
        raise BoundaryDenied("Too many write scopes")
    for value in scopes:
        if not isinstance(value, str) or not SAFE_GLOB.fullmatch(value):
            raise BoundaryDenied(f"Write scope is not a narrowly supported pattern: {value}")
        if value in ("*", "**", "**/*", ".") or value.startswith("/"):
            raise BoundaryDenied("Global write scope is forbidden")
        stem = value[:-3] if value.endswith("/**") else value
        safe_relative(stem)
        if stem in ("src", "app", "project"):
            # A whole top-level tree can be legitimate; admins must explicitly approve it.
            continue
    return list(scopes)


def scope_within(scope, approved):
    """Only exact matches or narrowed descendants of a trailing /** ceiling."""
    if scope in approved:
        return True
    if any(c in scope for c in "*?["):
        if not scope.endswith("/**") or scope.count("*") != 2:
            return False
        candidate = scope[:-3]
    else:
        candidate = scope
    for ceiling in approved:
        if ceiling.endswith("/**") and candidate.startswith(ceiling[:-3] + "/"):
            return True
    return False


def private_environment():
    """Remove inherited service credentials from untrusted test subprocesses."""
    allow = ("PATH", "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE", "TMP", "TEMP", "TMPDIR",
             "LANG", "LC_ALL", "VIRTUAL_ENV", "PYTHONPATH")
    return {key: value for key, value in os.environ.items() if key in allow}

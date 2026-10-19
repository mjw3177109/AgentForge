"""Static inspection: no imports of target project, no model/network execution."""

import ast
import os
from pathlib import Path

from .guard import BLOCKED_SEGMENTS, BLOCKED_FILES, BoundaryDenied, scoped_file


def inspect_python(root: Path, max_files=750, max_bytes=512_000):
    findings = []
    scanned = 0
    django_detected = (root / "manage.py").is_file() and not (root / "manage.py").is_symlink()
    for directory, subdirs, files in os.walk(root, followlinks=False):
        subdirs[:] = sorted(
            d for d in subdirs
            if d not in BLOCKED_SEGMENTS and not d.startswith(".")
            and not (Path(directory) / d).is_symlink()
        )
        for name in sorted(files):
            if scanned >= max_files:
                raise BoundaryDenied("Static scan limit reached; narrow the repository")
            if not name.endswith(".py") or name.lower() in BLOCKED_FILES:
                continue
            absolute = Path(directory) / name
            rel = absolute.relative_to(root).as_posix()
            try:
                scoped_file(root, rel)
                if absolute.stat().st_size > max_bytes:
                    findings.append({"path": rel, "code": "SKIPPED_SIZE"})
                    continue
                tree = ast.parse(absolute.read_text("utf-8"), filename=rel)
                scanned += 1
                if not isinstance(tree, ast.Module):
                    raise ValueError("Unexpected AST")
            except (SyntaxError, UnicodeDecodeError) as exc:
                findings.append({
                    "path": rel, "code": "PYTHON_PARSE_ERROR",
                    "message": str(exc)[:400],
                })
            except OSError as exc:
                findings.append({"path": rel, "code": "FILE_READ_ERROR",
                                 "message": str(exc)[:300]})
    return {"python_files": scanned, "django_detected": django_detected,
            "findings": findings, "static_pass": not any(
                f["code"] in ("PYTHON_PARSE_ERROR", "FILE_READ_ERROR") for f in findings
            )}


def sanitized_manifest(root: Path):
    data = inspect_python(root)
    return {
        "python_files": data["python_files"],
        "django_detected": data["django_detected"],
        "findings": data["findings"][:30],
    }

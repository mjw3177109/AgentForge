#!/usr/bin/env python3
"""Opt-in, branch-restricted integration of the V3 P2 safe repair runtime.

Default is dry run. Existing AgentForge files are changed only with --apply on
an isolated feature/v3-* or experiment/v3-* branch; refuses structural drift.
"""
from __future__ import annotations
import argparse
import difflib
import os
import stat
import subprocess
import tempfile
from pathlib import Path


def replace_once(text: str, before: str, after: str, where: str) -> str:
    if text.count(before) != 1:
        raise RuntimeError(f"{where} integration refused: expected one exact marker, found {text.count(before)}")
    return text.replace(before, after, 1)


def plan_integration(repo: Path) -> dict[Path, tuple[str, str]]:
    src = repo / "src/agentforge/autonomous.py"
    cli = repo / "src/agentforge/cli.py"
    for target in (src, cli):
        if target.is_symlink() or not target.is_file():
            raise RuntimeError(f"Refusing symlink or missing source: {target}")
    old_a = src.read_text("utf-8")
    old_c = cli.read_text("utf-8")
    if "enable_v3_safe_repair" in old_a or "--v3-safe-repair" in old_c:
        raise RuntimeError("Already integrated or partially integrated; do not apply again")
    a = replace_once(old_a,
        "from agentforge.coding import CodingResult, LiveCodingRuntime, VerificationSpec\n",
        "from agentforge.coding import CodingResult, LiveCodingRuntime, VerificationSpec\n"
        "from agentforge.repair_v3 import SafeRepairRuntime\n", "autonomous import")
    a = replace_once(a,
        "        max_review_rounds: int = 2,\n",
        "        max_review_rounds: int = 2,\n"
        "        enable_v3_safe_repair: bool = False,\n", "autonomous constructor")
    a = replace_once(a,
        "        self.max_review_rounds = max_review_rounds\n",
        "        self.max_review_rounds = max_review_rounds\n"
        "        self.enable_v3_safe_repair = enable_v3_safe_repair\n", "autonomous config")
    if a.count("runtime = LiveCodingRuntime(") != 2:
        raise RuntimeError("Expected exactly two V2 runtime construction sites")
    a = a.replace("runtime = LiveCodingRuntime(",
                  "runtime = (SafeRepairRuntime if self.enable_v3_safe_repair else LiveCodingRuntime)(")
    c = replace_once(old_c,
        "    live.add_argument(\"--create-pr\", action=\"store_true\")\n",
        "    live.add_argument(\"--create-pr\", action=\"store_true\")\n"
        "    live.add_argument(\"--v3-safe-repair\", action=\"store_true\",\n"
        "                      help=\"Enable opt-in P2 rollback and independent compile gates\")\n",
        "CLI flag")
    c = replace_once(c,
        "            allowed_verification_executables=loaded.allowed_executables,\n",
        "            allowed_verification_executables=loaded.allowed_executables,\n"
        "            enable_v3_safe_repair=args.v3_safe_repair,\n", "CLI constructor")
    return {src: (old_a, a), cli: (old_c, c)}


def verify_branch(repo: Path) -> str:
    def git(*args: str) -> str:
        p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
        if p.returncode:
            raise RuntimeError("Git repository check failed: " + p.stderr.strip())
        return p.stdout.strip()
    branch = git("branch", "--show-current")
    if not branch.startswith(("feature/v3-", "experiment/v3-")):
        raise RuntimeError(f"Refusing protected/non-V3 branch: {branch!r}")
    for rel in ["src/agentforge/autonomous.py", "src/agentforge/cli.py"]:
        if git("status", "--porcelain", "--", rel):
            raise RuntimeError(f"Refusing to overwrite local edits to {rel}")
    return branch


def install(changes: dict[Path, tuple[str, str]]) -> None:
    saved: list[tuple[Path, str]] = []
    try:
        for path, (before, after) in changes.items():
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                             prefix=".agentforge-v3-", delete=False) as stream:
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
                tmp = Path(stream.name)
            try:
                os.chmod(tmp, stat.S_IMODE(path.stat(follow_symlinks=False).st_mode))
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
            saved.append((path, before))
    except BaseException:
        for path, before in reversed(saved):
            path.write_text(before, encoding="utf-8")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--apply", action="store_true", help="Actually modify two existing files")
    args = parser.parse_args()
    repo = Path(args.repo_root).resolve()
    branch = verify_branch(repo)
    if not (repo / "src/agentforge/repair_v3.py").is_file():
        parser.error("Install this P2 ZIP before enabling the integration")
    changes = plan_integration(repo)
    for file, (before, after) in changes.items():
        print("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                           fromfile=str(file.relative_to(repo)),
                                           tofile=str(file.relative_to(repo)) + " (P2)")))
    if args.apply:
        install(changes)
    print(f"{'APPLIED' if args.apply else 'DRY RUN'} P2 opt-in on {branch}; "
          "default behavior remains V2. --v3-safe-repair opts in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

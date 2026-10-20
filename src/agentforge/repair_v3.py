"""AgentForge V3 P2: opt-in scoped verification and rollback for coding repairs.

This module never expands a task's scopes, runs shell commands, publishes PRs,
or relaxes independent verification. The trusted existing runtime stays in charge
of all generated operations, authorization and verification execution.

Threat model: a clean, isolated task worktree with no concurrent writers. We check
for unexpected file changes before restoration and fail closed on conflicts; this
is not a substitute for OS isolation or a cross-process filesystem lock.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from agentforge.coding import (
    AgentAction, CodingResult, LiveCodingRuntime, VerificationResult, VerificationSpec,
)
from agentforge.contracts import TaskDraft
from agentforge.errors import EvidenceError, PolicyDenied
from agentforge.policy import PolicyEngine, norm
from agentforge.workspace import SafeWorkspace


class RepairSafetyStop(RuntimeError):
    """Failure cannot safely be repaired automatically."""


class RollbackConflict(RepairSafetyStop):
    """A file no longer matches the expected state; preserve it and stop."""


@dataclass(frozen=True)
class Diagnosis:
    category: str
    retryable: bool
    guidance: str
    fingerprint: str


_HINTS: tuple[tuple[str, re.Pattern[str], bool, str], ...] = (
    ("JAVA_TYPE_ERROR", re.compile(
        r"incompatible types|cannot be converted to|cannot find symbol|symbol:\s+method",
        re.I), True,
     "Re-check declared Java return types, Optional handling, overloads and imports "
     "against the existing code; verify with the authorized Maven compile/test gate."),
    ("JAVA_COMPILATION", re.compile(
        r"COMPILATION ERROR|\[ERROR\].*\.java:\[\d+|maven-compiler-plugin",
        re.I), True,
     "Repair the concrete Java compiler diagnostics within this TASK's existing write scope."),
    ("NODE_BUILD", re.compile(r"vite.*build|npm ERR!|error TS\d{4}", re.I), True,
     "Resolve the stated build/type error within the authorized source paths."),
    ("TEST_ASSERTION", re.compile(r"AssertionError|FAILED\s+\S+::|Tests run:.*Failures: [1-9]", re.I), True,
     "Fix the behavior established by the independent test without editing protected tests."),
    ("TIMEOUT", re.compile(r"timed out|timeout expired", re.I), False,
     "Environment timeout: stop automatic code repair and request environment diagnosis."),
    ("ENVIRONMENT", re.compile(r"command not found|No such file or directory|connection refused|Verification runner failed", re.I), False,
     "Missing executable or dependency: do not rewrite application code to conceal the environment problem."),
)


def diagnose_verification(results: Iterable[VerificationResult]) -> Diagnosis:
    """Classify failed independent checks, never grant write rights or weaken gates."""
    failures = [item for item in results if not item.success]
    if not failures:
        return Diagnosis("NONE", False, "No failed check to diagnose.", "none")
    merged = "\n".join((r.stderr + "\n" + r.stdout)[-6000:] for r in failures)[-12000:]
    # Permission problems and forbidden test paths must never become repair prompts.
    if re.search(r"PolicyDenied|outside write.scope|write scope denied|permission denied|"
                 r"server/src/test/.*(outside|denied)|VERIFICATION_SCOPE_GAP", merged, re.I):
        category, retryable, guidance = (
            "VERIFICATION_SCOPE_GAP", False,
            "Stop: this is an authorization/evidence ownership issue, not a coding repair task."
        )
    else:
        category, retryable, guidance = (
            "UNCLASSIFIED_VERIFICATION", True,
            "Inspect only the provided verification failure and repair within existing task scope."
        )
        for label, pattern, may_retry, hint in _HINTS:
            if pattern.search(merged):
                category, retryable, guidance = label, may_retry, hint
                break
    canonical = re.sub(r"\b\d{4,}\b", "<N>", merged.lower())
    canonical = re.sub(r"\s+", " ", canonical).strip()
    fingerprint = hashlib.sha256((category + "\0" + canonical[:2500]).encode()).hexdigest()[:20]
    return Diagnosis(category, retryable, guidance, fingerprint)


@dataclass(frozen=True)
class _FileState:
    existed: bool
    data: bytes | None
    mode: int | None
    expected_data: bytes | None


class ScopedChangeJournal:
    """Capture only explicitly authorized paths, then restore on failed checks.

    Restore is optimistic: if any target has been altered by an external actor,
    stop rather than clobber an unrecognized state. The implementation preflights
    all targets before modifying anything and refuses hardlinks.
    """

    def __init__(self, root: Path, policy: PolicyEngine, action: AgentAction):
        self.root = root.resolve()
        self.workspace = SafeWorkspace(self.root, policy)
        self.entries: dict[str, _FileState] = {}
        if not action.operations:
            raise RepairSafetyStop("P2 requires at least one file operation")
        for op in action.operations:
            rel = norm(op.path)
            if rel in self.entries:
                raise RepairSafetyStop(f"Duplicate file operation denied: {rel}")
            target = self.workspace.preflight_write(rel)
            if op.op == "delete_file" or target.exists():
                # Rollback must not read a write-only preimage.
                policy.require_read(rel)
            if target.is_symlink():
                raise RepairSafetyStop(f"Symlink mutation denied: {rel}")
            if target.exists():
                if not target.is_file():
                    raise RepairSafetyStop(f"Non-regular target denied: {rel}")
                metadata = target.stat(follow_symlinks=False)
                if metadata.st_nlink != 1:
                    raise RepairSafetyStop(f"Hardlink target denied: {rel}")
                old_data = target.read_bytes()
                mode = stat.S_IMODE(metadata.st_mode)
                existed = True
            else:
                old_data, mode, existed = None, None, False
                if op.op == "delete_file":
                    raise RepairSafetyStop(f"Delete target missing: {rel}")
            expected = op.content.encode("utf-8") if op.op == "write_text" and op.content is not None else None
            self.entries[rel] = _FileState(existed, old_data, mode, expected)
        self.closed = False

    def _state(self, target: Path) -> tuple[bool, bytes | None]:
        if target.is_symlink():
            raise RollbackConflict("Rollback target turned into a symlink")
        if not target.exists():
            return False, None
        if not target.is_file() or target.stat(follow_symlinks=False).st_nlink != 1:
            raise RollbackConflict("Rollback target is not an unlinked regular file")
        return True, target.read_bytes()

    def restore(self) -> None:
        if self.closed:
            return
        # Phase 1: validate EVERY path before writing ANY path.
        changed = []
        for rel, old in self.entries.items():
            target = self.workspace.preflight_write(rel)
            exists, current = self._state(target)
            originally = old.existed and exists and current == old.data
            applied = (exists == (old.expected_data is not None)
                       and current == old.expected_data)
            if not (originally or applied or (not old.existed and not exists)):
                raise RollbackConflict(f"Rollback conflict on {rel}: unexpected third-party content")
            if not originally and not (not old.existed and not exists):
                changed.append((rel, target, old))
        # Phase 2: after preflight, restore only affected allowlisted paths.
        for rel, target, old in changed:
            self.workspace.preflight_write(rel)
            if old.existed:
                assert old.data is not None
                # Restore at the *already authorized* target pathname. An
                # extra temporary sibling would be outside an exact-file write
                # scope, so we deliberately don't create one. A crash during
                # restoration can still leave partial data; fail closed.
                flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(target, flags, old.mode or 0o600)
                try:
                    st = os.fstat(fd)
                    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                        raise RollbackConflict(f"Rollback target changed type: {rel}")
                    os.ftruncate(fd, 0)
                    with os.fdopen(fd, "wb", closefd=False) as out:
                        out.write(old.data)
                        out.flush()
                    os.fsync(fd)
                    if old.mode is not None:
                        os.fchmod(fd, old.mode)
                finally:
                    os.close(fd)
            else:
                target.unlink()
        self.closed = True

    def commit(self) -> None:
        self.closed = True


class _SafeVerificationAdapter:
    def __init__(self, owner: "SafeRepairRuntime", delegate):
        self.owner = owner
        self.delegate = delegate

    def run(self, specs: list[VerificationSpec]) -> list[VerificationResult]:
        try:
            results = self.delegate.run(specs)
        except Exception as exc:
            # No false PASS on missing tools, timeouts, exceptions or malformed results.
            results = [VerificationResult(
                argv=spec.argv, returncode=127, stdout="",
                stderr=f"Verification runner failed: {type(exc).__name__}: {str(exc)[:700]}",
                success=False,
            ) for spec in specs]
        if not results:
            results = [VerificationResult(
                argv=["<verification-runner>"], returncode=2, stdout="",
                stderr="Independent verification returned no results; empty checks are not PASS.",
                success=False,
            )]
        if (len(results) != len(specs) or any(
            r.argv != s.argv or r.success != (r.returncode == 0)
            for r, s in zip(results, specs)
        )):
            results = list(results) + [VerificationResult(
                argv=["<verification-coverage>"], returncode=2, stdout="",
                stderr="VERIFICATION_SCOPE_GAP: independent verifier did not return one consistent "
                       "result for each authorized verification spec.", success=False,
            )]
        self.owner._latest_results = list(results)
        if all(r.success for r in results):
            if self.owner._pending is not None:
                self.owner._pending.commit()
                self.owner._pending = None
            return results
        diagnosis = diagnose_verification(results)
        self.owner.diagnoses.append(diagnosis)
        if self.owner._pending is not None:
            self.owner._pending.restore()  # RollbackConflict intentionally propagates.
            self.owner._pending = None
        # The base engine places failed results into the NEXT repair prompt.
        # Clearly label the hint; do not rewrite the actual independent verdict.
        for result in results:
            if not result.success:
                result.stderr = (result.stderr[-10500:] +
                    "\n[P2 VERIFIED FAILURE CLASSIFICATION] " + diagnosis.category +
                    "; fingerprint=" + diagnosis.fingerprint +
                    "; guidance=" + diagnosis.guidance +
                    "\n[SAFETY] Previous candidate was rolled back; task scope/verification remain unchanged.")
                break
        if not diagnosis.retryable:
            raise RepairSafetyStop(
                f"{diagnosis.category}: {diagnosis.guidance} (fingerprint {diagnosis.fingerprint})"
            )
        return results


class SafeRepairRuntime(LiveCodingRuntime):
    """Opt-in P2 runtime. Existing V2 runtime and all defaults stay untouched."""

    def __init__(self, *args, max_attempts: int = 2, **kwargs):
        if not 1 <= max_attempts <= 2:
            raise ValueError("P2 max_attempts must be 1 or 2 (plus existing reviewer allowance)")
        super().__init__(*args, max_attempts=max_attempts, **kwargs)
        self._original_verifier = self.verifier
        self.verifier = _SafeVerificationAdapter(self, self._original_verifier)
        self._pending: ScopedChangeJournal | None = None
        self._specs: list[VerificationSpec] = []
        self.diagnoses: list[Diagnosis] = []
        self._observed_actions: list[AgentAction] = []
        self._latest_results: list[VerificationResult] = []
        self._attempts_seen = 0

    @staticmethod
    def _java_build_gate(specs: list[VerificationSpec]) -> bool:
        accepted = {"compile", "test", "package", "verify", "install"}
        for spec in specs:
            if Path(spec.argv[0]).name.lower() in {"mvn", "mvn.cmd", "mvnw", "mvnw.cmd"}:
                if accepted.intersection(spec.argv[1:]):
                    return True
        return False

    def _apply(self, task: TaskDraft, action: AgentAction) -> list[str]:
        self._observed_actions.append(action)
        self._attempts_seen += 1
        if not self._specs:
            raise RepairSafetyStop("P2 requires explicit independent verification specs")
        if any(op.path.lower().endswith(".java") for op in action.operations):
            if not self._java_build_gate(self._specs):
                raise RepairSafetyStop(
                    "JAVA_VERIFICATION_GAP: Java source edits require an authorized Maven compile/test gate"
                )
        policy = self._policy(task)
        journal = ScopedChangeJournal(self.repo_root, policy, action)
        self._pending = journal
        try:
            changed = super()._apply(task, action)
            return changed
        except BaseException:
            # Base runtime may have applied a subset of multi-file operations.
            try:
                journal.restore()
            finally:
                self._pending = None
            raise

    def execute(self, task: TaskDraft, context_paths: list[str],
                verification: list[VerificationSpec], initial_feedback: str = "") -> CodingResult:
        if self._pending is not None:
            raise RepairSafetyStop("Previous task transaction still active")
        self._specs = list(verification)
        self.diagnoses = []
        self._observed_actions = []
        self._latest_results = []
        self._attempts_seen = 0
        if not verification:
            return CodingResult(status="BLOCKED", attempts=0, actions=[],
                                message="VERIFICATION_SCOPE_GAP: P2 refuses zero independent checks")
        # Critical: no scope expansion and no external commands added here.
        feedback = (initial_feedback + "\n" if initial_feedback else "") + (
            "P2 SAFE REPAIR MODE: all candidate writes must stay within existing task scopes. "
            "A failed independent check rolls back the candidate. "
            "Compiler errors must be repaired by checking declared source types, not guessed defaults. "
            "Do not modify verification fixtures outside the task's scope."
        )
        # Feeding mode prose as initial_feedback would grant an extra reviewer attempt in the
        # base runtime. ONLY carry it when review feedback already existed.
        if not initial_feedback:
            feedback = ""
        try:
            return super().execute(task, context_paths, verification, initial_feedback=feedback)
        except (RepairSafetyStop, RollbackConflict) as exc:
            # Preserve uncertain files; never make a second destructive rollback attempt.
            self._pending = None
            return CodingResult(status="BLOCKED", attempts=self._attempts_seen,
                                actions=self._observed_actions, verification=self._latest_results,
                message=f"P2 SAFETY STOP: {exc}")
        except (PolicyDenied, EvidenceError) as exc:
            self._pending = None
            return CodingResult(status="BLOCKED", attempts=self._attempts_seen,
                                actions=self._observed_actions, verification=self._latest_results,
                message=f"P2 AUTHORIZATION STOP: {exc}")
        except OSError as exc:
            self._pending = None
            return CodingResult(status="BLOCKED", attempts=self._attempts_seen,
                                actions=self._observed_actions, verification=self._latest_results,
                                message=f"P2 FILESYSTEM STOP: {type(exc).__name__}: {str(exc)[:700]}")
        finally:
            self._specs = []
            if self._pending is not None:
                # Should only occur for an exceptional exit; restore unless a third-party
                # conflict makes rollback unsafe, in which case the exception is surfaced.
                self._pending.restore()
                self._pending = None

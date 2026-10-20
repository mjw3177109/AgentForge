"""P2 regression tests: classification, path-safety, rollback and opt-in runtime.

Run against actual AgentForge in repository. These tests do not contact an LLM.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentforge.coding import AgentAction, VerificationResult, VerificationSpec
from agentforge.contracts import TaskDraft, TaskScope
from agentforge.errors import PolicyDenied
from agentforge.policy import PolicyEngine
from agentforge.repair_v3 import (
    RepairSafetyStop, RollbackConflict, SafeRepairRuntime, ScopedChangeJournal,
    diagnose_verification,
)


def _action(path: str, content: str | None = "fresh\n", op: str = "write_text"):
    if op == "write_text":
        return AgentAction(status="SUCCESS", evidence=["REQ-000001"],
                           operations=[{"op": "write_text", "path": path, "content": content}])
    return AgentAction(status="SUCCESS", evidence=["REQ-000001"],
                       operations=[{"op": "delete_file", "path": path}])


def _policy():
    return PolicyEngine(read=["app/**"], write=["app/**"], deny=["app/protected/**"])


def _failure(stderr: str, argv: list[str] | None = None):
    return VerificationResult(argv=argv or ["mvn", "test"], returncode=1,
                              stdout="", stderr=stderr, success=False)


@pytest.mark.parametrize("details,classification,retry", [
    ("PointsService.java:[93,19] incompatible types: java.util.Optional<java.lang.Long> cannot be converted to long", "JAVA_TYPE_ERROR", True),
    ("[ERROR] COMPILATION ERROR", "JAVA_COMPILATION", True),
    ("vite build failed", "NODE_BUILD", True),
    ("AssertionError: expected exactly once", "TEST_ASSERTION", True),
    ("Backend denied JUnit tests in server/src/test/** outside write scope", "VERIFICATION_SCOPE_GAP", False),
    ("connection refused", "ENVIRONMENT", False),
    ("command timed out", "TIMEOUT", False),
])
def test_diagnoses_are_bounded_and_specific(details, classification, retry):
    got = diagnose_verification([_failure(details)])
    assert got.category == classification
    assert got.retryable is retry
    assert len(got.fingerprint) == 20
    assert got.fingerprint == diagnose_verification([_failure(details)]).fingerprint


def test_journal_restores_existing_file_after_failed_verification(tmp_path):
    root = tmp_path
    target = root / "app/PointsService.java"
    target.parent.mkdir()
    target.write_text("old\n", encoding="utf-8")
    journal = ScopedChangeJournal(root, _policy(), _action("app/PointsService.java", "bad\n"))
    target.write_text("bad\n", encoding="utf-8")
    journal.restore()
    assert target.read_text("utf-8") == "old\n"


def test_journal_removes_new_file(tmp_path):
    root = tmp_path
    (root / "app").mkdir()
    journal = ScopedChangeJournal(root, _policy(), _action("app/new.py", "bad\n"))
    target = root / "app/new.py"
    target.write_text("bad\n")
    journal.restore()
    assert not target.exists()


def test_journal_restores_deleted_file(tmp_path):
    root = tmp_path
    target = root / "app/obsolete.py"
    target.parent.mkdir()
    target.write_bytes(b"original\xff\n")
    journal = ScopedChangeJournal(root, _policy(), _action("app/obsolete.py", op="delete_file"))
    target.unlink()
    journal.restore()
    assert target.read_bytes() == b"original\xff\n"


def test_journal_preserves_other_files(tmp_path):
    root = tmp_path
    (root / "app").mkdir()
    (root / "app/one.py").write_text("a")
    (root / "app/two.py").write_text("b")
    journal = ScopedChangeJournal(root, _policy(), _action("app/one.py", "x"))
    (root / "app/one.py").write_text("x")
    (root / "app/two.py").write_text("external")
    journal.restore()
    assert (root / "app/one.py").read_text() == "a"
    assert (root / "app/two.py").read_text() == "external"


def test_conflicting_third_party_edit_is_not_overwritten(tmp_path):
    root = tmp_path
    path = root / "app/source.py"
    path.parent.mkdir()
    path.write_text("old")
    journal = ScopedChangeJournal(root, _policy(), _action("app/source.py", "agent"))
    path.write_text("external")
    with pytest.raises(RollbackConflict):
        journal.restore()
    assert path.read_text() == "external"


def test_conflict_preflight_is_all_or_nothing(tmp_path):
    root = tmp_path
    (root / "app").mkdir()
    one, two = root / "app/one.py", root / "app/two.py"
    one.write_text("old1")
    two.write_text("old2")
    both = AgentAction(status="SUCCESS", evidence=["REQ-000001"], operations=[
        {"op":"write_text", "path":"app/one.py", "content":"agent1"},
        {"op":"write_text", "path":"app/two.py", "content":"agent2"},
    ])
    j = ScopedChangeJournal(root, _policy(), both)
    one.write_text("agent1")
    two.write_text("outside")
    with pytest.raises(RollbackConflict):
        j.restore()
    assert one.read_text() == "agent1"


@pytest.mark.parametrize("bad_path", ["../escape.txt", "app/protected/key.txt", "/tmp/escape.txt"])
def test_scope_escape_denied(tmp_path, bad_path):
    with pytest.raises((PolicyDenied, RepairSafetyStop)):
        ScopedChangeJournal(tmp_path, _policy(), _action(bad_path))


def test_symlink_denied(tmp_path):
    external = tmp_path / "external.txt"
    external.write_text("KEEP")
    (tmp_path / "app").mkdir()
    (tmp_path / "app/link.py").symlink_to(external)
    with pytest.raises((PolicyDenied, RepairSafetyStop)):
        ScopedChangeJournal(tmp_path, _policy(), _action("app/link.py"))
    assert external.read_text() == "KEEP"


def test_hardlink_denied(tmp_path):
    ext = tmp_path / "external.txt"
    ext.write_text("KEEP")
    (tmp_path / "app").mkdir()
    os.link(ext, tmp_path / "app/alias.py")
    with pytest.raises(RepairSafetyStop, match="Hardlink"):
        ScopedChangeJournal(tmp_path, _policy(), _action("app/alias.py"))
    assert ext.read_text() == "KEEP"


def test_no_reads_of_write_only_existing_files(tmp_path):
    target = tmp_path / "app/secret.txt"
    target.parent.mkdir()
    target.write_text("secret")
    policy = PolicyEngine(read=[], write=["app/**"])
    with pytest.raises(PolicyDenied):
        ScopedChangeJournal(tmp_path, policy, _action("app/secret.txt", "new"))
    assert target.read_text() == "secret"


def test_duplicate_ops_rejected_before_write(tmp_path):
    action = AgentAction(status="SUCCESS", evidence=["REQ-000001"], operations=[
        {"op": "write_text", "path": "app/a.py", "content": "1"},
        {"op": "write_text", "path": "app/a.py", "content": "2"},
    ])
    with pytest.raises(RepairSafetyStop, match="Duplicate"):
        ScopedChangeJournal(tmp_path, _policy(), action)


def _task():
    return TaskDraft(id="TASK-000101", requirement_ids=["REQ-000001"], adr_ids=[],
                     assigned_agent="backend", dependencies=[],
                     scope=TaskScope(read=["app/**"], write=["app/**"], deny=[]),
                     acceptance=["file must pass verification"], verification=["pytest"])


class FakeClient:
    def __init__(self, actions):
        self.actions = list(actions)
        self.requests = []

    def complete_model(self, system, user, schema):
        self.requests.append(user)
        return self.actions.pop(0)


class RecordingVerifier:
    def __init__(self, results):
        self.results = list(results)

    def run(self, specs):
        return self.results.pop(0)


def _repo(tmp_path):
    root = tmp_path / "repo"
    (root / ".agent/requirements").mkdir(parents=True)
    (root / ".agent/requirements/REQ-000001.yaml").write_text("id: REQ-000001\n")
    (root / "app").mkdir()
    return root


def test_p2_repairs_bad_java_type_then_passes_maven(tmp_path):
    root = _repo(tmp_path)
    target = root / "app/PointsService.java"
    target.write_text("class PointsService {}\n")
    client = FakeClient([_action("app/PointsService.java", "long balance = repository.findBalance(userId);"),
                         _action("app/PointsService.java", "Long balance = repository.findBalance(userId).orElseThrow();")])
    runtime = SafeRepairRuntime(client, root, {"mvn"}, max_attempts=2)
    runtime.verifier.delegate = RecordingVerifier([
        [_failure("PointsService.java:93: incompatible types: Optional<Long> cannot be converted to long")],
        [VerificationResult(argv=["mvn", "test"], returncode=0, stdout="OK", stderr="", success=True)],
    ])
    result = runtime.execute(_task(), [], [VerificationSpec(argv=["mvn", "test"])])
    assert result.status == "SUCCESS"
    assert result.attempts == 2
    assert "orElseThrow" in target.read_text()
    assert "JAVA_TYPE_ERROR" in client.requests[1]
    assert runtime.diagnoses[0].category == "JAVA_TYPE_ERROR"


def test_p2_failed_repairs_restore_original_and_exhaust_budget(tmp_path):
    root = _repo(tmp_path)
    file = root / "app/source.py"
    file.write_text("original\n")
    runtime = SafeRepairRuntime(FakeClient([_action("app/source.py", "bad1"),
                                           _action("app/source.py", "bad2")]),
                                root, {"python"}, max_attempts=2)
    runtime.verifier.delegate = RecordingVerifier([[_failure("AssertionError", ["python", "--version"])], [_failure("AssertionError", ["python", "--version"])]])
    result = runtime.execute(_task(), [], [VerificationSpec(argv=["python", "--version"])])
    assert result.status == "FAILED"
    assert result.attempts == 2
    assert file.read_text() == "original\n"


def test_p2_does_not_retry_permissions_as_codegen(tmp_path):
    root = _repo(tmp_path)
    runtime = SafeRepairRuntime(FakeClient([_action("app/no.py", "x")]), root, {"python"})
    runtime.verifier.delegate = RecordingVerifier([[_failure("VERIFICATION_SCOPE_GAP: tests outside write scope", ["python", "--version"])]])
    result = runtime.execute(_task(), [], [VerificationSpec(argv=["python", "--version"])])
    assert result.status == "BLOCKED"
    assert not (root / "app/no.py").exists()


def test_p2_requires_independent_verification_before_model_call(tmp_path):
    root = _repo(tmp_path)
    client = FakeClient([_action("app/no.py")])
    runtime = SafeRepairRuntime(client, root, set())
    result = runtime.execute(_task(), [], [])
    assert result.status == "BLOCKED"
    assert client.requests == []
    assert not (root / "app/no.py").exists()


def test_p2_blocks_java_edit_without_authorized_maven_gate(tmp_path):
    root = _repo(tmp_path)
    client = FakeClient([_action("app/PointsService.java", "class X {}")])
    runtime = SafeRepairRuntime(client, root, {"node"})
    result = runtime.execute(_task(), [], [VerificationSpec(argv=["node", "--version"])])
    assert result.status == "BLOCKED"
    assert not (root / "app/PointsService.java").exists()


def test_p2_does_not_extend_review_retry_budget(tmp_path):
    root = _repo(tmp_path)
    client = FakeClient([_action("app/x.py", "bad1"), _action("app/x.py", "bad2"),
                         _action("app/x.py", "good")])
    runtime = SafeRepairRuntime(client, root, {"python"})
    runtime.verifier.delegate = RecordingVerifier([
        [_failure("AssertionError", ["python", "-m", "pytest"])], [_failure("AssertionError", ["python", "-m", "pytest"])],
        [VerificationResult(argv=["python", "-m", "pytest"], returncode=0,
                            stdout="", stderr="", success=True)],
    ])
    result = runtime.execute(_task(), [], [VerificationSpec(argv=["python", "-m", "pytest"])],
                             initial_feedback="READ-ONLY REVIEWER REQUESTED CHANGES")
    assert result.status == "SUCCESS"
    assert result.attempts == 3
    assert len(client.requests) == 3


def test_bad_budget_never_allowed(tmp_path):
    root = _repo(tmp_path)
    with pytest.raises(ValueError, match="max_attempts"):
        SafeRepairRuntime(FakeClient([]), root, set(), max_attempts=10)


def test_p2_refuses_partial_or_fake_verifier_results(tmp_path):
    root = _repo(tmp_path)
    runtime = SafeRepairRuntime(FakeClient([_action("app/suspicious.py", "x")]), root,
                                {"python"}, max_attempts=1)
    runtime.verifier.delegate = RecordingVerifier([[
        VerificationResult(argv=["python", "--version"], returncode=0,
                           stdout="success", stderr="", success=True)
    ]])
    # Two specs, only one returned: cannot be PASS even though that one is green.
    result = runtime.execute(_task(), [], [VerificationSpec(argv=["python", "--version"]),
                                                VerificationSpec(argv=["python", "-m", "pytest"])])
    assert result.status == "BLOCKED"
    assert "VERIFICATION_SCOPE_GAP" in result.message
    assert not (root / "app/suspicious.py").exists()
    assert result.actions and result.verification


def test_p2_verifier_exception_rolls_back_and_blocks(tmp_path):
    root = _repo(tmp_path)
    path = root / "app/changed.py"
    path.write_text("before\n")
    runtime = SafeRepairRuntime(FakeClient([_action("app/changed.py", "bad\n")]), root,
                                {"python"}, max_attempts=1)
    class BrokenVerifier:
        def run(self, specs):
            raise OSError("No such file or directory: python")
    runtime.verifier.delegate = BrokenVerifier()
    result = runtime.execute(_task(), [], [VerificationSpec(argv=["python", "--version"])])
    assert result.status == "BLOCKED"
    assert path.read_text() == "before\n"
    assert runtime.diagnoses and runtime.diagnoses[0].category == "ENVIRONMENT"


def test_real_v20_deepseek_round01_maven_failure_classified():
    fixture = Path(__file__).resolve().parent / "fixtures/v20_run_39103687560_round01_maven.log"
    raw = fixture.read_text("utf-8")
    result = diagnose_verification([_failure(raw)])
    assert "PointsService.java:[93,52]" in raw
    assert result.category == "JAVA_TYPE_ERROR"
    assert result.retryable is True


def test_p2_restoration_never_creates_temp_sibling_outside_exact_file_scope(tmp_path):
    root = tmp_path
    path = root / "app/source.py"
    path.parent.mkdir()
    path.write_text("old\n")
    exact = PolicyEngine(read=["app/source.py"], write=["app/source.py"], deny=[])
    journal = ScopedChangeJournal(root, exact, _action("app/source.py", "candidate\n"))
    path.write_text("candidate\n")
    journal.restore()
    assert path.read_text() == "old\n"
    assert sorted(p.name for p in path.parent.iterdir()) == ["source.py"]


def test_partial_write_error_rolls_back_and_returns_blocked(tmp_path, monkeypatch):
    from agentforge.coding import LiveCodingRuntime
    from agentforge.workspace import SafeWorkspace
    root = _repo(tmp_path)
    file = root / "app/unchanged.py"
    file.write_text("baseline\n")
    action = AgentAction(status="SUCCESS", evidence=["REQ-000001"], operations=[
        {"op": "write_text", "path": "app/unchanged.py", "content": "temporary\n"},
        {"op": "write_text", "path": "app/new.py", "content": "bad\n"},
    ])
    def broken_apply(self, task, action):
        SafeWorkspace(self.repo_root, self._policy(task)).write_text(
            action.operations[0].path, action.operations[0].content)
        raise OSError("Simulated mid-transaction disk fault")
    monkeypatch.setattr(LiveCodingRuntime, "_apply", broken_apply)
    runtime = SafeRepairRuntime(FakeClient([action]), root, {"python"}, max_attempts=1)
    result = runtime.execute(_task(), [], [VerificationSpec(argv=["python", "--version"])])
    assert result.status == "BLOCKED"
    assert "FILESYSTEM STOP" in result.message
    assert file.read_text() == "baseline\n"
    assert not (root / "app/new.py").exists()

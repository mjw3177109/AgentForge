from pathlib import Path
from types import SimpleNamespace

import pytest

from agentforge.governance import ProposedChange, assess


def _profile():
    return SimpleNamespace(read_scope=["server/**"], write_scope=["server/src/main/**"], deny_scope=["server/src/main/secrets/**"])


def _eval(tmp_path: Path, *paths: str):
    return assess(repo_root=tmp_path, task=ProposedChange("TASK-900001", tuple(paths)), agent="backend", trusted_profile=_profile())


def test_writable_source_is_precheck_only(tmp_path):
    r = _eval(tmp_path, "server/src/main/java/PointsService.java")
    assert r.status == "SCOPE_PRECHECK_OK"
    assert r.verification == "NOT_EXECUTED"


def test_forbidden_junit_test_is_blocked(tmp_path):
    r = _eval(tmp_path, "server/src/test/java/PointsServiceTest.java")
    assert r.status == "BLOCKED"
    assert r.findings[0]["code"] == "SCOPE_OR_PATH_DENIED"


def test_unauthorized_scope_override_unavailable(tmp_path):
    r = _eval(tmp_path, "server/src/main/secrets/key.txt")
    assert r.status == "BLOCKED"


@pytest.mark.parametrize("unsafe", ["../outside", "server/src/main/../test/File.java", "/tmp/root.txt", "C:/secrets", "server//src/main/A.java"])
def test_path_traversal_and_noncanonical_block(tmp_path, unsafe):
    assert _eval(tmp_path, unsafe).status == "BLOCKED"


def test_symlink_target_blocked(tmp_path):
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "src").symlink_to(tmp_path, target_is_directory=True)
    assert _eval(tmp_path, "server/src/main/A.java").status == "BLOCKED"


def test_high_risk_requires_manual_approval(tmp_path):
    r = _eval(tmp_path, "server/src/main/auth/CurrentUserProvider.java")
    assert r.status == "MANUAL_REVIEW_REQUIRED"
    assert r.risk_level == "HIGH"


def test_unauthorized_path_always_blocks_even_if_other_path_allowed(tmp_path):
    r = _eval(tmp_path, "server/src/main/java/A.java", "server/src/test/java/B.java")
    assert r.status == "BLOCKED"


def test_empty_manifest_fails_closed(tmp_path):
    with pytest.raises(ValueError):
        _eval(tmp_path)

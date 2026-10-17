from pathlib import Path
import pytest

from agentforge.errors import PolicyDenied
from agentforge.policy import PolicyEngine
from agentforge.workspace import SafeWorkspace


def test_preflight_blocks_parent_symlink(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "app").symlink_to(outside, target_is_directory=True)
    ws = SafeWorkspace(repo, PolicyEngine(read=["**"], write=["app/**"], deny=[]))
    with pytest.raises(PolicyDenied):
        ws.preflight_write("app/pwn.txt")
    assert not (outside / "pwn.txt").exists()

from pathlib import Path
import subprocess
import pytest
from agentforge.errors import VerificationError
from agentforge.sandbox import DockerSandbox
from agentforge.verification import VerificationRunner


def test_builtin_file_exists(tmp_path: Path):
    (tmp_path / "x.txt").write_text("ok")
    policy = {"checks": {"x": {"type": "file_exists", "path": "x.txt"}}}
    result = VerificationRunner(tmp_path, policy).run(["x"])
    assert result[0]["returncode"] == 0


def test_host_command_is_disabled_by_default(tmp_path: Path):
    policy = {"checks": {"x": {"type": "host_command", "command": ["python", "-c", "print(1)"]}}}
    with pytest.raises(VerificationError):
        VerificationRunner(tmp_path, policy).run(["x"])


def test_docker_sandbox_cannot_mutate_live_worktree(tmp_path: Path, monkeypatch):
    (tmp_path / "source.txt").write_text("original", encoding="utf-8")

    def fake_run(argv, text, capture_output, timeout):
        mount = argv[argv.index("-v") + 1]
        sandbox_path = Path(mount.split(":/workspace", 1)[0])
        (sandbox_path / "source.txt").write_text("mutated", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = DockerSandbox(tmp_path).run("fake:image", ["true"])
    assert result["returncode"] == 0
    assert (tmp_path / "source.txt").read_text(encoding="utf-8") == "original"

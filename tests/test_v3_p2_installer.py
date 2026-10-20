"""Offline tests for the opt-in integration installer; never touches the real repo."""
from __future__ import annotations
import importlib.util
import subprocess
from pathlib import Path
import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/v3_p2_integrate.py"
_SPEC = importlib.util.spec_from_file_location("v3_p2_integrate", _SCRIPT)
assert _SPEC and _SPEC.loader
installer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(installer)


@pytest.fixture
def fake_repo(tmp_path):
    root = tmp_path / "forge"
    (root / "src/agentforge").mkdir(parents=True)
    (root / "src/agentforge/autonomous.py").write_text('''from agentforge.coding import CodingResult, LiveCodingRuntime, VerificationSpec

class AutonomousDevelopmentPipeline:
    def __init__(self,
        max_review_rounds: int = 2,
    ):
        self.max_review_rounds = max_review_rounds

    def run(self):
        runtime = LiveCodingRuntime(
            None,
        )
        runtime = LiveCodingRuntime(
            None,
        )
''')
    (root / "src/agentforge/cli.py").write_text('''def main():
    live.add_argument("--create-pr", action="store_true")
    pipeline = AutonomousDevelopmentPipeline(
            allowed_verification_executables=loaded.allowed_executables,
    )
''')
    subprocess.run(["git", "init", "-q", root], check=True)
    subprocess.run(["git", "-C", root, "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", root, "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", root, "add", "."], check=True)
    subprocess.run(["git", "-C", root, "commit", "-qm", "baseline"], check=True)
    subprocess.run(["git", "-C", root, "checkout", "-qb", "feature/v3-p2"], check=True)
    (root / "src/agentforge/repair_v3.py").write_text("# opt in\n")
    return root


def test_installer_exactly_two_existing_files_change(fake_repo):
    assert installer.verify_branch(fake_repo) == "feature/v3-p2"
    edits = installer.plan_integration(fake_repo)
    assert {p.name for p in edits} == {"autonomous.py", "cli.py"}
    assert all(a != b for a, b in edits.values())
    installer.install(edits)
    actual = (fake_repo / "src/agentforge/autonomous.py").read_text()
    cli = (fake_repo / "src/agentforge/cli.py").read_text()
    assert "enable_v3_safe_repair: bool = False" in actual
    assert actual.count("SafeRepairRuntime if self.enable_v3_safe_repair") == 2
    assert '--v3-safe-repair' in cli
    with pytest.raises(RuntimeError, match="Already integrated"):
        installer.plan_integration(fake_repo)


def test_installer_is_dry_run_by_default(fake_repo):
    before = (fake_repo / "src/agentforge/autonomous.py").read_bytes()
    proc = subprocess.run(["python", str(_SCRIPT), "--repo-root", str(fake_repo)],
                          text=True, capture_output=True)
    assert proc.returncode == 0 and "DRY RUN" in proc.stdout
    assert (fake_repo / "src/agentforge/autonomous.py").read_bytes() == before


def test_installer_refuses_protected_branch(fake_repo):
    subprocess.run(["git", "-C", fake_repo, "checkout", "-qb", "main"], check=True)
    with pytest.raises(RuntimeError, match="Refusing"):
        installer.verify_branch(fake_repo)


def test_installer_refuses_dirty_target_files(fake_repo):
    source = fake_repo / "src/agentforge/cli.py"
    source.write_text(source.read_text() + "# unsaved user changes\n")
    with pytest.raises(RuntimeError, match="local edits"):
        installer.verify_branch(fake_repo)


def test_installer_refuses_structural_drift(fake_repo):
    source = fake_repo / "src/agentforge/autonomous.py"
    source.write_text(source.read_text().replace("runtime = LiveCodingRuntime(", "runtime = OtherRuntime("))
    with pytest.raises(RuntimeError, match="two V2 runtime"):
        installer.plan_integration(fake_repo)


def test_installer_preserves_source_file_modes(fake_repo):
    import stat
    cli = fake_repo / "src/agentforge/cli.py"
    cli.chmod(0o644)
    installer.install(installer.plan_integration(fake_repo))
    assert stat.S_IMODE(cli.stat().st_mode) == 0o644

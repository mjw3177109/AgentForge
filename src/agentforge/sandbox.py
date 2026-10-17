from __future__ import annotations
from pathlib import Path
import shutil
import subprocess
import tempfile
from agentforge.errors import VerificationError


class DockerSandbox:
    """Run verification against a disposable repository copy.

    The live task worktree is never mounted directly. Network is disabled by
    default, Linux capabilities are dropped, and no host Docker socket is
    exposed.
    """

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()

    def run(
        self,
        image: str,
        command: list[str],
        cwd: str = ".",
        timeout: int = 300,
        network: bool = False,
    ) -> dict:
        if not image:
            raise VerificationError("docker_command requires image")
        with tempfile.TemporaryDirectory(prefix="agentforge-verify-") as td:
            sandbox_root = Path(td) / "workspace"
            shutil.copytree(
                self.repo_root,
                sandbox_root,
                symlinks=True,
                ignore=shutil.ignore_patterns(".git", ".agentforge-worktrees", ".agentforge-features"),
            )
            argv = [
                "docker", "run", "--rm",
                "--security-opt", "no-new-privileges",
                "--cap-drop", "ALL",
                "-v", f"{sandbox_root}:/workspace",
                "-w", str(Path("/workspace") / cwd),
            ]
            if not network:
                argv += ["--network", "none"]
            argv += [image, *command]
            try:
                proc = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
            except FileNotFoundError as exc:
                raise VerificationError("Docker is required for docker_command verification") from exc
            except subprocess.TimeoutExpired as exc:
                raise VerificationError(f"Sandbox verification timed out after {timeout}s") from exc
            return {
                "returncode": proc.returncode,
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-4000:],
            }

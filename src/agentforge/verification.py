from __future__ import annotations
from pathlib import Path
import subprocess
from agentforge.errors import VerificationError
from agentforge.sandbox import DockerSandbox
from agentforge.util import ensure_within


class VerificationRunner:
    def __init__(self, repo_root: Path, policy: dict, unsafe_allow_host: bool = False):
        self.repo_root = repo_root.resolve()
        self.checks = policy.get("checks", {})
        self.unsafe_allow_host = unsafe_allow_host
        self.sandbox = DockerSandbox(self.repo_root)

    def _builtin(self, name: str, spec: dict) -> dict:
        kind = spec.get("type")
        rel = spec.get("path", "")
        try:
            target = ensure_within(self.repo_root, self.repo_root / rel)
        except ValueError as exc:
            raise VerificationError(f"Verification path escapes repository: {rel}") from exc
        if kind == "file_exists":
            ok = target.is_file()
        elif kind == "directory_exists":
            ok = target.is_dir()
        else:
            raise VerificationError(f"Unknown builtin verification type: {kind}")
        return {
            "name": name,
            "returncode": 0 if ok else 1,
            "stdout": f"{kind} {rel}: {ok}",
            "stderr": "" if ok else f"Missing {rel}",
        }

    def run(self, names: list[str]) -> list[dict]:
        results: list[dict] = []
        for name in names:
            spec = self.checks.get(name)
            if not spec:
                raise VerificationError(f"Undefined verification check: {name}")
            kind = spec.get("type", "docker_command")
            if kind in {"file_exists", "directory_exists"}:
                result = self._builtin(name, spec)
            elif kind == "docker_command":
                command = spec.get("command")
                if not isinstance(command, list) or not command:
                    raise VerificationError(f"Verification command must be argv list: {name}")
                raw = self.sandbox.run(
                    image=spec.get("image", ""),
                    command=command,
                    cwd=spec.get("cwd", "."),
                    timeout=int(spec.get("timeout", 300)),
                    network=bool(spec.get("network", False)),
                )
                result = {"name": name, **raw}
            elif kind == "host_command":
                if not self.unsafe_allow_host:
                    raise VerificationError("host_command is disabled; use docker_command or builtin checks")
                command = spec.get("command")
                if not isinstance(command, list) or not command:
                    raise VerificationError(f"Verification command must be argv list: {name}")
                try:
                    cwd = ensure_within(self.repo_root, self.repo_root / spec.get("cwd", "."))
                except ValueError as exc:
                    raise VerificationError("Verification cwd escapes repository") from exc
                proc = subprocess.run(
                    command,
                    cwd=cwd,
                    text=True,
                    capture_output=True,
                    timeout=int(spec.get("timeout", 300)),
                )
                result = {
                    "name": name,
                    "returncode": proc.returncode,
                    "stdout": proc.stdout[-4000:],
                    "stderr": proc.stderr[-4000:],
                }
            else:
                raise VerificationError(f"Unsupported verification type: {kind}")
            results.append(result)
            if result["returncode"] != 0:
                raise VerificationError(f"Verification failed: {name}\n{result['stderr'][-2000:]}")
        return results

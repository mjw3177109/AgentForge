from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from agentforge.autonomous import AgentExecutionProfile
from agentforge.coding import VerificationSpec


_FORBIDDEN_EXECUTABLES = {
    "bash", "sh", "zsh", "fish", "cmd", "cmd.exe", "powershell", "pwsh", "python -c"
}


@dataclass(frozen=True, slots=True)
class LoadedExecutionProfiles:
    profiles: dict[str, AgentExecutionProfile]
    allowed_executables: set[str]


def _string_list(raw: dict, key: str, agent: str) -> list[str]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{agent}.{key} must be a list of non-empty strings")
    return value


def load_execution_profiles(path: Path) -> LoadedExecutionProfiles:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Execution profile file must contain a mapping")

    allowed = data.get("allowed_verification_executables", [])
    if not isinstance(allowed, list) or not all(isinstance(item, str) and item.strip() for item in allowed):
        raise ValueError("allowed_verification_executables must be a list of executable names")
    allowed_set = {Path(item).name for item in allowed}
    if allowed_set & _FORBIDDEN_EXECUTABLES:
        raise ValueError("Shell interpreters are forbidden as verification executables")

    raw_agents = data.get("agents", {})
    if not isinstance(raw_agents, dict) or not raw_agents:
        raise ValueError("Execution profile file must define at least one agent")

    profiles: dict[str, AgentExecutionProfile] = {}
    for agent, raw in raw_agents.items():
        if not isinstance(agent, str) or not isinstance(raw, dict):
            raise ValueError("Each agent profile must be a mapping")
        context_paths = _string_list(raw, "context_paths", agent)
        read_scope = _string_list(raw, "read_scope", agent)
        write_scope = _string_list(raw, "write_scope", agent)
        deny_scope = _string_list(raw, "deny_scope", agent)
        raw_verification = raw.get("verification", [])
        if not isinstance(raw_verification, list):
            raise ValueError(f"{agent}.verification must be a list")

        specs: list[VerificationSpec] = []
        for item in raw_verification:
            if not isinstance(item, dict):
                raise ValueError(f"{agent}.verification entries must be mappings")
            spec = VerificationSpec.model_validate(item)
            executable = Path(spec.argv[0]).name
            if executable in _FORBIDDEN_EXECUTABLES:
                raise ValueError(f"Shell interpreter denied for {agent}: {executable}")
            if executable not in allowed_set:
                raise ValueError(f"Verification executable not allowlisted for {agent}: {executable}")
            specs.append(spec)

        profiles[agent] = AgentExecutionProfile(
            context_paths=context_paths,
            verification=specs,
            read_scope=read_scope,
            write_scope=write_scope,
            deny_scope=deny_scope,
        )

    return LoadedExecutionProfiles(profiles=profiles, allowed_executables=allowed_set)

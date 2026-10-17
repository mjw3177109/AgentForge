from agentforge.errors import StateTransitionError

TASK_TRANSITIONS = {
    "PENDING": {"READY", "CANCELLED"},
    "READY": {"RUNNING", "BLOCKED", "CANCELLED"},
    "RUNNING": {"VERIFYING", "BLOCKED", "FAILED"},
    "VERIFYING": {"DONE", "FAILED", "BLOCKED"},
    "BLOCKED": {"READY", "CANCELLED"},
    "FAILED": {"READY", "CANCELLED"},
    "DONE": set(),
    "CANCELLED": set(),
}

class TaskStateMachine:
    @staticmethod
    def require(old: str, new: str) -> None:
        if new not in TASK_TRANSITIONS.get(old, set()):
            raise StateTransitionError(f"Illegal task state transition: {old} -> {new}")

"""Offline deterministic role responses for REAL Docker benchmark CI only."""
from .v11_benchmark import SCENARIOS


CORRECTED = {
    "arith-001": "def add(a, b):\n    return a + b\n",
    "pricing-002": (
        "def final_price(cents, percent):\n"
        "    return cents * (100 - percent) // 100\n"
    ),
    "access-003": (
        "def may_read(actor_id, owner_id, is_staff=False):\n"
        "    return actor_id is not None and (actor_id == owner_id or is_staff)\n"
    ),
}
INCORRECT = {
    "arith-001": "def add(a, b):\n    return a * b\n",
    "pricing-002": (
        "def final_price(cents, percent):\n"
        "    return cents - cents * percent // 100\n"
    ),
    "access-003": (
        "def may_read(actor_id, owner_id, is_staff=False):\n"
        "    return actor_id == owner_id or is_staff\n"
    ),
}


class FakeScenarioAgent:
    def __init__(self, scenario):
        if scenario not in SCENARIOS:
            raise ValueError("Unrecognized synthetic scenario")
        self.scenario = scenario
        self.calls = 0

    def complete_model(self, system, user, schema):
        self.calls += 1
        if schema.__name__ == "CodingPlan":
            obj = {
                "summary": "Limit all candidate changes to the permitted function implementation.",
                "files": [self.scenario.target_path],
                "acceptance": "All original independent Django business cases must pass.",
            }
        elif schema.__name__ == "CodingProposal":
            content = (CORRECTED if "Fixer" in system else INCORRECT)[
                self.scenario.identifier
            ]
            obj = {
                "summary": "Change one allowlisted module without touching any business tests.",
                "edits": [{"path": self.scenario.target_path, "content": content}],
            }
        else:
            obj = {
                "decision": "APPROVE",
                "reason": "Single allowlisted source change, no test or configuration changes.",
            }
        return schema.model_validate(obj)

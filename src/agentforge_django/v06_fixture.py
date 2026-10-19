"""Deterministic V0.6 synthetic role outputs, NOT a real-model acceptance."""

from .v05_fixture import REQUEST, make_fixture


class FakeRepairModel:
    def __init__(self, *, fail_after_repair=False, second_review="APPROVE"):
        self.calls = 0
        self.fail_after_repair = fail_after_repair
        self.second_review = second_review
        self._reviews = 0

    def complete_model(self, system, user, schema):
        self.calls += 1
        role = schema.__name__
        if role == "CodingPlan":
            result = {
                "summary": "Repair the addition arithmetic in a single source module.",
                "files": ["app/views.py"],
                "acceptance": "Existing Django addition behavioral tests must succeed."
            }
        elif role == "CodingProposal":
            fixer = "Fixer" in system
            expr = "a - b" if (not fixer or self.fail_after_repair) else "a + b"
            # Initial attempt must change the file without satisfying the test.
            if not fixer:
                expr = "a * b"
            result = {
                "summary": "Candidate file replacement restricted to arithmetic routine.",
                "edits": [{"path": "app/views.py", "content":
                           "def add(a, b):\n    return " + expr + "\n"}],
            }
        else:
            self._reviews += 1
            result = {
                "decision": self.second_review if self._reviews > 1 else "APPROVE",
                "reason": "The proposed edits stay within approved Python source paths.",
            }
        return schema.model_validate(result)

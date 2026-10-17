from pathlib import Path

path = Path("tests/test_autonomous_pipeline.py")
text = path.read_text(encoding="utf-8")
old = '''        result = pipeline.run(
            "exercise per-task review repair budgets",
            base_branch="main",
            feature_branch="feature/REQ-910001-review-budget",
        )
'''
new = '''        result = pipeline.run(
            "exercise per-task review repair budgets",
            base_branch="main",
            requirement_id="REQ-910001",
            adr_id="ADR-910001",
            feature_branch="feature/REQ-910001-review-budget",
        )
'''
if text.count(old) != 1:
    raise RuntimeError(f"expected one late-review run invocation, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

autonomous_path = Path("src/agentforge/autonomous.py")
autonomous_text = autonomous_path.read_text(encoding="utf-8")
old_message = '''                    message=(
                        f"review cycle {review_cycle + 1}, task repair attempt "
                        f"{repair_attempt}/{self.max_review_rounds}: {result.message}"
                    ),
'''
new_message = '''                    message=(
                        f"review repair round {review_cycle + 1}, task attempt "
                        f"{repair_attempt}/{self.max_review_rounds}: {result.message}"
                    ),
'''
if autonomous_text.count(old_message) != 1:
    raise RuntimeError(
        f"expected one generated review message block, found {autonomous_text.count(old_message)}"
    )
autonomous_path.write_text(
    autonomous_text.replace(old_message, new_message, 1),
    encoding="utf-8",
)

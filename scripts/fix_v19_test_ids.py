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

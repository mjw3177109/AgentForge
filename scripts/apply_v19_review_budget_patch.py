from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


root = Path(__file__).resolve().parents[1]
autonomous_path = root / "src/agentforge/autonomous.py"
tests_path = root / "tests/test_autonomous_pipeline.py"

text = autonomous_path.read_text(encoding="utf-8")

text = replace_once(
    text,
    '''            "For REQUEST_CHANGES, include every affected TASK id in evidence so the orchestrator can route repairs. "
            "Do not use file paths or prose in evidence. Existing unchanged files may not appear in DIFF; do not claim they are absent solely because they are not in DIFF.\\n\\n"
''',
    '''            "For REQUEST_CHANGES, include every affected TASK id in evidence so the orchestrator can route repairs. "
            "Evaluate all currently identifiable material defects across all tasks in this review; do not intentionally defer known defects to later review cycles. "
            "Requested changes must stay within the requirement, ADR, VERIFIED contracts, and VERIFIED project context; do not invent endpoints, identity sources, or integration facts. "
            "Do not use file paths or prose in evidence. Existing unchanged files may not appear in DIFF; do not claim they are absent solely because they are not in DIFF.\\n\\n"
''',
    "review completeness prompt",
)

text = replace_once(
    text,
    '''        review: ReviewDecision | None = None
        for review_round in range(self.max_review_rounds + 1):
''',
    '''        review: ReviewDecision | None = None
        review_cycle = 0
        repair_counts = {task.id: 0 for task in ordered_tasks}
        while True:
''',
    "review loop header",
)

text = replace_once(
    text,
    '''            if review_round >= self.max_review_rounds:
                return AutonomousResult(
                    status="REVIEW_CHANGES",
                    requirement_id=plan.requirement.id,
                    adr_id=plan.architecture.id,
                    feature_branch=branch,
                    task_runs=task_runs,
                    review=review,
                    message=review.summary,
                )

            affected_ids = [item for item in review.evidence if item.startswith("TASK-")]
''',
    '''            affected_ids = [item for item in review.evidence if item.startswith("TASK-")]
''',
    "remove global terminal review budget",
)

text = replace_once(
    text,
    '''            if not affected_ids:
                return AutonomousResult(
                    status="REVIEW_CHANGES",
                    requirement_id=plan.requirement.id,
                    adr_id=plan.architecture.id,
                    feature_branch=branch,
                    task_runs=task_runs,
                    review=review,
                    message="Reviewer requested changes without routable TASK evidence.",
                )

            for task in ordered_tasks:
                if task.id not in affected_ids:
                    continue
''',
    '''            if not affected_ids:
                return AutonomousResult(
                    status="REVIEW_CHANGES",
                    requirement_id=plan.requirement.id,
                    adr_id=plan.architecture.id,
                    feature_branch=branch,
                    task_runs=task_runs,
                    review=review,
                    message="Reviewer requested changes without routable TASK evidence.",
                )

            repairable_ids = [
                task_id
                for task_id in affected_ids
                if task_id in task_by_id and repair_counts[task_id] < self.max_review_rounds
            ]
            if not repairable_ids:
                return AutonomousResult(
                    status="REVIEW_CHANGES",
                    requirement_id=plan.requirement.id,
                    adr_id=plan.architecture.id,
                    feature_branch=branch,
                    task_runs=task_runs,
                    review=review,
                    message=(
                        "Reviewer still requests changes after all affected tasks exhausted "
                        f"their per-task repair budget: {review.summary}"
                    ),
                )

            for task in ordered_tasks:
                if task.id not in repairable_ids:
                    continue
                repair_attempt = repair_counts[task.id] + 1
''',
    "per-task repair budget routing",
)

text = replace_once(
    text,
    '''                    initial_feedback=(
                        f"READ-ONLY REVIEWER REQUESTED CHANGES IN REVIEW ROUND {review_round + 1}:\\n"
                        f"{review.summary}\\n\\n"
                        f"Repair only {task.id}. Do not change files outside this task's scope."
                    ),
''',
    '''                    initial_feedback=(
                        f"READ-ONLY REVIEWER REQUESTED CHANGES IN REVIEW CYCLE {review_cycle + 1}; "
                        f"TASK REPAIR ATTEMPT {repair_attempt}/{self.max_review_rounds}:\\n"
                        f"{review.summary}\\n\\n"
                        f"Repair only {task.id}. Do not change files outside this task's scope."
                    ),
''',
    "repair feedback counters",
)

text = replace_once(
    text,
    '''                    message=f"review repair round {review_round + 1}: {result.message}",
''',
    '''                    message=(
                        f"review cycle {review_cycle + 1}, task repair attempt "
                        f"{repair_attempt}/{self.max_review_rounds}: {result.message}"
                    ),
''',
    "repair record message",
)

text = replace_once(
    text,
    '''                record.commit = git.commit_all(
                    f"fix({task.assigned_agent}): review repair {task.id} round {review_round + 1}"
                )
                task_runs.append(record)

        if review is None or review.status != "APPROVE":
''',
    '''                record.commit = git.commit_all(
                    f"fix({task.assigned_agent}): review repair {task.id} attempt {repair_attempt}"
                )
                task_runs.append(record)
                repair_counts[task.id] = repair_attempt

            review_cycle += 1

        if review is None or review.status != "APPROVE":
''',
    "increment per-task repair budget",
)

autonomous_path.write_text(text, encoding="utf-8")


test = r'''


def test_late_discovered_task_gets_its_own_repair_budget(tmp_path):
    repo, _ = make_git_repo(tmp_path)
    responses = [
        {
            "id": "REQ-910001",
            "title": "late review repair budget",
            "actors": ["USER"],
            "modules": ["backend", "admin"],
            "business_rules": ["both tasks must converge"],
            "acceptance": ["late-discovered admin issue can still be repaired"],
            "out_of_scope": [],
        },
        {
            "id": "ADR-910001",
            "requirement_ids": ["REQ-910001"],
            "decision": {
                "backend": {"change_required": True},
                "admin": {"change_required": True},
            },
            "evidence": ["REQ-910001"],
        },
        {
            "tasks": [
                {
                    "id": "TASK-910101",
                    "requirement_ids": ["REQ-910001"],
                    "adr_ids": ["ADR-910001"],
                    "assigned_agent": "backend",
                    "dependencies": [],
                    "scope": {"read": ["app/**"], "write": ["app/**"], "deny": [".agent/**"]},
                    "acceptance": ["backend converges"],
                    "verification": [],
                },
                {
                    "id": "TASK-910102",
                    "requirement_ids": ["REQ-910001"],
                    "adr_ids": ["ADR-910001"],
                    "assigned_agent": "admin",
                    "dependencies": ["TASK-910101"],
                    "scope": {"read": ["app/**"], "write": ["app/**"], "deny": [".agent/**"]},
                    "acceptance": ["admin converges"],
                    "verification": [],
                },
            ]
        },
        {
            "status": "SUCCESS",
            "summary": "initial backend",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910101"],
            "operations": [{"op": "write_text", "path": "app/backend.txt", "content": "backend-v0\n"}],
        },
        {
            "status": "SUCCESS",
            "summary": "initial admin",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910102"],
            "operations": [{"op": "write_text", "path": "app/admin.txt", "content": "admin-raw\n"}],
        },
        {
            "status": "REQUEST_CHANGES",
            "summary": "backend issue one",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910101"],
        },
        {
            "status": "SUCCESS",
            "summary": "backend repair one",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910101"],
            "operations": [{"op": "write_text", "path": "app/backend.txt", "content": "backend-v1\n"}],
        },
        {
            "status": "REQUEST_CHANGES",
            "summary": "backend issue two",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910101"],
        },
        {
            "status": "SUCCESS",
            "summary": "backend repair two",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910101"],
            "operations": [{"op": "write_text", "path": "app/backend.txt", "content": "backend-v2\n"}],
        },
        {
            "status": "REQUEST_CHANGES",
            "summary": "backend remains exhausted; admin issue discovered late",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910101", "TASK-910102"],
        },
        {
            "status": "SUCCESS",
            "summary": "admin late repair",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910102"],
            "operations": [{"op": "write_text", "path": "app/admin.txt", "content": "admin-table\n"}],
        },
        {
            "status": "APPROVE",
            "summary": "late admin issue repaired; exhausted backend received no third repair",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910101", "TASK-910102"],
        },
    ]
    llm_server, llm_handler = start_server(SequenceHandler, responses)
    try:
        pipeline = AutonomousDevelopmentPipeline(
            client=client_for(llm_server),
            repo_root=repo,
            profiles={
                "backend": AgentExecutionProfile(),
                "admin": AgentExecutionProfile(),
            },
            allowed_verification_executables=set(),
            max_coding_attempts=1,
            max_review_rounds=2,
        )
        result = pipeline.run(
            "exercise per-task review repair budgets",
            base_branch="main",
            feature_branch="feature/REQ-910001-review-budget",
        )

        assert result.status == "SUCCESS"
        assert result.review and result.review.status == "APPROVE"
        assert [record.task_id for record in result.task_runs] == [
            "TASK-910101",
            "TASK-910102",
            "TASK-910101",
            "TASK-910101",
            "TASK-910102",
        ]
        assert "backend-v2" in (repo / "app/backend.txt").read_text("utf-8")
        assert "admin-table" in (repo / "app/admin.txt").read_text("utf-8")
        assert len(llm_handler.requests) == 12
        assert run_git(repo, "rev-list", "--count", "main..HEAD") == "6"
    finally:
        llm_server.shutdown()
'''

test_text = tests_path.read_text(encoding="utf-8")
if "def test_late_discovered_task_gets_its_own_repair_budget" in test_text:
    raise RuntimeError("late-review repair regression test already exists")
tests_path.write_text(test_text.rstrip() + test + "\n", encoding="utf-8")

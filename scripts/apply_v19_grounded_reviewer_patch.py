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

old_project_context = '''    def _project_context(self) -> str:
        path = self.repo_root / ".agent/project.yaml"
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[:20000]

    def _task_constraints(self) -> str:
'''
new_project_context = '''    def _project_context(self) -> str:
        path = self.repo_root / ".agent/project.yaml"
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[:20000]

    def _review_context(self, max_chars: int = 40000) -> str:
        """Build a read-only reviewer bundle from declared verified repository context."""
        candidates: list[str] = [".agent/project.yaml"]
        contracts_dir = self.repo_root / ".agent/contracts"
        if contracts_dir.is_dir():
            for path in sorted(contracts_dir.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    candidates.append(path.relative_to(self.repo_root).as_posix())
        for profile in self.profiles.values():
            candidates.extend(profile.context_paths)

        chunks: list[str] = []
        seen: set[str] = set()
        used = 0
        for raw in candidates:
            rel = str(raw).replace("\\\\", "/").strip()
            if not rel or rel in seen or any(char in rel for char in "*?["):
                continue
            seen.add(rel)
            path = (self.repo_root / rel).resolve()
            try:
                path.relative_to(self.repo_root)
            except ValueError:
                continue
            if not path.is_file() or path.is_symlink():
                continue
            body = path.read_text(encoding="utf-8", errors="replace")
            block = f"--- {rel} ---\\n{body}\\n"
            remaining = max_chars - used
            if remaining <= 0:
                break
            if len(block) > remaining:
                block = block[:remaining]
            chunks.append(block)
            used += len(block)
        return "\\n".join(chunks)

    def _task_constraints(self) -> str:
'''
text = replace_once(text, old_project_context, new_project_context, "review context helper")

old_review_context = '''            f"VERIFIED PROJECT CONTEXT:\\n{self._project_context()}\\n\\n"
            "AVAILABLE EVIDENCE IDS:\\n"
'''
new_review_context = '''            f"VERIFIED REVIEW CONTEXT (project facts, contracts, and declared agent context):\\n{self._review_context()}\\n\\n"
            "AVAILABLE EVIDENCE IDS:\\n"
'''
text = replace_once(text, old_review_context, new_review_context, "review context prompt")

old_rules = '''            "Evaluate all currently identifiable material defects across all tasks in this review; do not intentionally defer known defects to later review cycles. "
            "Requested changes must stay within the requirement, ADR, VERIFIED contracts, and VERIFIED project context; do not invent endpoints, identity sources, or integration facts. "
            "Do not use file paths or prose in evidence. Existing unchanged files may not appear in DIFF; do not claim they are absent solely because they are not in DIFF.\\n\\n"
'''
new_rules = '''            "Evaluate all currently identifiable material defects across all tasks in this review; do not intentionally defer known defects to later review cycles. "
            "Requested changes must stay within the requirement, ADR, VERIFIED contracts, and VERIFIED project context; do not invent endpoints, identity sources, or integration facts. "
            "REQUEST_CHANGES has a strict burden of proof: every requested change must be directly supported by REQUIREMENT, ARCHITECTURE, VERIFIED REVIEW CONTEXT, TASK RUNS, or DIFF. "
            "Do not use hypothetical or conditional concerns (for example may, might, could, if, perhaps, possibly) as rejection reasons. "
            "Do not require an 'existing' integration, auth client, privileged scope, event handler, endpoint, or other project component unless it is explicitly present in VERIFIED REVIEW CONTEXT or DIFF. "
            "When a VERIFIED contract defines an internal service seam for a trusted external flow but VERIFIED REVIEW CONTEXT contains no integration component, review the seam itself and do not invent an integration target. "
            "When a VERIFIED contract names the endpoint or scope a consumer must use, do not infer a broader privileged endpoint or scope that the contract does not define. "
            "Do not use file paths or prose in evidence. Existing unchanged files may not appear in DIFF; use VERIFIED REVIEW CONTEXT before claiming an unchanged project component is absent.\\n\\n"
'''
text = replace_once(text, old_rules, new_rules, "review grounding rules")

old_feedback = '''                    initial_feedback=(
                        f"READ-ONLY REVIEWER REQUESTED CHANGES IN REVIEW CYCLE {review_cycle + 1}; "
                        f"TASK REPAIR ATTEMPT {repair_attempt}/{self.max_review_rounds}:\\n"
                        f"{review.summary}\\n\\n"
                        f"Repair only {task.id}. Do not change files outside this task's scope."
                    ),
'''
new_feedback = '''                    initial_feedback=(
                        f"READ-ONLY REVIEWER REQUESTED CHANGES IN REVIEW CYCLE {review_cycle + 1}; "
                        f"TASK REPAIR ATTEMPT {repair_attempt}/{self.max_review_rounds}:\\n"
                        f"{review.summary}\\n\\n"
                        f"Repair only {task.id}. Do not change files outside this task's scope. "
                        f"Act only on concrete reviewer findings that explicitly apply to {task.id}; ignore findings that name only other TASK ids. "
                        "REQUIREMENT, ARCHITECTURE, VERIFIED contracts, and your readable VERIFIED project context outrank reviewer prose. "
                        "Do not invent or assume missing integration, auth, client, endpoint, event, or privileged-scope components. "
                        "If reviewer prose depends on a project component absent from your readable verified context, do not fabricate that component; fix the supported in-scope findings instead."
                    ),
'''
text = replace_once(text, old_feedback, new_feedback, "task-scoped repair feedback")

autonomous_path.write_text(text, encoding="utf-8")


tests = tests_path.read_text(encoding="utf-8")
anchor = '''        assert len(llm_handler.requests) == 12
        assert run_git(repo, "rev-list", "--count", "main..HEAD") == "6"
'''
replacement = '''        assert len(llm_handler.requests) == 12
        first_review_prompt = llm_handler.requests[5]["body"]["messages"][1]["content"]
        assert "REQUEST_CHANGES has a strict burden of proof" in first_review_prompt
        assert "Do not use hypothetical or conditional concerns" in first_review_prompt
        admin_repair_prompt = llm_handler.requests[10]["body"]["messages"][1]["content"]
        assert "Act only on concrete reviewer findings that explicitly apply to TASK-910102" in admin_repair_prompt
        assert "VERIFIED contracts" in admin_repair_prompt
        assert run_git(repo, "rev-list", "--count", "main..HEAD") == "6"
'''
tests = replace_once(tests, anchor, replacement, "review/repair prompt assertions")

new_test = r'''


def test_reviewer_context_includes_contracts_and_declared_context(tmp_path):
    repo, _ = make_git_repo(tmp_path)
    contracts = repo / ".agent/contracts"
    contracts.mkdir(parents=True)
    (repo / ".agent/project.yaml").write_text(
        "id: PROJECT-REVIEW-CONTEXT\nverified_contracts:\n  api: .agent/contracts/API-REVIEW.yaml\n",
        encoding="utf-8",
    )
    (contracts / "API-REVIEW.yaml").write_text(
        "id: API-REVIEW\nstatus: VERIFIED\npath: /api/verified\n",
        encoding="utf-8",
    )
    (repo / "app/reviewer-context.txt").write_text(
        "AUTH_MODE=verified-existing-session\n",
        encoding="utf-8",
    )

    pipeline = AutonomousDevelopmentPipeline(
        client=OpenAICompatibleClient(base_url="http://127.0.0.1:1", api_key="", model="x"),
        repo_root=repo,
        profiles={
            "backend": AgentExecutionProfile(context_paths=["app/reviewer-context.txt"]),
        },
        allowed_verification_executables=set(),
    )
    context = pipeline._review_context()

    assert "--- .agent/project.yaml ---" in context
    assert "--- .agent/contracts/API-REVIEW.yaml ---" in context
    assert "path: /api/verified" in context
    assert "--- app/reviewer-context.txt ---" in context
    assert "AUTH_MODE=verified-existing-session" in context
'''
if "def test_reviewer_context_includes_contracts_and_declared_context" in tests:
    raise RuntimeError("reviewer context regression test already exists")
tests_path.write_text(tests.rstrip() + new_test + "\n", encoding="utf-8")

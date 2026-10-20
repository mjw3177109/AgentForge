# AgentForge V4.0 increment — installation and paths

Target repo: `mjw3177109/AgentForge`.

**Install only in an independent `feature/v4-*` branch** based on reviewed V3
or V2 baseline. DO NOT overwrite the `verify/v2.0-stability` branch and DO NOT
merge or modify Draft PR #22.

This ZIP contains **only V4 new files**, no replacement of V2 or V3 files.
Keep existing P0-P4.1 and their pinned SHA packages as they are.

## Apply

1. Create an isolated feature branch from the reviewed integration commit.
2. Extract this ZIP into the repository root, with the same relative paths.
3. `python -m pip install -e ".[dev]"`
4. `python -m pytest -q tests/test_v4_control.py`
5. `python scripts/v4_acceptance.py --scope v4 --iterations 3`
6. `python scripts/v4_acceptance.py --scope full --iterations 3`
7. `python scripts/v4_control.py inspect --repo-root .`
8. Review the exact Git diff before making any commit.

For Django, see `examples/v4/django_execution_profiles.yaml` and
`examples/v4/django_request.json`. The example profile is **not** automatically
applied; a maintainer must adapt it to actual project directories and existing
policies. V4 discovery only reads files, it never runs Django migrations.

## Command examples (operator on a real project)

```bash
python scripts/v4_control.py inspect --repo-root .
python scripts/v4_control.py preflight --repo-root . \
  --trusted-profile .agent/execution-profiles.yaml \
  --request examples/v4/django_request.json
```

`AGENTFORGE_V4_APPROVAL_KEY` and `AGENTFORGE_V4_AUDIT_KEY` are distinct
operator-owned secrets of at least 32 characters. Do not commit them.

GitHub Action `.github/workflows/agentforge-v40-control-offline.yml` runs only
offline checks. It does **not** start paid DeepSeek jobs.

**Current status:** V4 code tested locally on Python 3.13 only; source remains a
preview until actual branch-wide CI and real DeepSeek acceptance succeed.

### Safer incremental installer (Windows / Linux)

Extract the ZIP **to a staging folder outside the repository first**, then run:

```bash
python staging/scripts/v4_install.py --repo-root PATH_TO_AGENTFORGE \
  --archive PATH_TO_V4_ZIP
# Only after reviewing dry-run output:
python staging/scripts/v4_install.py --repo-root PATH_TO_AGENTFORGE \
  --archive PATH_TO_V4_ZIP --apply
```

The installer requires an isolated `feature/v4-*` or `experiment/v4-*` branch
with baseline `fbb4eaba` in its history and a clean tracked worktree. It refuses
to overwrite different existing files. It never pushes commits to GitHub.

# AgentForge

AgentForge is a GitHub-driven, constrained multi-agent software engineering framework.

## V1.3 bootstrap

This repository baseline intentionally starts with the deterministic safety core:

- `.agent` project protocol
- Requirement / ADR / Task schemas
- Fact / Evidence validation
- Task state machine
- read / write / deny policy engine
- safe workspace mutations
- symlink and path-traversal defenses
- GitHub Actions CI
- WeChat shop template policy skeleton

The next layer adds the live LLM/GitHub runtime on top of these gates; models never bypass them.

## Local check

```bash
python -m pip install -e ".[dev]"
pytest -q
python protocol_bundle/scripts/validate_protocol.py
```

## Engineering rule

> 不知道就停；有依据才改；测试通过才完成；合并之后才记忆。

## Django auxiliary manager (optional branch)

This branch adds an installable agentforge_django App and a small demo host under
examples/django_host. Read docs/DJANGO_AGENT_MANAGER.md or README_DJANGO.md.
Existing AgentForge core is preserved. Autonomous mutation remains opt-in and
candidate patches are NEVER deployed by the addon.


## V0.3 Django Control Center

See [README_DJANGO.md](README_DJANGO.md) for a runnable Django host and
[docs/DJANGO_AGENT_MANAGER.md](docs/DJANGO_AGENT_MANAGER.md) for security gates.
This version adds staff-readable dashboards and superuser-only intake/approval/
sanitized evidence endpoints. No autonomous code runs through HTTP endpoints.


## V0.4 offline Docker verifier

The Django addon now requires an offline Docker verifier for behavioral tests
(default, fail closed). Build with:
`docker build -t agentforge-django-verify:0.4 -f docker/Dockerfile.verify .`.
The previous host autonomous coding path is disabled by default pending a
secure isolated coding executor. Manual real-model acceptance in
`.github/workflows/agentforge-django-v04-live.yml` tests only a read-only
three-round policy fixture; full coding stability is not claimed.


## V0.5 constrained coding candidate pipeline

A new optional Django coding path performs bounded typed Planner/Executor/
Reviewer calls and independent offline Docker test verification. The old host
subprocess coding executor remains closed by default, and production deployment
remains an explicit human-only action. See README_DJANGO.md.


## V0.6 one-repair candidate flow (opt-in)

The additive Django layer now limits model-driven candidate changes to
one reviewable repair, at most five role requests and two independent offline
Docker validation rounds. It includes worker-only settings and audit metrics,
all OFF by default. See `README_DJANGO.md` and `deploy/v06/README.md`.

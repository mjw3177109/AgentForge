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

# AgentForge V3.0 — P3 仅增量安装清单

本包只包含以下 **5 个新增文件**，仓库根目录作为解压目标：

- `src/agentforge/memory_v3.py` — 受限长期记忆、独立证据关联、静态策略推荐
- `scripts/v3_memory.py` — `init/observe/predeclare/import-run/recommend/history` 可选 CLI
- `tests/test_v3_memory.py` — 离线安全与 P1/P2 兼容测试
- `docs/V30_MEMORY_P3.md` — 功能与运行说明
- `PLACEMENT_P3.md` — 本安装清单

**不覆盖** V2 的任何源码或 P0/P1/P2 的任何文件。不要将历史 memory.sqlite3 放进 Agent 的写权限目录。

安装建议：独立 `feature/v3-memory-p3` 分支；先将 P0/P1/P2 已有增量文件保留，再解压本包，执行：

```bash
python -m pip install -e ".[dev]"
pytest -q tests/test_v3_memory.py
```

若要执行总集成测试，参考 `docs/V30_MEMORY_P3.md`。本包没有推送到 GitHub、修改 PR #22、运行新的远端 Actions、扩大权限或改变生产系统。

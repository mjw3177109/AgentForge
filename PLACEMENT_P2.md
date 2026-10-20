# AgentForge V3.0 P2 增量安装清单

只包含 **8 个新增文件**（未替换 V2 现有文件）：

| 文件 | 用途 |
|---|---|
| `src/agentforge/repair_v3.py` | 子类化 V2 编码执行器，实现安全回滚与结构化故障诊断 |
| `scripts/v3_p2_integrate.py` | 严格的 Git 分支/源码锚点检查，默认 dry-run，`--apply` 才启用 CLI 接入 |
| `scripts/v3_p2_diagnose.py` | 只读故障分类 CLI |
| `tests/test_v3_repair.py` | 故障、回滚、权限、Java 门禁回归测试 |
| `tests/test_v3_p2_installer.py` | 真实 Git 初始化的隔离接入测试 |
| `tests/fixtures/v20_run_39103687560_round01_maven.log` | 真实历史失败日志 fixture |
| `docs/V30_SAFE_REPAIR_P2.md` | 使用文档和安全边界 |
| `PLACEMENT_P2.md` | 本清单 |

### 放置

1. 切换/创建独立 `feature/v3-*` 或 `experiment/v3-*` 分支（不能是 main、V2 PR 分支）。
2. 将本 ZIP 解压到仓库根目录，不移除或覆盖已有 V2/P0/P1 文件。
3. 执行 `python -m pip install -e ".[dev]"`。
4. 执行 `pytest -q tests/test_v3_repair.py tests/test_v3_p2_installer.py`。
5. 如果需要接入，在独立分支执行 `python scripts/v3_p2_integrate.py --repo-root .` 查看 diff，审查后 `--apply`。
6. 接入后默认行为还是 V2，只有显式 `--v3-safe-repair` 才启用 P2。

**当前不等同 V3 工程整体验收通过，不会自动调用 DeepSeek/修改 Github/合并 PR/部署。**

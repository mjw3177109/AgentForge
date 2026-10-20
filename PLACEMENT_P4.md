# P4 增量安装清单

本 ZIP **只新增 6 个文件**，不覆盖原仓库文件、P0–P3 原型或 PR #22：

| 路径 | 用途 |
|---|---|
| `src/agentforge/acceptance_v3.py` | P0–P3 完整性预检、历史只读诊断、P1 签名证据核验及离线结果候选审查 |
| `scripts/v3_p4_acceptance.py` | 统一 P4 CLI：inspect / history / offline / verify |
| `tests/test_v3_p4_acceptance.py` | P4 安全与跨模块回归测试 |
| `.github/workflows/agentforge-v30-p4-acceptance.yml` | 独立分支手动触发的验收工作流，仅人工注册，不自动触发 |
| `docs/V30_P4_INTEGRATION_ACCEPTANCE.md` | 完整技术方案与验收标准 |
| `PLACEMENT_P4.md` | 本文件 |

放置：从 `fbb4eabab1b42b26ee1f545c38729dadc68541c5` 创建独立 `feature/v3-p4-acceptance`，先安装 P0/P1/P2/P3，再解压本包到仓库根目录。切勿直接解压到 `verify/v2.0-stability`、`main`，不要执行 P2 安装器的 `--apply`，除非在实验分支已经逐项审查。

测试：`python -m pip install -e ".[dev]" && pytest -q tests/test_v3_preflight.py tests/test_v3_evidence.py tests/test_v3_repair.py tests/test_v3_p2_installer.py tests/test_v3_memory.py tests/test_v3_p4_acceptance.py`

真实端到端：完整流程见 `docs/V30_P4_INTEGRATION_ACCEPTANCE.md`。独立 Python CI、LLM、MySQL、Maven/Node/Vite 尚需正式 CI 验收。

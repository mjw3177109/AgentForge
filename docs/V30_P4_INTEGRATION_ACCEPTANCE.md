# AgentForge V3.0 P4 — 集成与稳定性验收（增量，不发布）

## 1. 实际交付和边界

P4 将 P0 权限治理、P1 独立证据、P2 受限修复、P3 工程记忆纳入同一套 **fail-closed 验收流程**。本补丁新增 4 个文件和 1 个 GitHub Actions workflow，不覆盖 V2 核心文件、P0–P3 已有代码，也不改变 Agent read/write/deny 配置。

- `src/agentforge/acceptance_v3.py`：检查组件清单、诊断历史 V2 结果、核对 P1 独立签名、检查离线矩阵候选结果（候选 JSON 永不自动被视为可信 CI）。
- `scripts/v3_p4_acceptance.py`：`inspect`/`history`/`offline`/`verify` 四种只读或仅向**显式输出路径**写测试报告的命令。
- `tests/test_v3_p4_acceptance.py`：离线 11 项 P4 测试，跨 P0/P1/P2/P3，包含越权 JUnit、Java Optional 类型错误、2/3 失败不误判、签名篡改与未认证 CI 结果阻断。
- `.github/workflows/agentforge-v30-p4-acceptance.yml`：仅手动触发，双 Python 版本三轮全量 Python 测试、三轮真实 DeepSeek、每轮 Node/Maven/Vite/MySQL 门禁、隔离证据签名；无自动合并和部署动作。
- `docs/V30_P4_INTEGRATION_ACCEPTANCE.md`：本说明；另附根目录 `PLACEMENT_P4.md` 安装清单。

**重要安全原则：本地检查成功、离线 121 项通过、甚至 P1 验证了三轮真实 benchmark 都不能自动批准合并或生产发布。真实 P4 完整验收需要人工审阅签名证据、两套 Python CI、P2 opt-in 的独立真实验收以及业务 Exactly-once 服务层门禁。**

## 2. 离线安装与测试

基线：GitHub 仓库 `mjw3177109/AgentForge` 的 `verify/v2.0-stability`，已知提交 `fbb4eabab1b42b26ee1f545c38729dadc68541c5`。**不要在该受保护验收分支或 PR #22 上直接安装；先从基线派生 `feature/v3-p4-acceptance`。**

先依次安装 P0、P1、P2、P3 增量包，再把本 ZIP 解压到仓库根目录。所有原文件保留，不要默认运行 P2 的 `--apply`，也不要擅自扩大 Backend 对 `server/src/test/**` 的写权限。

```bash
python -m pip install -e ".[dev]"
python scripts/v3_p4_acceptance.py inspect --repo-root .
python scripts/v3_p4_acceptance.py offline --repo-root . --scope v3-smoke --iterations 1
python scripts/v3_p4_acceptance.py offline --repo-root . --scope full --iterations 3 \
  --output /tmp/v30-offline-python-current.json
```

- `inspect` 输出 `COMPONENTS_PRESENT_NOT_VERIFIED`：仅证明所需文件存在并可读，不是功能验收。
- `offline` 固定执行 `pytest -q -ra`，`full` 额外执行 V2 的 `protocol_bundle/scripts/validate_protocol.py`；三轮每轮必须完整成功。不接受 skipped/xfail/xpass 伪通过。
- Python 3.11 和 3.12 是**两个独立 CI 环境**，本地只运行一个 Python 版本不能视为 CI 矩阵通过。
- `history` 是**未签名诊断**，即使全部报 PASS 也只返回 `ELIGIBLE_FOR_INDEPENDENT_P1_VERIFICATION`，不能得到可信验收 PASS。返回非零表示失败或未核验。

## 3. 真实历史 2/3 失败的离线回放

从官方 GitHub Actions Run #39103687560 下载 `agentforge-v20-stability-evidence` 并解压。不要使用旧 #39092231063 的单次成功冒充当前三轮稳定性通过。

```bash
python scripts/v3_p4_acceptance.py history --artifacts /path/to/artifacts/v20-stability
```

实际在 2026-10-19 本地回放检查中，结果为 `REPORTED_FAIL`，Round 01 FAIL、Round 02 PASS、Round 03 PASS；后两轮各报告 10/10 门禁，**CLI 故意返回退出码 2**。这是对历史已有 artifact 的诊断，不是新的 DeepSeek 运行。

## 4. P1 证据验签的硬性条件

只有**独立可信验证环境**可以持有 `AGENTFORGE_V3_EVIDENCE_KEY`，同时必须从 GitHub API/受信任 CI 上下文固定真实 Run ID、源提交 SHA、模型标识以及执行配置。不可从被验签的 JSON 自身推断期待值。

```bash
python scripts/v3_p4_acceptance.py verify \
  --artifacts /trusted/v20-stability --manifest /trusted/p4-signed-v20.json \
  --profile benchmarks/v18_hardened/execution-profiles.yaml \
  --expected-run-id <NEW_RUN_ID> --expected-commit <FULL_40_SHA> \
  --expected-model <REAL_CONFIGURED_MODEL_ID> \
  --expected-key-id p4-reviewed-verifier
```

在存在并匹配已审查密钥且 3/3 独立门禁均通过时才返回 `INDEPENDENT_LIVE_3_OF_3_VERIFIED`；**其含义只限 V2 fixture 的三轮真实运行已完成独立证据核验**。这不是 Django、Spring、真实支付集成或 P2 已启用的真实执行能力声明。

## 5. GitHub Actions 新工作流设计

`.github/workflows/agentforge-v30-p4-acceptance.yml` **只允许 `workflow_dispatch` 手动触发**，并要求：

1. 在独立 `feature/v3-*` / `experiment/v3-*` 分支上运行；输入确认口令 `RUN_THREE_PAID_DEEPSEEK_ROUNDS`，避免无意触发付费三轮。
2. 提供固定、**经人类审查**的 40 位 `trusted_verifier_sha`；该 SHA 的 P1 验证程序及可信 profile 不可由执行 Agent 任意修改。
3. `offline` 在 Python 3.11/3.12 分别运行三轮完整 pytest/protocol。测试失败不继续付费模型。
4. `live` 用原 V2 `scripts/run_v20_stability.py` 在临时 MySQL/Redis 以及 Node 20/Java17 环境中执行三轮；失败仍上传 artifact。
5. `independent-attestation` 是隔离的新 job，**只有此 job**接收签名密钥；从可信 verifier SHA 读取 P1 源码，下载前一 job 的 artifact，重新计算校验和与 Reviewer / 四 Agent / MySQL 并发门禁，签名并验签。不接触生产数据。
6. `permissions: contents: read`，不授予 push、发布 PR、合并、部署权限。

注意 GitHub 官方限制：一个全新的 `workflow_dispatch` workflow 通常需要先经维护者审查并在**默认分支注册**，才能在 Actions UI 手动选择目标 ref。为了保护 main/PR #22，本包**没有自动注册或执行**新 workflow；可由维护者通过独立审核的工作流注册 PR 实施。不得为绕过这一限制添加会自动花费 DeepSeek 额度的 `push` 触发器。

`AGENTFORGE_LLM_BASE_URL`、`AGENTFORGE_LLM_MODEL` 使用 GitHub Repository Variables；`AGENTFORGE_LLM_API_KEY`、`AGENTFORGE_V3_EVIDENCE_KEY` 使用 Repository Secrets。若凭证不存在必须 fail，不允许 skip 算 PASS。

## 6. 验收矩阵及剩余风险

| 验收事项 | 当前状态 | 是否可宣称 V3 全量通过 |
|---|---|---|
| P0–P4 本地隔离兼容测试 | 122/122 PASS（Python 3.13） | 否 |
| 真实历史 Artifact #39103687560 回放 | 2/3 FAIL（正确保留） | 否 |
| P0 权限范围保护 | 本地回归覆盖 JUnit 路径拒绝 | 否 |
| P1 签名证据跨 Run/commit 防重用 | 合成数据集验证 | 否 |
| P2 Java Optional 类型错误识别 / 有限回滚 | 离线回归 | 否 |
| P3 失败案例索引与策略只读建议 | 离线回归 | 否 |
| Python 3.11/3.12 三轮**整仓**测试 | 待正式 Actions 运行 | 否 |
| 真实 DeepSeek 最新提交 3/3 + Reviewer/四 Agent | 待新 Run | 否 |
| 每轮 10 项独立 Node/Maven/Vite/MySQL | 待新 Run | 否 |
| P2 `--v3-safe-repair` 真正启用后的 Live 三轮 | 待单独构建 Live 基准；本工作流暂跑 V2 fixture | 否 |
| Java 服务层重复业务单号 exactly-once 入账 | 尚无完整独立业务集成门禁 | 否 |
| 生产发布安全、流量、多租户 | 未验证 / 不在本阶段放行范围 | 否 |

**结论：P4 补丁提供可运行的验证入口、集成安全回归和可部署的手动验收流程定义，但没有创造一条新的正式 DeepSeek Run。** PR #22 继续保持 Draft，直到正式证据满足要求并由人类复核。

## 7. 下一阶段

P4.1：维护者审阅新 workflow、执行完整整仓双 Python CI；P4.2：用真实 DeepSeek 在明确启用 P2 的隔离工作树上跑三轮并测量修复率；P4.3：新增独立 Java 服务层 `business_no` exactly-once 行为门禁，以及 PostgreSQL/MySQL 场景差异测试（仅在相应目标系统采用这些数据库时）。之后才考虑 V3 Release Candidate，而非自动生产部署。

# AgentForge V3.0 · P1 独立证据引擎（增量实现）

> 状态：可运行的 **离线证据收集/完整性核验原型**。仅新增文件，未接入 V2 运行链路、未提交 GitHub、未改变权限、不自动合并或部署。`VERIFIED_PASS` 不是生产发布许可。

## 1. 目标

把 V2.0 的 `artifacts/v20-stability/` 目录从“可阅读的日志”升级成“受签名保护、带上下文绑定、能够重新计算状态的证据包”，并禁止仅凭 Reviewer `APPROVE` 或 `summary.json` 的一句 `PASS` 判断验收成功。

接口同时追踪：GitHub Actions `run_id`、完整 40 位 commit SHA、模型 ID、可信 profile SHA-256、产生时间、validator 版本、round、TASK ID 与 task commit、独立 gate ID/结果/日志 SHA-256，以及生成代码快照的受控文件摘要。

V2.0 的旧 `agentforge.evidence.EvidenceIndex` 用于协议证据 ID 验证；这里创建独立包 `agentforge.evidence_v3`，**不改变既有模块语义**。

## 2. 读取内容与验收规则

读取 `summary.json` 与 `round_01/02/03/v20_result.json`，逐项对比；再读取三轮 `v20_runner_stdout.txt` / `v20_runner_stderr.txt`、每项独立 gate 的原始日志、以及完成轮次的生成代码快照。

单轮 `PASS` 必须同时满足：

1. `v20_result.json` 与 summary 内逐轮记录相同，轮号、轮状态和退出码一致。
2. 原始 JSON 任务日志为 `SUCCESS`，四个 Agent 各有一次初始 `SUCCESS`，各自具有提交 SHA，Reviewer 为 `APPROVE`，返修次数不超过 2，并且没有发布 PR。
3. 正好存在以下十项互不重复的独立 gate：
   - `node_database-contract_test`
   - `node_backend-contract_test`
   - `node_points_test`
   - `node_points-ledger-contract_test`
   - `maven`
   - `npm_install`
   - `npm_vite`
   - `mysql_create`
   - `mysql_schema`
   - `mysql_concurrent_ledger_uniqueness`
4. 全部 gate `PASS`、退出码为零，日志存在且与报告退出码匹配；MySQL schema 日志包含两张契约表，MySQL 并发日志必须证明两个写入中仅一个成功、另一写入因重复键失败，并且最终仅一行。
5. 核对数据库 SQL、Node 测试、Java 主要源码、前端源码、Maven/Vite 配置等稳定快照文件；并枚举所有 Java 源码参与哈希，避免生成的新 Java 文件脱离签名覆盖。
6. `summary.json` 必须明确 `rounds_required=3`、`rounds_passed=3`、`overall=PASS`，并符合重新计算出的结果。任何缺失、不一致、伪造成功或签名异常均无法通过。

一个已经失败的轮次因上游失败未执行后续 gate，会记录 `NOT_EXECUTED_GATES`，保持 `FAIL`，**不会被误认为这十项已经测试失败或通过**。如果一轮声称 `PASS` 但缺少测试日志/快照，则为 `UNVERIFIED`。整体只在完整 3/3 且无任何问题时才能 `PASS`。

## 3. 加载和运行

建议放在独立实验分支，如 `feature/v3-evidence-p1`，或在已经加入 P0 的 V3 实验分支上覆盖。切勿加入尚未达标的 `verify/v2.0-stability`。

```bash
python -m pip install -e '.[dev]'
pytest -q tests/test_v3_evidence.py
```

在**与模型/生成代码运行器隔离、持有专用签名密钥的受信任验证环境**中执行收集（签名 key 从受保护的 CI Secret `AGENTFORGE_V3_EVIDENCE_KEY` 注入，建议随机 >=32 字节，不要保存在仓库或 artifact 中）：

```bash
python scripts/v3_evidence.py collect \
  --artifacts artifacts/v20-stability \
  --profile benchmarks/v18_hardened/execution-profiles.yaml \
  --run-id 39103687560 \
  --commit fbb4eabab1b42b26ee1f545c38729dadc68541c5 \
  --model-id YOUR_ACTUAL_MODEL_ID \
  --key-id trusted-ci-v1 \
  --output v3_evidence_run_39103687560.json
```

**注意：**示例 Run #39103687560 是历史 **2/3 FAIL**，上面的 collect 会创建签名报告并以退出码 `2` 结束，不会制造虚假的 `PASS`。请用真实的受信任模型名替代占位符。

再在**独立验证上下文**使用从 GitHub/可信 CI 获取的 run、commit、model、key ID 进行核对：

```bash
python scripts/v3_evidence.py verify \
  --artifacts artifacts/v20-stability \
  --profile benchmarks/v18_hardened/execution-profiles.yaml \
  --manifest v3_evidence_run_39103687560.json \
  --expected-run-id 39103687560 \
  --expected-commit fbb4eabab1b42b26ee1f545c38729dadc68541c5 \
  --expected-model-id YOUR_ACTUAL_MODEL_ID \
  --expected-key-id trusted-ci-v1 \
  --max-age-hours 168
```

`collect` **仅以独占新建方式写入指定的本地输出文件，不覆盖已有文件**；`verify` 完全只读。两个命令均不调用网络、DeepSeek、GitHub、Maven、MySQL、Vite，不执行原项目源码。不修改 PR、工作流、原 Agent 权限、模型配置或生产环境。

`collect` 输出 `COLLECTED` 与真实计算的 `PASS/FAIL/UNVERIFIED`，不代表独立认可。`verify` 只有在签名、期望上下文、时间戳、每个受保护文件 SHA-256 和重新计算的验收条件全部一致时才返回 `VERIFIED_PASS`；否则返回 `BLOCKED` 和问题清单，进程退出码 `2`。

## 4. 安全与信任边界

- **HMAC-SHA256 保护完整性和对称密钥持有者身份，并不能证明生成代码正确。** 如果不可信 Agent 能访问签名密钥，它就可以自己签出虚假证据。生产部署时应使用可信隔离验证器、不可被 Agent 访问的密钥、只读 artifact 输入，独立密钥轮换与发布审批。此原型不执行签名者身份基础设施的部署。
- 每一轮的 `Reviewer APPROVE` 是 **LLM 审查意见**； Node/Maven/Vite/MySQL gate 日志是 **验证器输出**；前者不能代替后者。模型输出不能通过自填 JSON 变成独立测试。
- 哈希绑定的是**清单枚举的证据文件**，包括 10 类测试日志和重要源码，不是对整个 GitHub 仓库、CI Runner 或 MySQL 服务器完整可信性的加密证明。构建结果重现性、测试欺骗、对执行器的供应链攻击需独立治理。
- `snapshot_sha256` 覆盖固定契约相关文件和全部 Java 源码；不包括可能巨大的 `node_modules`、`target`、`dist`、`.git`。没有快照就不能认定对应轮次 PASS。
- 该项目的 MySQL 并发门禁只验证 **ledger 唯一约束**，不能推出 Java 服务层 exactly-once 积分入账、Redis 故障回退或生产支付链路的正确性。
- P1 不从未经信任的输入扩张 `write_scope`，也不取代 P0/既有文件系统防护。需要单独批准后才能考虑将其作为 Actions 的*额外*验收门禁，而不是代替原有 V2 门禁。
- 提供 `--max-age-hours` 用于限制证据新鲜度，默认 168 小时，过期/未来时间会拒绝。

## 5. 验证实况（2026-10-19）

- 25 项 P1 离线测试通过；与 P0 12 项组合为 37 项通过。
- 从真实历史 [Run #39103687560](https://github.com/mjw3177109/AgentForge/actions/runs/39103687560) 的 GitHub artifact 提取所需输出和源码，离线重新计算得到：**整体 FAIL，2/3 PASS**，第 1 轮执行失败（10 项后置 gate 未运行），第 2、3 轮各 10 项独立门禁 PASS。这个冒烟检查没有使用可信 CI 的签名密钥，也不等于线上 P1 已接入。
- 未执行完整原仓库 Python 3.11/3.12 多轮 CI 或真实 DeepSeek 重跑。

## 6. 下一阶段 P2 建议

基于 P1 的可信失败材料，再实现 `VERIFICATION_SCOPE_GAP`、`COMPILATION_FAILURE`、`BEHAVIORAL_FAILURE` 等分类，以及 Java 返修后的即时编译门禁。历史失败只能指导策略，不得自动扩权、减测或发布。

# AgentForge V3.0 — P3 长期工程记忆与安全策略学习

## 1. 目标与工程边界

P3 是**可选的、独立的、建议型工程记忆模块**：把 P2 故障分类、历史独立验收证据与人工预声明的修复策略试验关联起来。长期保存最小化的结构化历史，推荐**由代码审查过的固定策略**，不生成或执行补丁。

- 完全新增，不覆盖 `src/agentforge/evidence.py`、`autonomous.py`、`coding.py`、`policy.py`、`repair_v3.py`、`cli.py`，不碰 V2 稳定性分支/PR。
- 不调用 DeepSeek/其他大模型、GitHub API、Shell、数据库迁移、生产接口，不改 read/write/deny，不能合并 PR 或发布。
- 现阶段既不把 P3 建议自动注入 P2 的 Agent prompt，也不为历史经验扩大任何执行能力；人工独立判断并明确授权是必须的。
- 只有 P1 在独立信任环境**重验签名、摘要、Run ID、commit、模型、可信 profile 和 3/3 门禁**之后才记录相应结果。

## 2. 文件清单（增量 4 个文件）

| 路径（相对仓库根目录） | 作用 |
|---|---|
| `src/agentforge/memory_v3.py` | SQLite 存储、指纹隔离、策略目录、独立签名验收导入与只读策略查询 |
| `scripts/v3_memory.py` | opt-in 本地命令行：init/observe/recommend/predeclare/import-run/history |
| `tests/test_v3_memory.py` | P1/P2 接口的独立三轮合成 fixture + 权限隔离/防重放/防篡改测试 |
| `docs/V30_MEMORY_P3.md` | 本说明 |
| `PLACEMENT_P3.md` | 安装与覆盖清单 |

**注意：实际 ZIP 为 5 个新增文件**（含本清单）。没有 `__pycache__`、凭证、数据库文件或历史原始日志。

## 3. 先决条件

1. 在**独立的** `feature/v3-*` 实验分支，已安装现有 AgentForge（Python >=3.11）和 P1、P2 增量文件。
2. 使用既有依赖 `pydantic`、`pytest` 等；P3 自身只使用 Python 标准库 SQLite、hashlib、json 等，以及 P1 验证接口。
3. 准备一个受信任的 `execution-profiles.yaml`，可以先用 `benchmarks/v18_hardened/execution-profiles.yaml` 进行隔离开发测试。业务项目使用自己的可信、已批准 profile。
4. 在目标项目**外部**存放长期 SQLite 文件，避免被 Agent 所能写的目录覆盖；例如 `$HOME/agentforge-private/memory.sqlite3`。数据库目录需要先由维护者创建并限制访问。CLI 不替维护者创建目录。

## 4. 命令行：P2 诊断 → P3 记忆 → 推荐

以下命令在仓库根目录执行，所有写入仅指向维护者明确选择的 SQLite 文件（不得放在 Agent 工作区）。

```bash
# 先在仓库根目录安装（仅示例；不触发真实 Agent）
python -m pip install -e ".[dev]"
mkdir -p "$HOME/agentforge-private"
chmod 700 "$HOME/agentforge-private"  # Linux/macOS，Windows 需使用 NTFS ACL

# 初始化（显式创建，已存在的陌生数据库不会被覆盖）
python scripts/v3_memory.py --db "$HOME/agentforge-private/memory.sqlite3" init

# 使用 P2 的原始只读诊断 CLI 生成结构化 JSON
python scripts/v3_p2_diagnose.py \
  --log tests/fixtures/v20_run_39103687560_round01_maven.log \
  > /tmp/agentforge-p2-diagnosis.json

# 存储仅包含分类、20 位指纹和来源标签的历史观察；忽略原始日志和自由文本
python scripts/v3_memory.py --db "$HOME/agentforge-private/memory.sqlite3" \
  observe --project mjw3177109/AgentForge \
  --profile benchmarks/v18_hardened/execution-profiles.yaml \
  --diagnosis /tmp/agentforge-p2-diagnosis.json --source-id run-39103687560-round01

# 仅返回策略提示和历史关联效果；不写代码、不执行修复
python scripts/v3_memory.py --db "$HOME/agentforge-private/memory.sqlite3" \
  recommend --project mjw3177109/AgentForge \
  --profile benchmarks/v18_hardened/execution-profiles.yaml \
  --diagnosis /tmp/agentforge-p2-diagnosis.json
```

返回状态 `ADVISORY_ONLY`，并提供经过审查的固定策略如 `java-declared-type-check` 与 `java-optional-boundary-review`。对于 `VERIFICATION_SCOPE_GAP`、`TIMEOUT`、`ENVIRONMENT` 等类别返回 `BLOCKED_FOR_AUTOREPAIR` 且无建议。**这些都是静态/历史经验，不是软件验收成功。**

## 5. 策略试验与 P1 关联

**必须先有对应 P2 诊断记录**。一次项目 Run 最多预声明一个策略；已经导入的 Run 无法补报试验。Run ID、commit 和可信 profile 必须匹配 P1 的验收证据。

```bash
# 在验收证据导入之前，明确登记试验关联（不启动任务）
python scripts/v3_memory.py --db "$HOME/agentforge-private/memory.sqlite3" \
  predeclare --project mjw3177109/AgentForge \
  --profile benchmarks/v18_hardened/execution-profiles.yaml \
  --fingerprint <P2_20_HEX_FINGERPRINT> \
  --strategy-id java-declared-type-check \
  --run-id <NEW_ACTIONS_RUN_ID> --commit <FULL_40_CHARACTER_COMMIT>

# 只有在持有受信任 P1 校验密钥的独立验证环境中，才导入证据
# 由负责签名的 CI 以安全方式注入 AGENTFORGE_V3_EVIDENCE_KEY
python scripts/v3_memory.py --db "$HOME/agentforge-private/memory.sqlite3" \
  import-run --project mjw3177109/AgentForge \
  --profile benchmarks/v18_hardened/execution-profiles.yaml \
  --manifest /path/to/signed_p1_manifest.json \
  --artifacts /path/to/v20-stability-artifacts \
  --run-id <NEW_ACTIONS_RUN_ID> --commit <FULL_40_CHARACTER_COMMIT> \
  --model deepseek-chat --key-id <TRUSTED_SIGNING_KEY_ID>

python scripts/v3_memory.py --db "$HOME/agentforge-private/memory.sqlite3" \
  history --project mjw3177109/AgentForge
```

**说明：** 示例中的 `<...>` 是待填写的占位符，不能原样运行。

- P1 `VERIFIED_PASS`：记录 `IMPORTED_PASS`、3/3；若存在同一 run/commit/profile 的预声明，则仅记为 `ASSOCIATED_PASS`。
- P1 对真实失败的 signed `2/3` 返回 `BLOCKED`；仅在其内层完整性校验没有其它错误（返回问题完全等于重新计算出的实际失败问题）时，P3 可保存 `IMPORTED_FAIL`，从不计成功。为防 CI 将它误认作通过，CLI 返回退出码 2。
- 签名不对、文件篡改、签名过期、Run/commit/模型/profile 不符、证据缺失或重新验证不一致：**阻止导入，不记录 PASS/FAIL**。
- `predeclare` 仅证明本地记录的声明早于 **P3 证据导入**，并不能证明策略确实在远端真实 Run 执行，也无法证明声明早于远端 Run 的实际开始；目前记录的 `ASSOCIATED_PASS` 是**历史关联而非因果证明**。P4 需由可信调度器在执行时签名策略启用事件，才能进一步证明采用关系。

## 6. 安全学习与误差限制

- 只有固定、人工审核的策略 ID 才可记录；不能把原始错误日志、LLM 自由提示词、代码、密钥作为可执行记忆。SQLite 中只存结构化分类、指纹、关联、证据 SHA-256 和可信运行标识。
- 推荐查询以 `project + trusted_profile_sha256 + fingerprint + category` 为边界，同名问题跨项目/权限配置**不交叉学习**。
- 推荐排序采用 Beta(1,1) 平滑的 `(关联通过数 + 1)/(关联通过数 + 关联失败数 + 2)` 作为**启发式排序分数**，不是下一次实际成功概率，也不是统计学上独立样本的可靠估计。
- 一个策略在同一指纹下 `>=2` 次关联失败、`0` 次关联通过，就从推荐结果中排除。无剩余候选时返回 `NO_SAFE_RECOMMENDATION`，改由人工分析。
- 即使经验多次成功，也绝对不能：自动加权限、改写 protected tests、降低门禁、取消 Reviewer、发 PR/合并/部署；没有自动应用策略的 API。
- P1 的 HMAC 是共享密钥机制，适用于受信任、隔离验证环境；如果同一执行上下文中的编码 Agent 也能读取密钥，就**不能**认为证据具备独立可信性。

## 7. 离线验收

```bash
pytest -q tests/test_v3_memory.py
pytest -q tests/test_v3_preflight.py tests/test_v3_evidence.py \
  tests/test_v3_repair.py tests/test_v3_p2_installer.py tests/test_v3_memory.py
```

本阶段完成 **36 项 P3 测试**。与原 P0/P1/P2 在已有本地隔离兼容测试接口上一并运行 **111 项通过**。这不是完整 GitHub 项目 Python 3.11/3.12 的 CI、真实 DeepSeek 重跑、独立 Maven/Vite/MySQL 现场测试，也不意味着 V2.0 PR #22 可合并。

用历史 [Run #39103687560](https://github.com/mjw3177109/AgentForge/actions/runs/39103687560) 已下载的证据做了离线烟雾验证，并在临时本地验证环境签署测试清单后导入：结果 `IMPORTED_FAIL`，`rounds_passed=2`，`strategy_trial_linked=false`。这**不是**来自 GitHub 原生的独立签名或一次新 Run。

## 8. P4 后续集成验收前必须完成

1. 在独立 V3 分支，使用实际 GitHub SHA 的整仓测试、Python 3.11/3.12、Node/Maven/Vite/MySQL 严格验收。
2. 将 P1 签名与 P3 数据库放到与执行 Agent **不同安全主体**，配置最小化的密钥读权限和安全存储目录；建立备份/恢复/保留期限。
3. 对试验启用状态增加由可信 Orchestrator 在**开始执行前**签名的不可抵赖证据；只有可信启用记录才能尝试评价修复策略因果效应。
4. 根据真实 V2 `Optional<Long>` 回归缺陷构建独立、可复现的 Java 行为 fixture，验证 P2 回滚与 P3 分类检索协作，而不动受保护测试。
5. 进一步评估本地 SQLite 权限和数据篡改威胁：此 DB 不是防管理员篡改的审计账本，需要由独立信任域保存签名归档。
6. 完整三轮真实 DeepSeek 通过与业务层 Exactly-once 验收之前，保持 PR Draft，不合并、不部署。

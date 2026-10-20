# AgentForge V3.0 — P2 智能故障诊断与受限修复（增量版）

## 1. 实现目标

在 **不替换 V2.0、不开启默认自治、不改变 Agent read/write/deny 权限** 的前提下，为现有 `LiveCodingRuntime` 增加独立的 `SafeRepairRuntime`：

- 使用 V2 原本的 AgentAction、TaskScope、SafeWorkspace、EvidenceIndex、VerificationRunner；不创建新的文件读写权限。
- 每次 Agent 提交候选修改之前，建立**仅包含候选路径**的变更前像和允许路径记录。
- 验证失败时：检查候选文件是否仍为预期的写后状态，随后按路径恢复原内容，或者删除本轮新建的候选文件。
- 遇到文件内容被其他进程意外修改：以 `RollbackConflict` **阻止覆盖**，保留现场供人工处理。
- 反馈 Java/Maven 编译错误、业务测试断言错误、Node/Vite 构建错误等结构化诊断给下一轮 Agent；遇到越权、验收范围缺口、验证器故障、环境故障则 BLOCKED。
- 后端 Java 修改必须具备现有 profile 授权的 Maven `compile/test/package/verify/install` 之一，不能以 `mvn -v` 或省略验证冒充 PASS。
- 检查验证结果数量、命令和返回码与声明的验证 specs 一致；部分绿灯不能冒充完整成功。
- 使用 V2 既有最多 2 次尝试、Reviewer 附加 1 次尝试的上限；不引入无限循环、不增加 Agent 权限。

## 2. 源码与 V2 接口

现有 V2 中 `LiveCodingRuntime.execute()` 调用 `_apply()`，然后通过 `self.verifier.run(verification)` 独立验证。P2 通过继承类覆盖 `_apply()` 并包装已有验证器，原有 `coding.py` **不必修改**，没有重复实现 Agent 调用与模型协议。

P2 具体做法：

1. `ScopedChangeJournal` 验证路径 `norm()` / `SafeWorkspace.preflight_write()`，禁止软链接、硬链接、重复操作；恢复前像需要实际 read_scope 权限。
2. 先校验权限与验证覆盖，再调用 V2 `_apply` 执行变更。
3. 原 V2 验证器在**一次性副本**中执行配置内的真实测试。
4. 若验证成功，关闭本次 journal，保留本轮修改，交给原 V2 Git 提交流程。
5. 若验证失败，回滚候选修改后，把明确标记的诊断和原始错误返回给原 V2 有限修复循环。
6. Reviewer 发起修复依然只针对原有授权的 TASK，不能指示 Backend 写入 `server/src/test/**`。

**重要边界**：日志分类是建议，不是通过验收的证据。只有独立验证全部 PASS 才能完成任务。此版本**不能证明** MySQL 服务层 exactly-once、支付真实链路、生产发布安全，也不是完整的系统隔离或跨进程原子事务。

## 3. 历史真实故障回归

证据来自 2026-10-18 GitHub Actions Run `39103687560` 的 `round_01/diagnostics/maven-test.txt`。

编译诊断：

```text
PointsService.java:[93,52] incompatible types:
java.util.Optional<java.lang.Long> cannot be converted to long
```

本包包含一个从真实 artifact 摘出的完整 Maven 日志测试 fixture。预期分类是 `JAVA_TYPE_ERROR`。它只给出明确的类型检查方向，**不猜测账户余额的默认值**：需遵循业务语义处理 `Optional<Long>`，并重新执行现有 Maven 门禁。

此测试是**离线故障复现/分类**；不代表新的 DeepSeek 三轮实际运行已获 PASS。

## 4. 放置文件

把本 ZIP 解压到 AgentForge 仓库根目录。本次只包含新增文件，主要为：

- `src/agentforge/repair_v3.py` — P2 运行时、诊断与事务式路径回滚
- `scripts/v3_p2_integrate.py` — 严格分支与结构校验的可选接入脚本，默认仅预览 diff
- `scripts/v3_p2_diagnose.py` — 只读诊断 CLI
- `tests/test_v3_repair.py` — 单元及模拟运行测试
- `tests/test_v3_p2_installer.py` — 接入脚本的隔离 Git 仓库测试
- `tests/fixtures/v20_run_39103687560_round01_maven.log` — 已发生的编译错误证据
- `docs/V30_SAFE_REPAIR_P2.md` 与 `PLACEMENT_P2.md` — 文档

只在单独分支上测试：

```bash
# 从已知稳定的实验基础分支创建，不改 PR #22
# 以下分支示例；如果已存在，就使用自己的 V3 实验分支
git switch -c feature/v3-safe-repair-p2

# 解压新增文件到仓库根目录后
python -m pip install -e ".[dev]"
pytest -q tests/test_v3_repair.py tests/test_v3_p2_installer.py

# CLI 离线诊断历史失败，不执行代码修改
python scripts/v3_p2_diagnose.py --log tests/fixtures/v20_run_39103687560_round01_maven.log
```

可选接入现有工程（**不会默认开启 P2**）：

```bash
# 默认 dry-run，显示要改的两个文件的精确 diff
python scripts/v3_p2_integrate.py --repo-root .

# 确认后才应用接入；只改 autonomous.py、cli.py，改动经逐项 marker 验证
python scripts/v3_p2_integrate.py --repo-root . --apply

# 此后使用独立、可丢弃的 fixture 测试运行，无推送、无自动 PR
agentforge autonomous-live "isolated test task" --repo-root /path/to/disposable/fixture \
  --profiles .agent/execution-profiles.yaml --v3-safe-repair
```

**不要**在生产仓库工作树里直接用真实模型运行自动修复；`autonomous-live` 是会在本地项目生成并提交代码的操作。必须使用隔离的测试仓库、可信配置、明确授权。默认不带 `--v3-safe-repair` 仍运行原 V2 代码。原 GitHub workflow 不会被 P2 自动触发。

## 5. 测试情况与待验收项

P2 开发时在与仓库关键接口匹配的本地隔离兼容环境中运行 38 项测试通过；P0+P1+P2 测试组合 75 项通过。**这不等于完整 GitHub 仓库 pytest、Java、Node、MySQL 或真实 DeepSeek 实测。**

正式合入之前仍需：

1. 在仓库对应 SHA 的独立 V3 分支运行 Python 3.11、3.12 全套 pytest + protocol 校验。
2. 试运行已有 V2 深度评测及独立 Node、Maven、Vite、MySQL schema/concurrency 行为门禁。
3. 验证真实 Reviewer 修复缺陷可以由 `SafeRepairRuntime` 正确阻止 Java 编译二次失败；必要时保留 BLOCKED，不降级验收。
4. 检查 V3 opt-in 模式和 V2 默认模式行为一致性、操作系统不同的文件模式及并发写入风险。
5. 未通过以上步骤之前，PR 保持 Draft，禁止合并及生产部署。

## 6. 威胁模型与不足

- 只支持受信任、隔离、没有其他进程并发写入的工作树；本地变更检测是尽力而为，不能替代跨进程排他锁、OS 沙箱或文件系统事务。
- 恢复时保留常规文件内容与权限位，不保证时间戳、ACL、扩展属性或自动删除新建的空目录。
- 若回滚途中发生 I/O 错误，可能出现部分文件已恢复。系统必须视为事故，人工检查，不能假定彻底回滚。
- 本 P2 不允许高风险权限变更，不负责训练自我改进策略；长期记忆与自优化属于后续 P3。
- 该包**没有**上传代码至 GitHub，没有触碰 `verify/v2.0-stability` / PR #22，亦未创建远程 workflow Run。

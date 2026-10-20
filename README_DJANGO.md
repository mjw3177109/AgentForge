# AgentForge Django · 运行入口

**目标：自主执行，可信交付。** Django 版是附加式工程管控层，
默认只读，不重构旧项目、不连接生产数据库、不自动提交生产修改。

## 5 分钟启动开发版（Python 3.11+）

1. 在该分支根目录安装：python -m pip install -e ".[django]"
2. 运行：python examples/django_host/manage.py migrate
3. 创建管理员：python examples/django_host/manage.py createsuperuser
4. 运行：python examples/django_host/manage.py runserver 127.0.0.1:8000
5. 打开 http://127.0.0.1:8000/admin/ 或 http://127.0.0.1:8000/agentforge/

要管理另一个受信任 Django 工作目录，设置环境变量
AGENTFORGE_ALLOWED_ROOTS 指向它的父目录（路径分隔符用系统 pathsep；
Linux/macOS 是冒号，Windows 是分号），重启后在 Admin 中登记项目并启用。

**先创建 AUDIT 任务**，任务创建不会自动执行。启动单次工作任务：
python examples/django_host/manage.py run_agentforge_job <任务 UUID>

VERIFY 会运行目标 manage.py 的 check/test：请只对受信任项目执行，
最好把整个 worker 放到断网、无生产密钥的容器/虚拟机里。

AUTONOMOUS 永远不会直接修改原项目，必须同时打开全局+项目授权，
并有人类批准（git HEAD、写入范围），只在临时 Git 克隆里执行。
模型通过 Reviewer 和 Django 独立验证后，也仅产出候选补丁供人工审核。
默认不开启。

完整说明见 docs/DJANGO_AGENT_MANAGER.md。

## V0.2 操作

完成迁移后可直接通过 `python examples/django_host/manage.py process_agentforge_queue --max-jobs 5`
处理最多 5 个待处理只读巡检任务。只有显式传入 `--include-verify` 才会执行
Django 业务测试；`--include-autonomous` 还需要人工审批和全局授权。

工作人员可在 `/agentforge/` 查看 30 天项目状态、任务列表、审计时间线。
如 Worker 意外停止，先确认进程不再运行，再使用
`python examples/django_host/manage.py recover_agentforge_job <UUID> --confirm-worker-stopped`
清理占用；中断的运行任务会标记 BLOCKED，不自动重试。

旧版审批不会自动继承授权，须重新申请并使用新任务。


## V0.3 — Agent Control Center

升级后不需要新的数据库迁移（沿用 V0.2 Schema）。

在 `http://127.0.0.1:8000/agentforge/` 查看新版控制中心：
- 项目总览：近期任务、状态、历史验证证据；
- 项目详情：独占执行锁、权限配置、对应任务；
- 任务详情：审计时间线、审批状态、独立验收结果；
- 仅超级管理员：创建待执行任务、受限人工审批、下载脱敏 JSON 证据。

**重要：** 网页只创建 PENDING 任务和写入受限审批记录，不调用 DeepSeek
执行代码。仍然必须由外部 Worker / 管理命令处理：
`python examples/django_host/manage.py process_agentforge_queue --max-jobs 5`

如要提交 AUTONOMOUS 任务，需要全局开关、项目开关、干净的 Git 工作树、
任务权限 YAML 和独立业务测试策略都满足限制；审批仅授权生成待审补丁。
模板与测试都不声明已经满足生产级隔离或真实 DeepSeek 三轮稳定性验收。


## V0.4：Docker Worker 安全验证

先从本分支安装依赖，再预先构建 Docker 验证镜像：
```bash
python -m pip install -e ".[django]"
docker build -t agentforge-django-verify:0.4 -f docker/Dockerfile.verify .
python examples/django_host/manage.py process_agentforge_queue --max-jobs 2 --include-verify
```

VERIFY 默认只允许 Docker 离线容器运行 `python manage.py check/test`；
镜像没准备好时会 BLOCKED，不会退回主机执行。被测试代码仅访问临时副本，
不能获得宿主机生产数据库、Docker socket 或 DeepSeek API 密钥。
需根据实际项目预装受信任的 Python 依赖镜像，不能让不可信项目在验证时安装软件。

**AUTONOMOUS 在 V0.4 默认阻断**，因为原核心中的代码生成期测试尚未完全
移入受控容器；单纯对生成结果做 Docker 测试不等于全链路安全。
确需在封闭、可信的开发环境使用旧模式，见安全设计文档中的危险开关。

真实 DeepSeek **只读策略 3/3** 入口：手动触发
`agentforge-django-v04-live.yml`，先配置 Actions Secret / Variables。
此入口不是完整自治编码 3/3，未运行不可声称 PASS。

细节与局限：[docs/DJANGO_AGENT_MANAGER.md](docs/DJANGO_AGENT_MANAGER.md)。

### 特别说明：独立分支上的 DeepSeek 测试入口

GitHub 的手动 `workflow_dispatch` 通常需要工作流文件已存在于默认分支。
本项目仍保持 `main` 不动，因此先在可信终端配置好 API 环境变量，再执行：
```bash
python scripts/run_django_v04_live_acceptance.py
```
仅显式运行时才实际调用收费模型。它验证的是三轮**只读策略决策**，
不是三轮完整的自动编码交付。未运行就保持 NOT_RUN/BLOCKED，不能伪造成功。


## V0.5 — 受限自动编码候选交付

V0.5 不会重新打开原 V2.0 的宿主机编码执行器，而是启用独立链路：

```
已授权的任务 → DeepSeek Planner → DeepSeek Executor → DeepSeek Reviewer
           → 受限全文件替换（临时副本） → 离线 Docker Validator
           → 人工审核候选补丁（绝不自动合并、发布）
```

新模块：`v05_broker.py`、`v05_coding.py`、`v05_fixture.py`。
只允许修改现有小型 Python 源文件，不允许修改测试、Django settings、
迁移、密钥或超出白名单的文件。Validator 由固定 Docker 命令独立运行，
不会执行模型自行指定的命令。

开发环境验证命令：
```bash
docker build -t agentforge-django-verify:0.4 -f docker/Dockerfile.verify .
python scripts/run_django_v05_smoke.py
```
这个 Smoke Test 使用**模拟 Agent 文本响应 + 真正的 Docker 业务测试**。
它不是付费 DeepSeek 测试。

在专用可信 Worker 的 Django settings 中，受人工审批后才可按需配置：
```python
AGENTFORGE_VERIFICATION_BACKEND = "docker"
AGENTFORGE_ALLOW_AUTONOMOUS = True
AGENTFORGE_V05_ISOLATED_AUTONOMOUS = True
AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER = True
AGENTFORGE_V05_ALLOWED_LLM_HOSTS = ("api.deepseek.com",)
```
此外还必须有单任务 `MutationApproval`、项目授权、干净 Git HEAD、
已配置离线镜像、真实源文件写入白名单及 DeepSeek API Key。
默认示例 settings 保持全部 OFF。

在明确同意付费并使用**固定的合成 Django 项目**时，可运行真实模型三轮：
```bash
python scripts/run_django_v05_live_acceptance.py --confirm-paid-calls
```
每轮调用三个真实模型角色并执行真正的 Docker 业务测试，总计正常为
9 次 API 请求；出错时可能更少。完整证据写入
`artifacts/django-v05-live/summary.json`。
此验收默认**不会运行**，没有 API Key 时不伪造结果。
它只证明合成案例，不证明实际业务项目达到 3/3 生产稳定性。


## V0.6 — 一次受限自愈 + 独立 Worker

V0.6 在 V0.5 受限编码路径上增加最多一轮自动修复：

```text
Planner → Executor → Reviewer → Docker check/test
                                     │
                                   失败
                                     ↓
                       Fixer（仅已有获批 Python 文件）
                                     ↓
                             Reviewer（再次审核）
                                     ↓
                          Docker check/test（再次独立验证）
                                     ↓
                          候选补丁 PROPOSED / FAIL
```

V0.6 每个任务最多 5 次模型角色请求、2 轮 Docker 验证、1 次修复。
Docker 命令固定，单条检查最长 90 秒；不会把原始测试日志或密钥
发送给 Fixer。实际货币费用没有测量，因此不能将其称为“人民币上限”。

默认所有 V0.6 开关仍为关闭：
`AGENTFORGE_V06_BOUNDED_REPAIR=False`、
`AGENTFORGE_V06_DEDICATED_WORKER=False`。开启需要原 V0.5 所有开关、
明确的项目人工审批和独立的可信 Worker 进程，并设置
`AGENTFORGE_WORKER_ROLE=trusted-dedicated`；该角色标记不能代替真正的 VM 隔离。

本地离线全闭环验收（脚本中模型是 Fake，但 Docker 检查是真的）：
```bash
docker build -t agentforge-django-verify:0.4 -f docker/Dockerfile.verify .
python scripts/run_django_v06_smoke.py
```

需向真实 DeepSeek API 支付费用的独立三轮合成样本测试：
```bash
python scripts/run_django_v06_live_acceptance.py --confirm-paid-calls
```
此命令默认不会由 push 自动启动。工作流文件
`.github/workflows/agentforge-django-v06-live.yml` 为手动入口，
可能需要存在于默认 GitHub 分支才可以触发，但我们尚未修改 `main`。

可信 Worker 的**演示配置**在
`examples/django_host/config/v06_worker_settings.py`，
独立 VM 配置、数据库及权限要求见 `deploy/v06/README.md`。
**它不是已部署的安全多租户 Worker**，不能给公开用户任意提交代码执行。


## V0.7 — PostgreSQL + 跨进程 Worker 临时集成验收

本阶段修复 **V0.6 真实 DeepSeek Broker 不接受 max_requests=5** 的缺陷，
增加 HTTPS 主机/端口校验，阻止授权令牌被误发往非 TLS 接口。

新增 `.github/workflows/agentforge-django-v07-staging.yml`：在 GitHub
Actions 的临时 Ubuntu Runner 上启动 PostgreSQL 和 Django 控制端，
再启动一个独立 Python Worker 进程，分别配置 Django Settings。
用一次真实的人类审批记录、真实 PostgreSQL 任务状态和真实 Docker
验证测试“初始业务失败 → 第一修复仍失败 → 第二修复成功”。
模型角色使用明示的 **Scripted Fake**，CI 不消耗 DeepSeek 费用。

- Worker 无真实 DeepSeek key，产生候选补丁，不合并、不发布；
- 控制端没有 Docker 运行入口，不开启自治执行开关；
- 两个进程共用临时 PostgreSQL，整个运行结束即销毁；
- 真实 Docker 从不共享 Git 源库、PostgreSQL 密钥和 Docker socket；
- 这是 **同一 GitHub CI 主机上的两个进程**，不是两个独立 VM。

实际部署独立服务器还需要服务器地址、数据库访问方式及凭据；
仓库中的 `deploy/v07/` 是可参考的部署文件而非已经启动的服务。

真实 DeepSeek 三轮测试仍需要显式授权和可用 API Key。
开发分支默认不自动付费、不伪造结果。GitHub 现阶段只开放
合成模型的临时 staging 验收。


### V0.7 安全部署示例补充

提供 `config.v07_control_settings` 和 `config.v07_worker_settings`
两个独立 settings，均要求 **远程 PostgreSQL + TLS verify-full + 可信 CA**。
systemd 服务模板现在默认引用 `v07_worker_settings`，缺少数据库
环境变量会直接失败，不再偷偷使用本机 SQLite。
这两份设置是部署准备文件，仍然需要用户已有的 VM、远程数据库、
证书和网络访问控制才能真正启动常驻服务。


## V0.8 · 候选补丁人工交付及执行锁诊断

## V0.8 — candidate patch handoff and lease observation

V0.8 adds a read-only superuser-only `GET /agentforge/jobs/<uuid>/candidate.patch`
endpoint. It downloads a **candidate** patch, never applies, merges, publishes
or modifies Git. Before returning bytes the server checks:

- task mode AUTONOMOUS, final status PROPOSED, unbroken audit hash chain;
- exact SHA-256 matches patch content and maximum 100 KB size;
- original approver is still an active staff superuser;
- original request and project configuration still match the human approval;
- scope unchanged, source file manifest 1–3 existing .py paths within approved scope;
- every patch header matches that original manifest;
- two passing offline Docker check/test results with positive business test evidence;
- result explicitly denies production release.

Failure is 403. This is a protected source-code export for human review, not
permission to run `git apply` automatically. Treat downloaded source as
confidential. Immutable commit anchoring and patch review remain human tasks.

Use `python examples/django_host/manage.py inspect_agentforge_leases --json`
to inspect live/stale-looking project locks. The suspected-stale flag is based
on **elapsed time only**, cannot prove a worker died, and never releases a
lock or retries a task. The existing explicit operator recovery remains the
only release path after an interrupted job.

V0.8 also suppresses a late stale Worker's final_gate event after manual
operator recovery. That worker's result is never resurrected. Do not run
a recovery command while a Worker is still alive; process termination must
be verified out-of-band.

### Acceptance remains separate

Django Python 3.11/3.12 unit tests and real Docker CI establish integration
correctness. The real DeepSeek 3/3 gated workflow remains OFF unless the
owner explicitly configures protected credentials and fee approval. No
persistent external VM has been provisioned by this patch.


## V0.9 — durable PostgreSQL worker heartbeat and bounded supervisor

V0.9 adds `JobLease.heartbeat_at` via migration 0004, and a dedicated
PostgreSQL heartbeat thread for **trusted Worker processes only**.
The remote worker settings turn it on (10s interval), while the
temporary GitHub CI worker uses a 1-second interval and verifies the
heartbeat independently alongside real Docker tests.

The heartbeat updates only the row matching the exact job and immutable
owner token. If the row disappears or its status ceases to be RUNNING,
the heartbeat is marked lost and finalization fails closed: no PASS or
PROPOSED status is permitted. PostgreSQL error or stopped heartbeat
also blocks finalization. Legacy SQLite demo remains heartbeat OFF;
attempting to enable heartbeat in SQLite is rejected before claiming a job.

`inspect_agentforge_leases --json` now reports `heartbeat_age_seconds`
and liveness `RECENT_HEARTBEAT`, `HEARTBEAT_OVERDUE_CHECK_PROCESS`, or
`UNKNOWN_LEGACY_NO_HEARTBEAT`, alongside lock age. Heartbeat staleness
is NOT proof a process died. No automatic lease stealing or retry exists.

For a dedicated Linux VM, an optional bounded **one-job** supervisor is
available:

```bash
python examples/django_host/manage.py supervise_agentforge_job <UUID> --timeout-seconds 900
```

It requires `AGENTFORGE_WORKER_ROLE=trusted-dedicated`, dedicated worker
settings, and PostgreSQL heartbeat enabled. It starts a child process and
terminates its Unix process group after timeout. The supervisor does NOT
reclaim the lease, retry, or assert Docker containers have terminated:
the Docker daemon may continue a container after its CLI exits. A human
operator must verify process/container state before using the existing
explicit `recover_agentforge_job` operation.

This is a reliability and fencing improvement, NOT a claim of hostile-code
microVM sandboxing or persistent VM deployment. The source/DeepSeek data
transfer permissions remain OFF unless explicitly authorized.


## AgentForge V1.0 — atomic Worker fencing and real-model failure attribution

**Candidate success and audit finalization are now one atomic database operation.**
Both the Worker and manual recovery lock `AgentJob` and then `JobLease`
in the same order. The Worker must still hold the *exact* owner token before
committing any final PASS/PROPOSED, and every worker audit event is also
fenced to a RUNNING job with its original lease. A recovered job's final
`operator_recovery` event cannot be followed by a late Worker success event.

If the ownership lease disappeared, V1.0 **leaves the job for operator
investigation**, never fabricates a success or takes ownership from another
Worker. Expired heartbeat or a heartbeat DB fault blocks candidate delivery.
The migration/heartbeat features from V0.9 remain unchanged.

V1.0 also adds read-only model readiness inventory and a typed, redacted
result classifier, used by the *opt-in* DeepSeek 3-round script:

```bash
python scripts/check_agentforge_v10_readiness.py \
    --output artifacts/agentforge-v10-readiness.json
```

The inventory **never calls DeepSeek or Docker**, and always reports
`real_deepseek_three_round_result: NOT_RUN`. It merely checks whether
necessary local settings/CLI are present; secret values are never printed.
Real DeepSeek API calls require the already-existing explicit paid-run gate,
and remain **NOT RUN** unless the user enables it. A true result report
distinguishes MODEL_TRANSPORT_OR_SCHEMA, POLICY_OR_PRECONDITION,
MODEL_REVIEW_REJECTED, INDEPENDENT_BEHAVIORAL_TEST_FAILED, and
VERIFICATION_INFRASTRUCTURE. It never serializes raw model prompts,
stdout/stderr or exception strings.

New CI tests cover the following *negative* cases: old Worker tries to
finalize after operator recovery, foreign owner token, missing lease,
heartbeat loss/expiry, and model/API error messages containing secrets.
PostgreSQL integration CI continues to check the actual cross-process
Worker + Docker candidate-only loop, and core regression checks stay on.

**Honest V1.0 boundary:** engineering CI passing is not real DeepSeek
3/3 coding stability, not a dedicated external VM deployment, not a
security-certified adversarial sandbox, and not production release permission.
No `main` merge or paid model call is automatic.


## V1.1 — 三类 Django 真实 Docker 基准与受控 DeepSeek 验收

V1.0 已经完成了 Worker/审计权限加固。V1.1 的重点是**扩大真实业务验收覆盖度**，
而不是把同一个 `add(a,b)` 简单算术题重复三次。

新增固定合成基准（全部为新建的测试项目，不使用用户业务代码）：
1. `arith-001`：正数、负数和零的计算；
2. `pricing-002`：折扣金额、100%/0% 边界、整数舍入；
3. `access-003`：对象拥有者、员工访问、未授权用户和匿名身份保护。

三套原始程序必须各自先在 **真实离线 Docker** 中出现业务测试失败；
之后每套由独立模型 Planner/Executor/Reviewer 或 Fixer 生成修复候选，
重新进入独立 Docker 检查。只有至少分别通过 3、4、5 条真实业务测试，
源代码与测试原件完全未改动、模型角色调用不超过每例 5 次，
结果才是 `PASS`。每例都报告源代码/测试摘要及候选补丁哈希。

在 GitHub Actions 或有 Docker 的环境先执行免费验收：

```bash
docker build -t agentforge-django-verify:0.4 -f docker/Dockerfile.verify .
python scripts/run_django_v11_offline.py
```

此命令仍使用 `SCRIPTED_FAKE_AGENT`，但 Django Docker 检查和业务测试
是真实执行的；即使全部通过也不能把 `real_model_verified` 标记为真。

明确同意 API 收费后，才允许配置真实 DeepSeek 环境变量并手工运行：

```bash
python scripts/run_django_v11_live.py --confirm-paid-calls \
    --output artifacts/django-v11-live/report.json
```

三个不同案例需要 3–5 次角色 API 请求/例，最多 15 次逻辑请求。
要求 `AGENTFORGE_LLM_API_KEY`、`AGENTFORGE_LLM_BASE_URL=https://api.deepseek.com`
和 `AGENTFORGE_LLM_MODEL=deepseek-chat`，以及预构建的 Docker 验证镜像。
付费的工作流 `agentforge-django-v11-live.yml` 额外受到 GitHub Repo 变量
`AGENTFORGE_V07_PAID_LIVE=I_APPROVE_THREE_DEEPSEEK_RUNS` 门禁保护。
默认 push 不触发付费任务。工作流通常需要位于 GitHub 默认分支才可直接
使用 workflow_dispatch；本次不改动 main。

验收分为 `模型/网络问题`、`Reviewer 拒绝`、`业务回归失败`、
`验证环境问题`、`初始缺陷未复现` 等。
输出仅包含脱敏的分数、计数、哈希和错误类别，不包含源代码、
提示词、API 密钥及测试原始日志。**3/3 合成基准通过不等于实际业务项目已
达到生产可用性，也不证明多租户恶意代码隔离。**


## V1.1 真实 DeepSeek 接口验收加强

本阶段增加**真实 HTTP 请求格式的离线契约测试**，检查 DeepSeek 请求地址、
Authorization、模型、`max_tokens`、请求失败扣额度和 429 不重试。
同时记录 API 返回的 `usage.prompt_tokens`、`completion_tokens`、
`total_tokens`，仅在提供方返回完整、合法数据时计数；
**没有 usage 字段绝不能声称 token 费用已测量**。

现有真实 DeepSeek 3/3 付费工作流仍然为显式 opt-in，
未启用时不会调用 API。HTTP 模拟测试不等于真实 DeepSeek 已通过。
生产 VM 与真实业务项目验收也仍独立。


## V1.2 — 真实模型三案例验收数据与人工对比报告

本阶段保留 V1.1 的三个真实 Django 基准：算术、整数折扣和对象权限，
不继续靠重复同一道题提升数字。每例都追踪 Planner、Executor、
Reviewer、Fixer 的调用结果，并记录角色请求数、经过一次修复的案例数、
Docker 业务测试的实际用例数。模型提示词、测试原始日志和 API
密钥绝不进入可公开的报告。

来自 DeepSeek API 的 token 字段只在服务器真正返回有效 usage 时汇总。
覆盖情况独立标为 COMPLETE、PARTIAL 或 UNKNOWN。部分失败请求
可能不会返回 token 统计，所以使用量不是完整费用凭证，
也不推断人民币或美元总费用。离线 ScriptedFakeAgent 的覆盖状态固定
为 NOT_APPLICABLE，绝不能声称真实模型通过。

免费验证：
~~~bash
python scripts/run_django_v11_offline.py
python scripts/render_django_v12_report.py \
  --input artifacts/django-v11/offline-report.json \
  --output artifacts/django-v11/operator-summary.md
~~~
Docker Smoke CI 使用真实 Docker 业务测试与脚本模拟 Agent，
输出 JSON 与 Markdown 两份证据。同一个验收逻辑被真实 DeepSeek
入口复用，真实运行时可执行：
~~~bash
python scripts/run_django_v11_live.py --confirm-paid-calls
python scripts/render_django_v12_report.py \
  --input artifacts/django-v11-live/report.json \
  --output artifacts/django-v11-live/operator-summary.md
~~~
第二段是**付费**模型调用入口，不会因为正常 git push 自动执行。
仓库原有 GitHub Actions 付费工作流仍有明确变量门禁。本次没有修改该
付费工作流，也没有触发它；任何实际模型验收结论必须同时检查对应
GitHub 运行日志及原始脱敏 JSON 证据。

V1.2 的 CI 通过只证明报告正确生成和现有工程回归稳定，
不证明真实 DeepSeek 3/3、持久化独立 VM 已部署或生产可用。


## V1.3 · 真实 DeepSeek 运行可信来源与可恢复证据

本阶段修正验收漏洞：不能只传入 `model_kind=REAL_DEEPSEEK`
就把脚本模拟 Agent 的成绩标记为真实模型成功。三案例实际运行器在
**调用模型之前**验证客户端必须是受限 `BoundedDeepSeek`
类型，并检查正式 HTTPS DeepSeek 接口、`deepseek-chat`、
禁重试设置、尚未消费的五次请求限额及密钥非空。
未通过校验时案例直接失败，整套报告 `real_model_verified=False`。

真实模式还会在第一笔模型 API 请求之前，先使用 Docker
**完整检查全部三个不同基准的原始缺陷**。其中任何一个不具备
合格的失败基线，直接停止且不产生付费调用。
这些检查只证明当前合成基准可执行，不是生产环境安全证明。

付费任务现在每完成一个案例就写入独立的
`checkpoint.json`，使用同目录临时文件和原子替换，
只包含固定白名单的案例编号、结果、错误类别和请求计数。
检查点明确标记 `INCOMPLETE_UNTIL_FINAL_REPORT`、
`real_model_verified=False`；流程中途崩溃不会把部分结果冒充 3/3。
最终报告仍是 `report.json`，不会包含原始源码、提示词或异常内容。
GitHub Actions 额外保留 Markdown 人工审查摘要。

真实付费工作流 `.github/workflows/agentforge-django-v11-live.yml`
已改为**仅可手动触发**，不再因修改这个文件而触发付费工作；
同时仍需要仓库管理员显式打开
`AGENTFORGE_V07_PAID_LIVE=I_APPROVE_THREE_DEEPSEEK_RUNS`
并提供 `AGENTFORGE_LLM_API_KEY`。在 GitHub UI 中，该工作流
通常需要先存在于默认分支才能使用 workflow_dispatch；
本阶段**不修改 main、不自动配置密钥、不授权付费**。

重要：运行时客户端类型检查只是防止误用的工程控制，
不是可独立验证的远程模型身份/消费证明。只有对应的 GitHub
执行日志和服务商账单/用量信息，才能进一步佐证实际 API 调用。
即使真实三案例 3/3，也不能据此认定已通过任意生产项目或恶意代码隔离测试。


## V1.4 — 独立验收证据一致性检查

本阶段先修复 V1.3 GitHub CI 的旧断言：
`tests/test_v11_cli.py` 过去错误地要求付费 workflow 必须包含
`paths:`。V1.3 已主动移除 push 触发，所以该测试现在明确要求
**只能 workflow_dispatch 且绝不包含 push 触发**。这保持了更安全的
“默认不产生费用”控制，不做回退。

新增：
- `src/agentforge_django/v14_evidence.py`：复核 3 个基准场景顺序、
  固定 manifest 指纹、源文件和测试文件的 SHA-256、实际测试数、
  模型角色请求数、单例/总体 PASS 一致性、token 来源标记和
  部署权限默认关闭；
- `scripts/verify_django_v14_evidence.py`：只读本地 JSON，
  不联网、不启动 Docker、不调用付费模型；输出原子写入且
  默认权限 0600 的 `v14-evidence-receipt.json`；
- `django_tests/test_v14_evidence.py`：包含伪造模型标签、
  篡改测试数、修改原测试文件指纹、虚报调用次数和
  伪造生产发布授权等拒绝用例。

运行命令（先要有 V1.2 的实际 JSON 报告）：
~~~bash
python scripts/verify_django_v14_evidence.py \
  --input artifacts/django-v11/offline-report.json \
  --output artifacts/django-v11/v14-evidence-receipt.json \
  --expected-model SCRIPTED_FAKE_AGENT --require-pass
~~~

真实 DeepSeek 手动工作流亦加入同一校验器，输出额外回执；付费
三案例运行依旧需要管理员明确配置密钥及授权变量才能触发，
本次**没有进行任何付费模型调用**。

**验收边界：** 这是“同一仓库中生成的报告和预置基准是否自洽”的
校验，不是第三方签名，不是服务商身份或 API 消费的独立证明。
操作者若能同时改写报告和校验器，SHA-256 不能阻止其伪造。
验证真实 DeepSeek 使用情况仍需对照对应 GitHub Actions
运行记录、API 服务商用量账单及可信执行环境。也不是已完成
持久 VM 生产部署或对抗性沙箱安全认证。



## V1.5 — 模型角色顺序和 Token 证据强一致性

V1.4 的验收回执已经具备固定基准 manifest、源码/测试哈希、
Docker 正向业务测试数和总体报告防篡改校验。V1.5 进一步校验：

- PASS 必须完整对应 `Planner → Executor → Reviewer`，或者仅一次
  修复时对应 `Planner → Executor → Reviewer → Fixer → Reviewer`；
  同时强制每个角色的 schema 接受状态为成功；
- 模型角色请求数、允许的修复次数和独立 Docker 验证轮数必须一致；
  任意删除 Reviewer、虚增调用次数、伪造二次验证都将拒绝 PASS；
- 来自真实 DeepSeek 的使用量必须满足 coverage、
  `provider_usage_reports`、逐案例 token 和总 token 的一致性；
  未报告的模型费用继续保留 UNKNOWN，不能自动被认作 $0；
- 全套角色计数、单次修复成功案例、缺失调用数必须与案例级记录一致。

新增 `django_tests/test_v15_consistency.py`，覆盖伪造角色轨迹、修复数、
Docker 验证数、token 覆盖率及合法无修复/一次修复路径。

验收仍然仅检查报告内部的逻辑一致性，不能证明模型供应商身份、
防止同一操作者同时伪造报告和校验程序，也不意味着独立云 VM 已部署。
真实 DeepSeek 三案例仍未在本阶段运行，原有手动付费门禁不变。


## V1.6 — Docker 测试防篡改写入屏障

本阶段修复独立验证器的真实安全隐患：此前容器虽然指定
`--read-only`，但项目代码挂载 `--mount type=bind` 默认仍可写。
恶意候选代码可能在 `manage.py check` 阶段修改临时业务测试文件，
继而影响 `manage.py test` 的真实通过结果。

修复方式：
1. Docker 项目挂载现在显式使用 `dst=/workspace,readonly`，
   禁止容器内对任何项目文件的新增、删除、覆盖；
2. 拷贝后的目录/文件权限从 `0777/0666` 收紧为 `0755/0644`，
   不再给非特权测试用户额外写权限；
3. 对临时工作区完整文件清单、路径和字节内容计算 SHA-256 指纹，
   每条 Docker 检查执行前后校验；发生任何文件篡改，
   立即设置 `VERIFICATION_WORKTREE_MUTATED`，不执行后续测试；
4. 增加真实 Docker 攻击测试：候选代码在 `check` 阶段尝试覆写
   `app/tests.py`，必须失败；合法修复仍必须成功通过 Django
   正向业务测试。原始项目不会被修改。

测试：
~~~bash
docker build -t agentforge-django-verify:0.4 -f docker/Dockerfile.verify .
python scripts/run_django_v16_write_barrier_smoke.py
~~~

安全边界：只读挂载是防止验证阶段改写测试的保护，
**不是**恶意代码不可突破的内核级隔离；Docker daemon 或宿主被控制、
测试本身有逻辑漏洞、模型假造行为等问题仍需要更强独立 VM/
微虚拟机、可信镜像摘要、审计与人工审批。实际 DeepSeek 付费调用
及持久 VM 部署仍未执行，本阶段不将测试脚本称为真实模型验收。


## V1.7 — 防止 Docker 验证镜像标签被替换

`docker_verification` 现在先使用本地 Docker Engine 查询
`image inspect --format '{{.Id}}'` 获取 **sha256:64 位**镜像配置 ID，
验证格式后使用该 ID（而不是可变的 `agentforge-django-verify:0.4`
标签）执行后续 `check` 和 `test`。两轮任务复用同一个镜像 ID；
检查到不存在、格式异常、与预先批准 ID 不一致均拒绝运行，不自动
pull、build 或执行本地宿主测试。

**持久 Worker 配置** `config.v07_worker_settings` 现在
强制要求 `AGENTFORGE_DOCKER_VERIFY_IMAGE_ID=sha256:...`；
在专用 VM 上先审核构建来源/镜像内容，再执行：

~~~bash
docker image inspect --format '{{.Id}}' agentforge-django-verify:0.4
~~~

将返回的完整镜像 ID 作为 Worker 的受保护环境变量。服务启动后，
标签被指向另一个镜像时会直接阻断。设置只能由 VM 操作员维护；
不用客户项目源码或 LLM 输出来设置 pin。

新增 `scripts/run_django_v17_image_identity_smoke.py` 在真实 Docker
上验证正确 pin 可通过、错误 pin 必须被阻止，并核对返回证据与
实际镜像 ID 一致。附加离线测试模拟镜像标签变化及无效 Docker
响应，确认验证脚本不能绕过 ID 检查。

**边界：** Docker 镜像 `.Id` 是本地 image config/content ID，
**不是** registry manifest digest、签名校验、SBOM 或 Docker daemon
可信性证明。本阶段未部署独立持久 VM，亦未触发真实 DeepSeek 付费请求。


## V1.8 — 专用 Worker 启动预检（不调用付费 API）

新增 `python examples/django_host/manage.py check_agentforge_worker --mode dedicated --json`。

预检 **只读** 检查：独立 Worker 角色和显式部署许可、关闭旧版宿主执行功能、
可信项目根目录、远程 PostgreSQL 的 TLS `verify-full` 配置、
**实际 PostgreSQL SELECT 1**、AgentForge Django migrations 全部已安装、
已开启数据库心跳、已审批 Docker 镜像 SHA-256 ID 与本机镜像一致、
以及 Worker 的 DeepSeek 密钥仅在受信任进程存在。输出
`ready_to_accept_candidate_only_jobs` 和固定错误码，不打印密钥、模型提示词、
数据库密码或用户项目源码。

服务模板 `deploy/v07/agentforge-worker.service` 已加 `ExecStartPre`：
检查失败就阻止 Worker 接单，不执行迁移、不自动拉镜像、不修改 Git。
可在专用 Linux VM 上使用以下命令验收（需事先配置已批准的环境文件）：

~~~bash
DJANGO_SETTINGS_MODULE=config.v07_worker_settings \
python examples/django_host/manage.py check_agentforge_worker --mode dedicated --json
~~~

GitHub CI 则在**临时同主机环境**使用 `--mode ci-staging`，它只接受
`CI=true`、隔离的测试 PostgreSQL localhost 和无 DeepSeek Key；
在真正执行合成任务之前，单独启动 Django Worker 预检进程并验证
全部检查成功。缺数据库、迁移、镜像身份或权限时会先拒绝接单。

**没有**因通过 CI 而宣称独立持久 VM 已部署、外部 PostgreSQL 已 provision，
也没有真实 DeepSeek 三案例付费运行。此命令验证的是准备条件，
不能证明 Docker 守护进程未被入侵或 VM 物理独立，也不自动开启生产发布权限。


## V1.9 — Docker 残留容器与超时恢复门禁

所有 Django 验证容器带 `org.agentforge.verifier=django-offline` 标签。
每次 check/test 后不仅执行 `docker rm -f`，还通过独立 Docker
`ps -a` 检查**精确容器名**确实消失。如果 Docker 清理无法验证，
当前测试以 `DOCKER_CLEANUP_UNVERIFIED` 失败，即便业务测试返回 0
也不交付候选补丁。

Worker 启动预检从 **11 项增加到 12 项**：检查 Docker 内所有带此
标签的容器，包含已停止者；如果存在遗留容器或查询失败，则
`VERIFIER_CONTAINERS_PRESENT_OR_UNKNOWN`，拒绝接单，不自动删除。

只读运维命令：
~~~bash
python examples/django_host/manage.py inspect_agentforge_containers --json --fail-if-any
python examples/django_host/manage.py inspect_agentforge_leases --json
python examples/django_host/manage.py check_agentforge_worker --mode dedicated --json
~~~

systemd 服务增加 `KillMode=control-group` 与 `TimeoutStopSec=30`，
禁自动重启。但独立 Docker 守护进程中的容器可能继续运行，因此
恢复前仍必须人工确认旧 Worker 已完全停止、Docker 残留已被安全处置，
再执行 `recover_agentforge_job --confirm-worker-stopped`。
详见 `deploy/v19/README.md`。

新增真实 Docker CI 创建一个未运行的标记容器，验证只读扫描能查到，
随后手动清理并确认扫描归零。没有运行真实 DeepSeek，
也没有部署专用远程持久 VM；Docker daemon 不可信时这些检查
不能作为独立安全证明。


## V2.0 — 专用 Worker 正式接入独立子进程监督

先前有 `supervise_agentforge_job`，但 systemd 仍使用直接执行
Agent 的队列命令，没有把超时监督接入真实生产路径。现在改为：

`ExecStartPre check_agentforge_worker`（12 项安全预检） →
`process_agentforge_supervised_queue`（最多选取 1 个任务） →
`supervise_agentforge_job`（新的 OS 进程组） →
`run_agentforge_job`（只生成候选补丁）。

Worker 子任务默认超时 **780 秒**，systemd 服务总启动超时
**960 秒**。命令本身和子进程监督器都要重新通过启动预检；
旧的 `process_agentforge_queue` 在专用 Worker 设置下不能直接
执行 VERIFY/AUTONOMOUS，从而减少绕开限时监督的风险。

超时后向子进程组发送 TERM，必要时 KILL，失败结果保持失败；
**不自动重新执行、不抢执行锁、不清理未知 Docker 容器、不部署代码**。
管理员仍需核实进程与 Docker 容器后按 V1.9 手册人工恢复。

V2.0 临时 PostgreSQL CI 新增真实的受限子进程执行只读 AUDIT
任务，并验证审计链、没有遗留 lease、不修改原仓库。
模拟 Agent 的代码修复仍独立使用真实 Docker 测试。
本阶段没有部署独立持久 VM，也没有触发收费 DeepSeek API。


## V2.1 — 真实 Linux 进程树超时处置验收

修复 V2.0 监督器的一项边界：直接子进程收到 SIGTERM 后可能很快退出，
但忽略 SIGTERM 的孙进程仍然存活。现在无论直接子进程是否提前退出，
**都会向原始进程组发送最终 SIGKILL**，并通过 Linux /proc
查验该进程组是否还有可执行进程。查询失败或进程仍存在时，
必须返回 `WORKER_TIMEOUT_PROCESS_EXIT_UNVERIFIED`，不接受正常
完成的结论；直接子进程返回 0，但仍有活跃子孙进程时，也拒绝
成功，并尝试清理原进程组。只有可验证为无活动进程时，才能把
OS 进程组处置状态视为结束；原任务超时仍然属于错误状态。

新增真实 Linux CI 测试：启动独立 session 的合成 Python 子进程树，
分别演练“主进程忽略 TERM”与“主进程收到 TERM 退出，孙进程忽略 TERM”。
脚本没有模型 API、用户源码、数据库写入或 Docker 调用；并额外
覆盖信号失败、超时、异常进程 ID 的单元回归。

~~~bash
python scripts/run_django_v21_supervisor_smoke.py
~~~

本阶段验证的是 **同一 POSIX 进程组** 内的进程清理。
恶意代码主动调用 `setsid` 脱离原进程组、Docker daemon 容器、
外部数据库任务、内核/VM 越权等无法由此保证终止。
发生超时后仍必须按 `deploy/v19/README.md` 人工核实
OS、Docker 容器和 lease；不得自动重试、回收执行锁或上线。
也不代表已部署独立持久 VM，或真实 DeepSeek 3/3 已执行。


## V2.2 — Linux 子进程收养、脱离进程组的遗留进程防误判

V2.1 已能终止原始 OS 进程组，但原任务可以启动调用 `setsid`
的孙进程，主动进入另一进程组。即使最初的子进程返回 0，
这类子孙进程也可能继续运行。V2.2 增加仅用于专用受信任 Linux
Worker 的 `PR_SET_CHILD_SUBREAPER`：单任务 supervisor 在启动
前要求没有其他子任务，并将意外孤儿子进程收养到监督进程名下。
退出或超时后读取 Linux `/proc/self/task/*/children` 检查已被
收养的任务后代，通过 `pidfd_open` 加
`pidfd_send_signal(SIGKILL)` 安全发信号并使用精确 `waitpid` 回收。
其目的在于避免复用 PID 误伤别的进程。至少持续一个安静窗口确认
没有活动/僵尸子进程，才能认为已清理。

如果发现逃逸后代，即使最终成功清理，也不接受原任务作为
正常成功；返回 `WORKER_ESCAPED_DESCENDANT_DETECTED`，候选交付
继续要求人工检查。无法启用 Linux subreaper、缺少 pidfd 支持、
无法读取 /proc 或清理超时，都 **fail closed**，不会退回旧的
仅进程组验证逻辑。

在 Linux CI 上执行两个**真实操作系统进程**场景：一是主进程
正常退出但留下 setsid 逃逸进程；二是主进程超时且后代主动
setsid；两者都须被收养检测、杀死并回收，不触及 Docker、
客户源码、PostgreSQL 或 DeepSeek API。

~~~bash
python scripts/run_django_v22_setsid_smoke.py
~~~

边界：没有能力发现刻意逃离操作系统 cgroup/namespace 并由其他
受信任守护进程创建的子进程；也不能控制 Docker daemon 中独立
存活的容器。生产仍建议使用 systemd `KillMode=control-group`
作为第二层保护，并按 V1.9 操作手册人工核对 Docker 残留和 lease。
**未部署独立常驻 VM、未进行真实 DeepSeek 三案例付费验收。**

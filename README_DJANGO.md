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

# V0.7 Worker — deployment boundary

This folder provides deployment templates and an ephemeral CI smoke test.
It does **not** provision or deploy any VM, production PostgreSQL, cloud
project, persistent queue daemon or real DeepSeek request.

## What really runs in GitHub CI

The v07 staging workflow starts PostgreSQL 16 as an Actions service,
a Django HTTP subprocess with control-only settings, and a separate
trusted Worker subprocess using the same test DB. An approved synthetic
task exercises Planner, Executor, Reviewer, one Fixer, second Reviewer
and two REAL offline Docker Django check/test rounds. The model is
`FakeRepairModel` and no LLM API key is used. No user project is read.
CI ends by destroying the temporary worktree and DB.

This proves cross-process Django/PostgreSQL handoff and the original
source remaining untouched. All processes still live on the SAME
GitHub runner host: this does not prove VM/hostile-code isolation.

## Actual persistent Worker — not deployed by this task

On an explicitly provided trusted VM (not the web app machine):

1. Provision a dedicated Linux VM, Docker daemon restricted to VM, a
   private database reachable over verified TLS, and read-only access
   to allowlisted trusted Django repositories. Create a dedicated
   `agentforge` OS account and protect the workers' source tree.
2. Install `python -m pip install -e ".[django,staging]"` and vet a
   pinned Docker verifier image with target app dependencies installed.
3. Configure Django DATABASES for the remote PostgreSQL database.
   **Do not use CI-only v07_staging settings**: these refuse remote
   database hosts and require `CI=true`.
4. Keep API tokens only in the trusted Worker secret manager, never
   in the public Django web app, Git repository or Docker validator.
5. Install a protected root-owned environment file in
   `/etc/agentforge/v07-worker.env` (mode 0600), or preferably use
   systemd credentials/secret management. Do not commit it.
6. Run an explicit one-shot worker on a private host:
   ```bash
   DJANGO_SETTINGS_MODULE=config.v06_worker_settings \
   python examples/django_host/manage.py process_agentforge_queue \
       --max-jobs 1 --include-autonomous
   ```
   V0.6 settings require explicit role, strong Django key and
   allowlisted roots. Your production settings must also replace
   demo SQLite and configure production-safe PostgreSQL TLS.
7. Only after OS/microVM isolation and network policy reviews should
   the operator install the optional systemd unit/timer in this folder.
   It is disabled unless an operator actively enables it.

Do not mount Docker daemon socket into public web. A Docker-capable
Worker is powerful on its VM. Generic Docker is not malicious
multi-tenant isolation; no production-readiness assertion is made.

To run REAL DeepSeek 3-round synthetic-fixture tests, use the manual
paid-acceptance script only with an expressly approved API key; success
on that fixture does NOT prove a real customer's Django project.


## Production deployment settings (new V0.7 fail-closed example)

The systemd unit now uses `config.v07_worker_settings` instead of the
V0.6 SQLite demo. It REFUSES to start until:

- `AGENTFORGE_V07_PRODUCTION_WORKER_CONFIRM=I_DEPLOY_IN_DEDICATED_VM`;
- `AGENTFORGE_V06_ENABLE_WORKER=I_ACCEPT_DEDICATED_WORKER`,
  `AGENTFORGE_WORKER_ROLE=trusted-dedicated`;
- a strong `DJANGO_SECRET_KEY` and explicit `AGENTFORGE_ALLOWED_ROOTS`;
- external `AGENTFORGE_PG_HOST`, `_NAME`, `_USER`, `_PASSWORD`;
- `AGENTFORGE_PG_SSLMODE=verify-full` and a valid local CA cert file at
  `AGENTFORGE_PG_SSLROOTCERT` (no localhost or plaintext fallback).

For the public Django web host, `config.v07_control_settings` reuses the
same verified remote DB but keeps all autonomous execution flags disabled.
It requires HTTPS reverse proxy, `AGENTFORGE_WEB_ALLOWED_HOSTS`,
and contains NO LLM API key or Docker socket. It may only queue/approve.
**Both hosts must refer to the same Git revision and provide a trustworthy
read-only view of the approved project source** for initial Git approval and
worker execution. This synchronization is not automated in this repo;
do not claim a production rollout without verifying it.

The supplied one-shot systemd timer is deliberately not enabled by CI.
It cannot establish container/VM security just by setting environment flags.


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

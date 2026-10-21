# AgentForge V1.9 — manual recovery runbook

No persistent VM is provisioned by this repository. Execute all commands on
the trusted Worker VM, never in a public web container.

**Startup**: verify protected PostgreSQL/CA settings, model-key isolation and
operator-approved Docker image; use
`manage.py check_agentforge_worker --mode dedicated --json` and require
all **12/12** checks. The check includes an empty Docker orphan inventory.

**After an unexpected crash, timeout, or reboot:**

1. Stop `agentforge-worker.timer` and `agentforge-worker.service`.
2. Inspect OS processes and confirm the OLD worker and children truly stopped.
   An expired database heartbeat is not proof of process termination.
3. Run `manage.py inspect_agentforge_leases --json` and
   `manage.py inspect_agentforge_containers --json --fail-if-any`.
   Independently inspect `docker ps -a --filter
   label=org.agentforge.verifier=django-offline`.
4. Only after identifying an obsolete *exact* generated container name may
   the operator manually remove that container with
   `docker rm -f -- <exact-container-name>`; do not blind-prune.
5. Rerun the orphan inventory. It must be empty. Verify no remaining worker
   process or detached Docker process belongs to the interrupted job.
6. THEN run `manage.py recover_agentforge_job <job_uuid>
   --confirm-worker-stopped`. The interrupted job is BLOCKED, never
   automatically resumed or deployed.
7. Run the dedicated preflight again before re-enabling the timer.

The service config sets `KillMode=control-group`, `TimeoutStopSec=30`,
`SendSIGKILL=yes`, and `Restart=no` but systemd process groups cannot
guarantee that a Docker daemon container has exited.

Docker daemon access confers strong host privileges; image config SHA IDs are
not signatures. This workflow does not certify malicious-code isolation.


## V2.3 — 重启后遗留执行锁阻断与 systemd 部署配置检查

新增 **第 13 项** Worker 启动门禁 `no_prior_worker_leases`：
在真实 PostgreSQL 连通、模型密钥环境与 migrations 检查合格后，
只读查询 `JobLease.objects.exists()`。任何仍存在的执行锁——
无论心跳新旧、任务是否已结束——都阻止启动并返回固定错误码
`ACTIVE_OR_STALE_WORKER_LEASE_REQUIRES_OPERATOR`。数据库检查异常
也按失败处理；只有明确无租约才进行 Docker 镜像与容器检查。
这样 systemd timer 在机器重启/进程崩溃后不能擅自越过历史事故，
开始另一项任务。当前设计按**单个受信任 Worker 独占整个队列**
运行；多台生产 Worker 并发需要另行设计可靠的全局调度策略。

临时 PostgreSQL CI 新增真实独立进程故障演练：完成原始合成任务后，
向真实数据库插入上轮任务留下的 lease；新启动预检须拒绝，
操作者模拟确认已退出的合成进程后**显式**调用旧版人工恢复逻辑，
核实数据库执行锁删除、审计链有效且原任务没有自动重试；
随后新进程预检应恢复通过。CI 不会将此认定为生产环境已演练。

增加 `scripts/check_django_v23_systemd.py` 的**离线配置合同检查**，
禁止删除 `ExecStartPre`、回退未受监督的队列入口、
开启自动重启、取消 `KillMode=control-group`、将 timer
改为 `Persistent=true`，以及削弱 OS 账户和 systemd 安全参数。
对应测试覆盖恶意配置变更和重复指令，检查不修改服务、不联系 Docker
或 PostgreSQL。

~~~bash
python scripts/check_django_v23_systemd.py
python examples/django_host/manage.py check_agentforge_worker --mode dedicated --json
python examples/django_host/manage.py inspect_agentforge_leases --json
~~~

生产恢复必须首先停止并人工核实旧 Worker 的全部 OS 进程、
Docker 容器，再确认 lease 所属任务；绝不能因为心跳过期就自动清理。
`recover_agentforge_job --confirm-worker-stopped` 仍需要操作者承担
确认责任，且不会自动运行任务或发布补丁。

**限制：** systemd 检查只读取仓库中跟踪的静态模板，
无法检测实际 VM 上的 drop-in overrides 或服务运行状态；
GitHub 集成 CI 的 PostgreSQL 与 Docker 运行在临时 runner 中。
未部署独立持久 VM、未验证远程生产数据库 TLS 会话、未执行收费
DeepSeek 三案例。下一步仍需专用服务器权限及付费授权。

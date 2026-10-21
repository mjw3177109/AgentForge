# AgentForge V2.4 — stage-only, real-host systemd verification

This is a handoff package for a **separately provisioned dedicated Linux VM**.
No VM, paid DeepSeek account or remote PostgreSQL is provisioned by this
repository. NEVER stage the Docker-capable Worker on the public web host.

## Prerequisites (operator must verify)
- Source tree at /opt/agentforge/AgentForge, reviewed commit SHA.
- Private venv at /opt/agentforge/venv/bin/python; agentforge Unix user.
- Root-owned /etc/agentforge/v07-worker.env with protected permissions;
  no secrets in the Git repository or CI artifacts.
- Approved Docker image SHA256 ID, separately restricted Docker daemon.
- Remote PostgreSQL with authenticated TLS verify-full, trusted CA and
  migrations already completed under a separate explicitly approved operation.
- The trusted Worker preflight is required to pass 13/13 before any job.

## Staging — will NOT start or enable the timer

```bash
python3 scripts/check_django_v23_systemd.py
sudo bash deploy/v24/stage_units.sh --stage-reviewed-units
python3 scripts/audit_django_v24_systemd_host.py \
  --output /tmp/agentforge-v24-installed-units-audit.json
systemctl cat agentforge-worker.service
systemctl cat agentforge-worker.timer
```

The staging script refuses installed/existing unit files or overrides rather
than overwriting them. It validates the reviewed source unit files, installs
fresh copies under /etc/systemd/system, and calls daemon-reload only.
If a partial installation remains after a failure, investigate manually.

The read-only audit checks exactly which unit files systemd currently exposes,
that no drop-in override is present, NeedDaemonReload=no, service inactive and
timer disabled. It never reads secret environment-file contents, starts a
service, enables a timer, modifies a DB or calls the model. Failures generate
fixed codes without raw systemctl messages.

A passing V2.4 audit is **not** permission to turn on autonomous execution.
Review all preflight gates and cloud/security costs in an independently
approved manual activation step. The same-worker CI tests do not demonstrate
a deployed persistent VM or a live DeepSeek 3/3 acceptance.


## V2.5 — Worker VM 运行账户与密钥保护、首次安装失败恢复

V2.4 的首次安装脚本还不能核实 Linux 主机上 Worker 的代码是否可以
被普通用户修改、是否有受保护的私有 Python 环境，以及
`/etc/agentforge/v07-worker.env` 是否可能被其他用户读取。
V2.5 新增独立只读脚本：

~~~bash
python3 scripts/check_django_v25_host.py
~~~

验证五项：`agentforge` 是非 root OS 用户；仓库主目录和父目录受
root 控制且禁止组/其他人写入；Django 主程序与源码目录不可被非 root
用户修改；受信任虚拟环境的 Python 可执行文件及 bin 目录受保护；
**Worker 私密环境文件必须是 root 所有、0600、非符号链接、单硬链接、
父目录不允许其他用户写入**。从不打开或解析密钥文件内容，
不写磁盘或数据库，不连接 Docker、PostgreSQL 或 DeepSeek。

首次部署脚本 `deploy/v24/stage_units.sh` 现在在碰触
`/etc/systemd/system` 之前自动调用上述检查，并通过独占
`flock` 阻止两个安装流程并发。安装若中断，会尝试回滚本次
新创建且字节内容仍和审查模板一致的 service/timer，并
`daemon-reload`；发现文件内容已经变更、符号链接或无权限时，
**不会删除未知文件**，要求管理员人工检查；不是跨两个文件的
内核级原子事务。首次安装仍需显式 `--stage-reviewed-units`，
不得覆盖既存 unit，不启动或启用任何服务。

在已由独立管理员审核的专用 Linux VM 上：

~~~bash
python3 scripts/check_django_v23_systemd.py
python3 scripts/check_django_v25_host.py
sudo bash deploy/v24/stage_units.sh --stage-reviewed-units
python3 scripts/audit_django_v24_systemd_host.py
~~~

当前检查重点是本地文件元数据，并**不能**确认源代码每一个文件的
供应链签名、证明运行位置是独立 VM、或远程 PostgreSQL TLS 握手
真正完成。也未执行真正付费 DeepSeek API 或自动激活 Worker。

# V2.3 — Worker restart interlock and systemd contract

This repository DOES NOT provision a persistent VM. No model API is called
by these checks.

## Pre-enable verification on a dedicated Worker

```bash
python scripts/check_django_v23_systemd.py
python examples/django_host/manage.py check_agentforge_worker --mode dedicated --json
python examples/django_host/manage.py inspect_agentforge_leases --json
python examples/django_host/manage.py inspect_agentforge_containers --json --fail-if-any
```

Require **13/13** startup checks. The extra check denies ANY residual lease,
including a lease with an overdue heartbeat or finished job status.
It cannot establish that the old process exited merely by checking the DB.

If a lease remains after a service crash, DO NOT restart the timer. Stop
timer+service, verify all original OS processes and Docker containers have
been accounted for (see deploy/v19/README.md), then explicitly recover the
specific job using the existing trusted operator command. Repeat preflight.

The static systemd contract validator checks the checked-in files only.
Before enabling in a real VM, separately review `systemctl cat
agentforge-worker.service`, `systemctl cat agentforge-worker.timer`,
drop-in overrides, actual service user/permissions, database TLS,
cgroup behavior and logs. Do not enable timer before an operator approves.

CI includes a real ephemeral PostgreSQL abandoned-lease/recovery drill.
This DOES NOT demonstrate VM reboot, persistent host isolation,
live provider identity, or production incident recovery.


## V2.4 — 专用 VM 上的 systemd 实际安装验收

之前 V2.3 只能校验 GitHub 仓库里的 systemd 模板，不知道实际服务器上
安装的 unit 是否被替换、通过 drop-in 覆盖、是否忘记 reload 或已经
意外启用了 timer。V2.4 新增两个仅供专用 Linux VM 管理员执行的工具：

1. `deploy/v24/stage_units.sh` 默认只显示帮助或拒绝执行；
   管理员显式加 `--stage-reviewed-units` 并以 root 执行时，
   检查 systemd、现有服务未启动、服务文件/覆盖目录不存在，
   调用 V2.3 静态配置检查及 `systemd-analyze verify` 后，
   **仅首次安装**审查过的 service 和 timer，并 `daemon-reload`。
   不启动、不启用、不做迁移、不联系模型 API。
2. `scripts/audit_django_v24_systemd_host.py` **只读**查询
   `systemctl cat/show`，检查其实际加载的 unit 路径为
   `/etc/systemd/system`、原始文件与审核模板一致、无 drop-in、
   不需要 daemon-reload、服务处于 inactive，且 timer 为 disabled。
   只输出固定验收错误码，不输出 EnvironmentFile 密钥、日志或原始
   systemctl 内容；可保存权限 0600 的 JSON 回执。

在**已经由管理员单独建立且经审查**的 Linux VM 上，先安装
Python、项目虚拟环境、专用 `agentforge` 用户、专有 Docker、
经 TLS verify-full 连接的 PostgreSQL、审批后的镜像 ID 与私有
环境配置文件。确认 `/opt/agentforge/AgentForge` 和
`/opt/agentforge/venv/bin/python` 可用。然后：

~~~bash
python3 scripts/check_django_v23_systemd.py
sudo bash deploy/v24/stage_units.sh --stage-reviewed-units
python3 scripts/audit_django_v24_systemd_host.py \
  --output /tmp/agentforge-v24-installed-units-audit.json
~~~

**此时仍不应开启 timer**。下一步必须另外在生产 Worker 的正确
受保护环境下通过 `check_agentforge_worker --mode dedicated --json`
的 13/13 检查，并人工审查实际 `systemctl cat`、Docker 权限、
数据库迁移、VM 隔离和成本授权，才能讨论人工启用。
工具从不把“systemd 文件正确安装”说成“Worker 生产准备通过”。

注意：这套首次安装工具对已经安装的 unit **明确拒绝覆盖**；
失败后若部分文件已存在，必须由管理员核对再处理，不能盲目重跑。
systemd 的实际状态检查依赖可信 Linux 主机，不能防止 root/
systemd 守护进程本身被攻击。GitHub Actions 只测试检查器和脚本，
不会在真实持久 VM 上执行它们；亦不做付费 DeepSeek 请求。

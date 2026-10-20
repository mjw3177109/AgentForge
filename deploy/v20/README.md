# AgentForge V2.0 bounded supervision

**No external VM is created by this repository.**

Production chain: systemd ExecStartPre (12 read-only security checks)
-> process_agentforge_supervised_queue (one pending task)
-> supervise_agentforge_job (bounded process group)
-> run_agentforge_job (candidate-only result).
Use 780s per job, 960s systemd TimeoutStartSec.

```bash
python examples/django_host/manage.py check_agentforge_worker --mode dedicated --json
python examples/django_host/manage.py process_agentforge_supervised_queue --mode dedicated --include-autonomous --timeout-seconds 780 --json
```

An expired heartbeat is NOT evidence that old processes or Docker containers
have stopped. Follow deploy/v19/README.md before manual recovery.
The CI PostgreSQL test exercises real bounded OS supervision of a synthetic
read-only AUDIT job. It does not prove independent VM or paid DeepSeek tests.


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

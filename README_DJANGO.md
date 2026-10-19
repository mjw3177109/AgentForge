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

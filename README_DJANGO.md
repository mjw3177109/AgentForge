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

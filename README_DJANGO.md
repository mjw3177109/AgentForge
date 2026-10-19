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

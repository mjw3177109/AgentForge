# V3.0 P1 增量安装清单

前置版本：AgentForge V2.0 基线；可以共存 P0，但本包 **只包含新增文件**，不会覆盖既有代码。

将 ZIP 解压到 AgentForge 仓库根目录，在独立 `feature/v3-evidence-p1` 实验分支使用。

新增文件及相对路径：

- `src/agentforge/evidence_v3/__init__.py` 证据引擎公开接口
- `src/agentforge/evidence_v3/v20.py` V2 真实 artifact 分析 / 哈希 / 签名 / 核验
- `scripts/v3_evidence.py` 离线收集与核验 CLI
- `tests/test_v3_evidence.py` 篡改、伪造 PASS、重放、签名、缺失门禁等测试
- `docs/V30_EVIDENCE_P1.md` 设计、边界、完整使用文档
- `PLACEMENT_P1.md` 本放置说明（安装后可不保留）

运行：

```
python -m pip install -e '.[dev]'
pytest -q tests/test_v3_evidence.py
```

不修改原 V2 文件；不默认启用、不调用 DeepSeek、不推送 GitHub、不修改 PR #22、不部署。

历史 Run #39103687560 是 2/3 FAIL，不得将单独两个轮次 PASS 宣称为整体验收通过。

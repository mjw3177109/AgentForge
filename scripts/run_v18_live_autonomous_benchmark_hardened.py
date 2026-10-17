from __future__ import annotations

from pathlib import Path

import run_v18_live_autonomous_benchmark as base


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "benchmarks" / "v18_hardened"

base.REQUEST = """给商城增加真实积分功能。已确认业务规则：
1. 订单支付成功后，按实付金额每满1元获得1积分，向下取整。
2. 积分永久有效。
3. 100积分抵扣1元。
4. 单笔订单积分抵扣金额最多为该订单实付金额的20%。
5. 必须使用商城现有 CurrentUserProvider 获取当前用户，禁止新增 X-User-Id 或其他自定义用户身份 Header。
6. MySQL 是积分账户和积分流水的事实源；同一业务单号必须幂等，不能重复入账。
7. Redis 只用于积分余额缓存，不是事实源。
8. 提供 Spring Boot 积分服务/API、微信小程序积分查询和抵扣预览 API 封装、Vue3 后台积分流水页面。
9. 不做生产部署，不自动合并 main。
10. `.agent/contracts/DB-POINTS-980100.yaml` 与 `.agent/contracts/API-POINTS-980100.yaml` 是 VERIFIED CONTRACT，所有 Agent 与 Reviewer 必须以它们为跨栈唯一合同。
严格使用仓库 VERIFIED PROJECT CONTEXT、VERIFIED CONTRACT 与 Execution Profile，不得发明新的技术栈、身份认证方式、接口路径、表名或验证命令。"""

_ORIGINAL_SCAFFOLD = base.scaffold
_ORIGINAL_SNAPSHOT = base.snapshot

FIXTURES = {
    "project.yaml": ".agent/project.yaml",
    "execution-profiles.yaml": ".agent/execution-profiles.yaml",
    "contracts/DB-POINTS-980100.yaml": ".agent/contracts/DB-POINTS-980100.yaml",
    "contracts/API-POINTS-980100.yaml": ".agent/contracts/API-POINTS-980100.yaml",
    "database-README.md": "database/README.md",
    "server-pom.xml": "server/pom.xml",
    "VerifiedPointsContractTest.java": "server/src/test/java/com/agentforge/shop/points/VerifiedPointsContractTest.java",
    "database-contract.test.js": "verification/database-contract.test.js",
    "backend-contract.test.js": "verification/backend-contract.test.js",
    "miniapp-points.test.js": "miniapp/tests/points.test.js",
    "admin-points-ledger-contract.test.js": "admin-web/tests/points-ledger-contract.test.js",
}


def scaffold(repo: Path) -> None:
    _ORIGINAL_SCAFFOLD(repo)
    mutable_test = repo / "server/src/test/java/com/agentforge/shop/points/PointsServiceTest.java"
    if mutable_test.exists():
        mutable_test.unlink()
    for source, target in FIXTURES.items():
        base.write(repo, target, (FIXTURE_ROOT / source).read_text(encoding="utf-8"))


def _save_diagnostic(artifact_dir: Path, name: str, result) -> None:
    diagnostics = artifact_dir / "diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    (diagnostics / f"{name}.txt").write_text(
        f"returncode={result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}",
        encoding="utf-8",
    )


def snapshot(repo: Path, artifact_dir: Path, completed) -> None:
    _ORIGINAL_SNAPSHOT(repo, artifact_dir, completed)
    if completed.returncode == 0:
        return
    if (repo / "server/pom.xml").is_file():
        _save_diagnostic(
            artifact_dir,
            "maven-test",
            base.run("mvn", "-q", "-f", "server/pom.xml", "test", cwd=repo, check=False, timeout=300),
        )
    for name, rel in (
        ("database-contract", "verification/database-contract.test.js"),
        ("backend-contract", "verification/backend-contract.test.js"),
        ("miniapp-contract", "miniapp/tests/points.test.js"),
        ("admin-contract", "admin-web/tests/points-ledger-contract.test.js"),
    ):
        if (repo / rel).is_file():
            _save_diagnostic(
                artifact_dir,
                name,
                base.run("node", "--test", rel, cwd=repo, check=False, timeout=60),
            )


base.scaffold = scaffold
base.snapshot = snapshot

if __name__ == "__main__":
    raise SystemExit(base.main())

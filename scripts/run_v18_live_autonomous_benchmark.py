from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


REQUEST = """给商城增加真实积分功能。已确认业务规则：
1. 订单支付成功后，按实付金额每满1元获得1积分，向下取整。
2. 积分永久有效。
3. 100积分抵扣1元。
4. 单笔订单积分抵扣金额最多为该订单实付金额的20%。
5. 必须使用商城现有 CurrentUserProvider 获取当前用户，禁止新增 X-User-Id 或其他自定义用户身份 Header。
6. MySQL 是积分账户和积分流水的事实源；同一业务单号必须幂等，不能重复入账。
7. Redis 只用于积分余额缓存，不是事实源。
8. 提供 Spring Boot 积分服务/API、微信小程序积分查询和抵扣预览 API 封装、Vue3 后台积分流水页面。
9. 不做生产部署，不自动合并 main。
严格使用仓库 VERIFIED PROJECT CONTEXT 和 Execution Profile，不得发明新的技术栈、身份认证方式或验证命令。"""


def run(*args: str, cwd: Path, check: bool = True, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(args),
        cwd=cwd,
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=os.environ.copy(),
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(args)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def scaffold(repo: Path) -> None:
    write(
        repo,
        ".agent/project.yaml",
        """id: PROJECT-V18-LIVE-WECHAT-SHOP
name: v18-live-wechat-shop
verified_facts:
  backend:
    path: server
    framework: Spring Boot 2.7.18
    java: 17
    auth_provider: server/src/main/java/com/agentforge/shop/auth/CurrentUserProvider.java
    auth_rule: CurrentUserProvider is the only allowed current-user source; do not invent X-User-Id or identity headers.
  database:
    engine: MySQL 8
    migration_file: database/migrations/V980100__points.sql
    source_of_truth: MySQL is authoritative for points account and ledger.
    idempotency: the same business_no may affect points at most once.
  cache:
    engine: Redis 7
    rule: Redis may cache balances but is never the source of truth.
  miniapp:
    path: miniapp
    runtime: Node CommonJS
    required_file: miniapp/src/api/points.js
    contract_test: miniapp/tests/points.test.js
  admin:
    path: admin-web
    framework: Vue3 + Vite
    required_view: admin-web/src/PointsLedgerView.vue
    entry: admin-web/src/main.js
business_rules:
  earn: floor(paid_amount_yuan) points after payment succeeds
  expiry: never
  redeem_rate: 100 points = 1 yuan
  max_order_discount: 20 percent of paid amount
required_outputs:
  - database/migrations/V980100__points.sql
  - Spring Boot points domain/service and API under server/src/main/java/com/agentforge/shop/points/
  - miniapp/src/api/points.js
  - admin-web/src/PointsLedgerView.vue
forbidden:
  - production deployment
  - automatic merge to main
  - custom user identity headers
""",
    )
    write(
        repo,
        ".agent/execution-profiles.yaml",
        """allowed_verification_executables:
  - mysql
  - redis-cli
  - mvn
  - node
  - npm
agents:
  database:
    context_paths:
      - database/README.md
      - .agent/project.yaml
    read_scope:
      - database/**
      - .agent/**
    write_scope:
      - database/**
    deny_scope:
      - server/**
      - miniapp/**
      - admin-web/**
    verification:
      - argv:
          - mysql
          - --protocol=TCP
          - -h127.0.0.1
          - -P3306
          - -uroot
          - -proot
          - agentforge
          - -e
          - "DROP TABLE IF EXISTS user_points_ledger; DROP TABLE IF EXISTS user_points_account; source database/migrations/V980100__points.sql; SHOW CREATE TABLE user_points_account; SHOW CREATE TABLE user_points_ledger;"
        cwd: .
        timeout_seconds: 60
  backend:
    context_paths:
      - server/pom.xml
      - server/src/main/java/com/agentforge/shop/auth/CurrentUserProvider.java
      - server/src/test/java/com/agentforge/shop/points/PointsServiceTest.java
      - .agent/project.yaml
    read_scope:
      - server/**
      - .agent/**
    write_scope:
      - server/**
    deny_scope:
      - database/**
      - miniapp/**
      - admin-web/**
    verification:
      - argv: [redis-cli, -h, 127.0.0.1, -p, "6379", PING]
        cwd: .
        timeout_seconds: 30
      - argv: [mvn, -q, -f, server/pom.xml, test]
        cwd: .
        timeout_seconds: 300
  miniapp:
    context_paths:
      - miniapp/tests/points.test.js
      - .agent/project.yaml
    read_scope:
      - miniapp/**
      - .agent/**
    write_scope:
      - miniapp/**
    deny_scope:
      - database/**
      - server/**
      - admin-web/**
    verification:
      - argv: [node, --test, miniapp/tests/points.test.js]
        cwd: .
        timeout_seconds: 60
  admin:
    context_paths:
      - admin-web/package.json
      - admin-web/index.html
      - admin-web/vite.config.js
      - admin-web/src/main.js
      - .agent/project.yaml
    read_scope:
      - admin-web/**
      - .agent/**
    write_scope:
      - admin-web/**
    deny_scope:
      - database/**
      - server/**
      - miniapp/**
    verification:
      - argv: [npm, install, --no-audit, --no-fund]
        cwd: admin-web
        timeout_seconds: 300
      - argv: [npm, run, build]
        cwd: admin-web
        timeout_seconds: 300
""",
    )
    write(
        repo,
        "database/README.md",
        """# Database contract

The points migration for REQ-980100 must be exactly `database/migrations/V980100__points.sql`.
It must create `user_points_account` and `user_points_ledger`.
The ledger must make `business_no` unique so repeated processing of the same business event cannot double-credit points.
MySQL is the source of truth.
""",
    )
    write(
        repo,
        "server/pom.xml",
        """<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>2.7.18</version>
    <relativePath/>
  </parent>
  <groupId>com.agentforge</groupId>
  <artifactId>v18-live-shop</artifactId>
  <version>1.0.0</version>
  <properties><java.version>17</java.version></properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-data-redis</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-test</artifactId>
      <scope>test</scope>
    </dependency>
  </dependencies>
</project>
""",
    )
    write(
        repo,
        "server/src/main/java/com/agentforge/shop/auth/CurrentUserProvider.java",
        """package com.agentforge.shop.auth;

public interface CurrentUserProvider {
    long currentUserId();
}
""",
    )
    write(
        repo,
        "server/src/test/java/com/agentforge/shop/points/PointsServiceTest.java",
        """package com.agentforge.shop.points;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.math.BigDecimal;
import org.junit.jupiter.api.Test;

class PointsServiceTest {
    private final PointsService service = new PointsService();

    @Test
    void earnsOnePointPerWholePaidYuan() {
        assertEquals(100L, service.earnPoints(new BigDecimal("100.99")));
        assertEquals(0L, service.earnPoints(new BigDecimal("0.99")));
    }

    @Test
    void convertsPointsAtOneYuanPerHundredPoints() {
        assertEquals(new BigDecimal("20.00"), service.discountForPoints(2000));
        assertEquals(new BigDecimal("0.50"), service.discountForPoints(50));
    }

    @Test
    void capsPointsDiscountAtTwentyPercentOfPaidAmount() {
        assertEquals(
            new BigDecimal("20.00"),
            service.maxDiscount(new BigDecimal("100.00"), 5000)
        );
        assertEquals(
            new BigDecimal("5.00"),
            service.maxDiscount(new BigDecimal("100.00"), 500)
        );
    }
}
""",
    )
    write(
        repo,
        "miniapp/tests/points.test.js",
        """const test = require('node:test');
const assert = require('node:assert/strict');
const {
  buildMyPointsUrl,
  buildRedeemPreviewUrl,
  getMyPoints,
  previewRedeem
} = require('../src/api/points');

test('uses fixed points API contracts', () => {
  assert.equal(buildMyPointsUrl(), '/api/points/me');
  assert.equal(
    buildRedeemPreviewUrl(100, 2000),
    '/api/points/redeem-preview?paidAmount=100&points=2000'
  );
});

test('queries current-user points without custom identity headers', async () => {
  let captured;
  await getMyPoints(async (options) => {
    captured = options;
    return { data: { balance: 123 } };
  });
  assert.equal(captured.url, '/api/points/me');
  assert.equal(captured.method, 'GET');
  assert.equal(captured.header, undefined);
});

test('previews redemption through POST', async () => {
  let captured;
  await previewRedeem(async (options) => {
    captured = options;
    return { data: { discount: 20 } };
  }, 100, 2000);
  assert.equal(captured.method, 'POST');
  assert.equal(captured.url, '/api/points/redeem-preview?paidAmount=100&points=2000');
});
""",
    )
    write(
        repo,
        "admin-web/package.json",
        """{
  "name": "agentforge-v18-live-admin",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {"build": "vite build"},
  "dependencies": {"vue": "3.5.22"},
  "devDependencies": {
    "@vitejs/plugin-vue": "5.2.4",
    "vite": "5.4.20"
  }
}
""",
    )
    write(
        repo,
        "admin-web/index.html",
        """<!doctype html>
<html><body><div id="app"></div><script type="module" src="/src/main.js"></script></body></html>
""",
    )
    write(
        repo,
        "admin-web/vite.config.js",
        """import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
export default defineConfig({ plugins: [vue()] });
""",
    )
    write(
        repo,
        "admin-web/src/main.js",
        """import { createApp } from 'vue';
import PointsLedgerView from './PointsLedgerView.vue';
createApp(PointsLedgerView).mount('#app');
""",
    )


def snapshot(repo: Path, artifact_dir: Path, completed: subprocess.CompletedProcess[str]) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (artifact_dir / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    (artifact_dir / "request.txt").write_text(REQUEST + "\n", encoding="utf-8")

    for name, args in {
        "git-log.txt": ("git", "log", "--oneline", "--decorate", "--all", "-30"),
        "git-status.txt": ("git", "status", "--short", "--branch"),
        "git-diff.txt": ("git", "diff", "main...HEAD", "--"),
    }.items():
        result = run(*args, cwd=repo, check=False, timeout=60)
        (artifact_dir / name).write_text(result.stdout + result.stderr, encoding="utf-8")

    generated = artifact_dir / "generated-repo"
    if generated.exists():
        shutil.rmtree(generated)
    shutil.copytree(
        repo,
        generated,
        ignore=shutil.ignore_patterns(".git", "node_modules", "target", "__pycache__", "*.pyc"),
    )


def main() -> int:
    artifact_dir = Path(
        os.getenv("AGENTFORGE_BENCHMARK_ARTIFACT_DIR", "artifacts/v18-live-autonomous")
    ).resolve()
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)

    with tempfile.TemporaryDirectory(prefix="agentforge-v18-live-") as temp_dir:
        repo = Path(temp_dir) / "wechat-shop"
        repo.mkdir()
        scaffold(repo)

        run("git", "init", "-b", "main", cwd=repo)
        run("git", "config", "user.email", "agentforge-live@example.test", cwd=repo)
        run("git", "config", "user.name", "AgentForge V1.8 Live", cwd=repo)
        run("git", "add", "-A", cwd=repo)
        run("git", "commit", "-m", "chore: initialize V1.8 live benchmark shop", cwd=repo)

        command = [
            "agentforge",
            "autonomous-live",
            REQUEST,
            "--repo-root",
            str(repo),
            "--profiles",
            ".agent/execution-profiles.yaml",
            "--base",
            "main",
            "--req-id",
            "REQ-980100",
            "--adr-id",
            "ADR-980100",
            "--feature-branch",
            "feature/REQ-980100-points-live",
        ]
        completed = run(*command, cwd=repo, check=False, timeout=1200)
        snapshot(repo, artifact_dir, completed)

        print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="", file=os.sys.stderr)
        if completed.returncode != 0:
            return completed.returncode

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            print(f"autonomous-live did not return JSON: {exc}", file=os.sys.stderr)
            return 3
        if payload.get("status") != "SUCCESS":
            print(f"unexpected autonomous status: {payload.get('status')}", file=os.sys.stderr)
            return 4
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

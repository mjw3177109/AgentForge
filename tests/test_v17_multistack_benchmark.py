from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agentforge.autonomous import (
    AgentExecutionProfile,
    AutonomousDevelopmentPipeline,
    GitHubPullRequestPublisher,
)
from agentforge.coding import VerificationSpec
from agentforge.llm import OpenAICompatibleClient


pytestmark = pytest.mark.skipif(
    os.getenv("AGENTFORGE_RUN_MULTISTACK_BENCHMARK") != "1",
    reason="V1.7 multi-stack benchmark requires CI service containers and toolchains",
)


class SequenceHandler(BaseHTTPRequestHandler):
    responses: list[dict] = []
    requests: list[dict] = []

    def log_message(self, format, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests.append(payload)
        if not type(self).responses:
            self.send_response(500)
            self.end_headers()
            return
        content = type(self).responses.pop(0)
        body = json.dumps(
            {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class PullRequestHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def log_message(self, format, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests.append(
            {
                "path": self.path,
                "payload": payload,
                "authorization": self.headers.get("authorization"),
            }
        )
        body = json.dumps({"html_url": "https://github.test/mjw3177109/AgentForge/pull/170"}).encode(
            "utf-8"
        )
        self.send_response(201)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_model_server(responses: list[dict]):
    handler = type(
        "V17SequenceHandler",
        (SequenceHandler,),
        {"responses": list(responses), "requests": []},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, handler


def start_pr_server():
    handler = type("V17PullRequestHandler", (PullRequestHandler,), {"requests": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, handler


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        shell=False,
        capture_output=True,
        text=True,
        check=check,
        timeout=120,
    )


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_shop_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "wechat-shop"
    remote = tmp_path / "wechat-shop-origin.git"
    repo.mkdir()

    write(
        repo / ".agent/project.yaml",
        """id: PROJECT-WECHAT-SHOP
name: wechat-shop
stack:
  backend: springboot2
  database: mysql
  cache: redis
  miniapp: wechat
  admin: vue3
""",
    )
    write(
        repo / "server/pom.xml",
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
  <artifactId>wechat-shop-server</artifactId>
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
        repo / "server/src/main/java/com/agentforge/shop/ShopApplication.java",
        """package com.agentforge.shop;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class ShopApplication {
    public static void main(String[] args) {
        SpringApplication.run(ShopApplication.class, args);
    }
}
""",
    )
    write(
        repo / "server/src/test/java/com/agentforge/shop/coupon/CouponServiceTest.java",
        """package com.agentforge.shop.coupon;

import static org.junit.jupiter.api.Assertions.assertEquals;
import java.math.BigDecimal;
import org.junit.jupiter.api.Test;

class CouponServiceTest {
    @Test
    void appliesFixedDiscountWithoutGoingNegative() {
        CouponService service = new CouponService();
        assertEquals(new BigDecimal("90.00"), service.applyDiscount(
            new BigDecimal("100.00"), new BigDecimal("10.00")));
        assertEquals(new BigDecimal("0.00"), service.applyDiscount(
            new BigDecimal("5.00"), new BigDecimal("10.00")));
    }
}
""",
    )

    write(
        repo / "miniapp/tests/coupons.test.js",
        """const test = require('node:test');
const assert = require('node:assert/strict');
const { buildCouponApplyUrl, applyCoupon } = require('../src/api/coupons');

test('uses the architecture-defined coupon endpoint', async () => {
  assert.equal(
    buildCouponApplyUrl(100, 10),
    '/api/coupons/apply?price=100&discount=10'
  );
  let captured;
  const result = await applyCoupon(async (options) => {
    captured = options;
    return { data: 90 };
  }, 100, 10);
  assert.equal(captured.method, 'POST');
  assert.equal(result.data, 90);
});
""",
    )

    write(
        repo / "admin-web/package.json",
        """{
  "name": "agentforge-wechat-shop-admin",
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
        repo / "admin-web/index.html",
        """<!doctype html>
<html><body><div id="app"></div><script type="module" src="/src/main.js"></script></body></html>
""",
    )
    write(
        repo / "admin-web/vite.config.js",
        """import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
export default defineConfig({ plugins: [vue()] });
""",
    )

    run("git", "init", "-b", "main", cwd=repo)
    run("git", "config", "user.email", "agentforge@example.test", cwd=repo)
    run("git", "config", "user.name", "AgentForge Benchmark", cwd=repo)
    run("git", "add", "-A", cwd=repo)
    run("git", "commit", "-m", "chore: initialize real wechat shop benchmark", cwd=repo)
    run("git", "init", "--bare", str(remote), cwd=tmp_path)
    run("git", "remote", "add", "origin", str(remote), cwd=repo)
    run("git", "push", "-u", "origin", "main", cwd=repo)
    return repo, remote


def model_responses() -> list[dict]:
    requirement = {
        "id": "REQ-970001",
        "title": "商城优惠券",
        "actors": ["CUSTOMER", "ADMIN"],
        "modules": ["database", "backend", "miniapp", "admin"],
        "business_rules": [
            "优惠券按固定金额抵扣",
            "抵扣后订单金额不得小于0",
            "同一用户同一优惠券只能领取一次",
        ],
        "acceptance": [
            "MySQL存在coupon和user_coupon表",
            "Spring Boot优惠券服务测试通过",
            "微信小程序调用统一优惠券接口",
            "Vue3后台优惠券页面可以构建",
            "Redis服务可用于优惠券缓存",
        ],
        "out_of_scope": ["自动合并main", "生产部署"],
    }
    architecture = {
        "id": "ADR-970001",
        "requirement_ids": ["REQ-970001"],
        "decision": {
            "database": {"change_required": True, "engine": "mysql"},
            "backend": {"change_required": True, "framework": "springboot2"},
            "cache": {"change_required": True, "engine": "redis"},
            "miniapp": {"change_required": True, "framework": "wechat"},
            "admin": {"change_required": True, "framework": "vue3"},
            "api": {"coupon_apply": "POST /api/coupons/apply"},
        },
        "evidence": ["REQ-970001"],
    }
    tasks = {
        "tasks": [
            {
                "id": "TASK-970101",
                "requirement_ids": ["REQ-970001"],
                "adr_ids": ["ADR-970001"],
                "assigned_agent": "database",
                "dependencies": [],
                "scope": {
                    "read": ["database/**"],
                    "write": ["database/**"],
                    "deny": [".agent/**", "server/**", "miniapp/**", "admin-web/**"],
                },
                "acceptance": ["创建coupon和user_coupon表并限制重复领取"],
                "verification": ["mysql migration"],
            },
            {
                "id": "TASK-970102",
                "requirement_ids": ["REQ-970001"],
                "adr_ids": ["ADR-970001"],
                "assigned_agent": "backend",
                "dependencies": ["TASK-970101"],
                "scope": {
                    "read": ["server/**", "database/**"],
                    "write": ["server/**"],
                    "deny": [".agent/**", "miniapp/**", "admin-web/**"],
                },
                "acceptance": ["Spring Boot优惠券固定金额抵扣测试通过", "Redis可连接"],
                "verification": ["maven test", "redis ping"],
            },
            {
                "id": "TASK-970103",
                "requirement_ids": ["REQ-970001"],
                "adr_ids": ["ADR-970001"],
                "assigned_agent": "miniapp",
                "dependencies": ["TASK-970102"],
                "scope": {
                    "read": ["miniapp/**"],
                    "write": ["miniapp/**"],
                    "deny": [".agent/**", "server/**", "database/**", "admin-web/**"],
                },
                "acceptance": ["小程序统一调用POST /api/coupons/apply"],
                "verification": ["node test"],
            },
            {
                "id": "TASK-970104",
                "requirement_ids": ["REQ-970001"],
                "adr_ids": ["ADR-970001"],
                "assigned_agent": "admin",
                "dependencies": ["TASK-970102"],
                "scope": {
                    "read": ["admin-web/**"],
                    "write": ["admin-web/**"],
                    "deny": [".agent/**", "server/**", "database/**", "miniapp/**"],
                },
                "acceptance": ["Vue3优惠券管理页面可构建"],
                "verification": ["vite build"],
            },
        ]
    }

    database_action = {
        "status": "SUCCESS",
        "summary": "create coupon schema",
        "evidence": ["REQ-970001", "ADR-970001", "TASK-970101"],
        "operations": [
            {
                "op": "write_text",
                "path": "database/migrations/V970001__coupon.sql",
                "content": """CREATE TABLE coupon (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  code VARCHAR(64) NOT NULL UNIQUE,
  discount_amount DECIMAL(10,2) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'
);

CREATE TABLE user_coupon (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  coupon_id BIGINT NOT NULL,
  used TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY uk_user_coupon (user_id, coupon_id),
  CONSTRAINT fk_user_coupon_coupon FOREIGN KEY (coupon_id) REFERENCES coupon(id)
);
""",
            }
        ],
    }

    backend_bad = {
        "status": "SUCCESS",
        "summary": "initial coupon backend implementation",
        "evidence": ["REQ-970001", "ADR-970001", "TASK-970102"],
        "operations": [
            {
                "op": "write_text",
                "path": "server/src/main/java/com/agentforge/shop/coupon/CouponService.java",
                "content": """package com.agentforge.shop.coupon;

import java.math.BigDecimal;
import org.springframework.stereotype.Service;

@Service
public class CouponService {
    public BigDecimal applyDiscount(BigDecimal price, BigDecimal discount) {
        return price.add(discount).setScale(2);
    }
}
""",
            },
            {
                "op": "write_text",
                "path": "server/src/main/java/com/agentforge/shop/coupon/CouponController.java",
                "content": """package com.agentforge.shop.coupon;

import java.math.BigDecimal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/coupons")
public class CouponController {
    private final CouponService service;

    public CouponController(CouponService service) {
        this.service = service;
    }

    @PostMapping("/apply")
    public BigDecimal apply(@RequestParam BigDecimal price, @RequestParam BigDecimal discount) {
        return service.applyDiscount(price, discount);
    }
}
""",
            },
            {
                "op": "write_text",
                "path": "server/src/main/java/com/agentforge/shop/coupon/CouponCache.java",
                "content": """package com.agentforge.shop.coupon;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

@Component
public class CouponCache {
    private final StringRedisTemplate redis;

    public CouponCache(StringRedisTemplate redis) {
        this.redis = redis;
    }

    public void markAvailable(long couponId) {
        redis.opsForValue().set("coupon:available:" + couponId, "1");
    }
}
""",
            },
        ],
    }

    backend_repair = {
        "status": "SUCCESS",
        "summary": "repair discount direction and zero floor",
        "evidence": ["REQ-970001", "ADR-970001", "TASK-970102"],
        "operations": [
            {
                "op": "write_text",
                "path": "server/src/main/java/com/agentforge/shop/coupon/CouponService.java",
                "content": """package com.agentforge.shop.coupon;

import java.math.BigDecimal;
import org.springframework.stereotype.Service;

@Service
public class CouponService {
    public BigDecimal applyDiscount(BigDecimal price, BigDecimal discount) {
        BigDecimal result = price.subtract(discount);
        if (result.signum() < 0) {
            result = BigDecimal.ZERO;
        }
        return result.setScale(2);
    }
}
""",
            }
        ],
    }

    miniapp_action = {
        "status": "SUCCESS",
        "summary": "add miniapp coupon API",
        "evidence": ["REQ-970001", "ADR-970001", "TASK-970103"],
        "operations": [
            {
                "op": "write_text",
                "path": "miniapp/src/api/coupons.js",
                "content": """function buildCouponApplyUrl(price, discount) {
  return `/api/coupons/apply?price=${price}&discount=${discount}`;
}

async function applyCoupon(request, price, discount) {
  return request({
    url: buildCouponApplyUrl(price, discount),
    method: 'POST'
  });
}

module.exports = { buildCouponApplyUrl, applyCoupon };
""",
            }
        ],
    }

    admin_action = {
        "status": "SUCCESS",
        "summary": "add Vue3 coupon admin page",
        "evidence": ["REQ-970001", "ADR-970001", "TASK-970104"],
        "operations": [
            {
                "op": "write_text",
                "path": "admin-web/src/main.js",
                "content": """import { createApp } from 'vue';
import CouponView from './CouponView.vue';
createApp(CouponView).mount('#app');
""",
            },
            {
                "op": "write_text",
                "path": "admin-web/src/api/coupons.js",
                "content": """export async function applyCoupon(price, discount) {
  const params = new URLSearchParams({ price: String(price), discount: String(discount) });
  const response = await fetch(`/api/coupons/apply?${params}`, { method: 'POST' });
  if (!response.ok) throw new Error('coupon request failed');
  return response.json();
}
""",
            },
            {
                "op": "write_text",
                "path": "admin-web/src/CouponView.vue",
                "content": """<script setup>
import { ref } from 'vue';
import { applyCoupon } from './api/coupons.js';

const price = ref(100);
const discount = ref(10);
const finalPrice = ref(null);

async function preview() {
  finalPrice.value = await applyCoupon(price.value, discount.value);
}
</script>

<template>
  <main>
    <h1>优惠券管理</h1>
    <button id="preview-coupon" @click="preview">预览抵扣</button>
    <p v-if="finalPrice !== null">优惠后：{{ finalPrice }}</p>
  </main>
</template>
""",
            },
        ],
    }

    review = {
        "status": "APPROVE",
        "summary": "Database, Spring Boot, Redis, MiniApp and Vue3 changes remain within REQ-970001 scope and all orchestrator verification gates passed.",
        "evidence": [
            "REQ-970001",
            "ADR-970001",
            "TASK-970101",
            "TASK-970102",
            "TASK-970103",
            "TASK-970104",
        ],
    }

    return [
        requirement,
        architecture,
        tasks,
        database_action,
        backend_bad,
        backend_repair,
        miniapp_action,
        admin_action,
        review,
    ]


def test_v17_real_multistack_coupon_request_to_pr(tmp_path: Path):
    repo, remote = make_shop_repo(tmp_path)
    model_server, model_handler = start_model_server(model_responses())
    pr_server, pr_handler = start_pr_server()
    try:
        model_host, model_port = model_server.server_address
        pr_host, pr_port = pr_server.server_address
        client = OpenAICompatibleClient(
            base_url=f"http://{model_host}:{model_port}",
            api_key="benchmark",
            model="v17-fake-openai-compatible",
            max_attempts=1,
        )
        publisher = GitHubPullRequestPublisher(
            repo_full_name="mjw3177109/AgentForge",
            token="benchmark-token",
            api_base=f"http://{pr_host}:{pr_port}",
        )

        mysql_args = [
            "mysql",
            "--protocol=TCP",
            "-h127.0.0.1",
            "-P3306",
            "-uroot",
            "-proot",
            "agentforge",
        ]
        profiles = {
            "database": AgentExecutionProfile(
                context_paths=[],
                verification=[
                    VerificationSpec(
                        argv=mysql_args
                        + [
                            "-e",
                            "source database/migrations/V970001__coupon.sql; DESCRIBE coupon; DESCRIBE user_coupon;",
                        ]
                    )
                ],
            ),
            "backend": AgentExecutionProfile(
                context_paths=[
                    "server/pom.xml",
                    "server/src/test/java/com/agentforge/shop/coupon/CouponServiceTest.java",
                ],
                verification=[
                    VerificationSpec(argv=["redis-cli", "-h", "127.0.0.1", "-p", "6379", "PING"]),
                    VerificationSpec(argv=["mvn", "-q", "-f", "server/pom.xml", "test"], timeout_seconds=240),
                ],
            ),
            "miniapp": AgentExecutionProfile(
                context_paths=["miniapp/tests/coupons.test.js"],
                verification=[
                    VerificationSpec(argv=["node", "--test", "miniapp/tests/coupons.test.js"])
                ],
            ),
            "admin": AgentExecutionProfile(
                context_paths=[
                    "admin-web/package.json",
                    "admin-web/index.html",
                    "admin-web/vite.config.js",
                ],
                verification=[
                    VerificationSpec(
                        argv=["npm", "install", "--no-audit", "--no-fund"],
                        cwd="admin-web",
                        timeout_seconds=240,
                    ),
                    VerificationSpec(
                        argv=["npm", "run", "build"],
                        cwd="admin-web",
                        timeout_seconds=240,
                    ),
                ],
            ),
        }

        pipeline = AutonomousDevelopmentPipeline(
            client=client,
            repo_root=repo,
            profiles=profiles,
            allowed_verification_executables={"mysql", "redis-cli", "mvn", "node", "npm"},
            max_coding_attempts=2,
        )
        result = pipeline.run(
            "给商城增加优惠券功能",
            base_branch="main",
            requirement_id="REQ-970001",
            adr_id="ADR-970001",
            feature_branch="feature/REQ-970001-coupon-real-stack",
            push=True,
            publisher=publisher,
            create_pr=True,
        )

        assert result.status == "PR_READY"
        assert result.review is not None and result.review.status == "APPROVE"
        assert [item.task_id for item in result.task_runs] == [
            "TASK-970101",
            "TASK-970102",
            "TASK-970103",
            "TASK-970104",
        ]
        backend = next(item for item in result.task_runs if item.task_id == "TASK-970102")
        assert backend.attempts == 2
        assert all(item.status == "SUCCESS" for item in result.task_runs)
        assert "subtract(discount)" in (
            repo / "server/src/main/java/com/agentforge/shop/coupon/CouponService.java"
        ).read_text("utf-8")
        assert (repo / "miniapp/src/api/coupons.js").is_file()
        assert (repo / "admin-web/src/CouponView.vue").is_file()
        assert (repo / "database/migrations/V970001__coupon.sql").is_file()

        commits = int(run("git", "rev-list", "--count", "main..HEAD", cwd=repo).stdout.strip())
        assert commits == 5
        remote_heads = run(
            "git",
            "--git-dir",
            str(remote),
            "show-ref",
            "--verify",
            "refs/heads/feature/REQ-970001-coupon-real-stack",
            cwd=tmp_path,
        )
        assert "feature/REQ-970001-coupon-real-stack" in remote_heads.stdout

        mysql_check = subprocess.run(
            mysql_args
            + [
                "-Nse",
                "SELECT CONCAT((SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='agentforge' AND table_name='coupon'), ':', (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='agentforge' AND table_name='user_coupon'));",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        assert mysql_check.stdout.strip() == "1:1"
        redis_check = subprocess.run(
            ["redis-cli", "-h", "127.0.0.1", "-p", "6379", "PING"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        assert redis_check.stdout.strip() == "PONG"

        assert len(model_handler.requests) == 9
        repair_prompt = model_handler.requests[5]["messages"][1]["content"]
        assert "VERIFICATION FAILED" in repair_prompt
        assert "CouponServiceTest" in repair_prompt

        assert len(pr_handler.requests) == 1
        pr_request = pr_handler.requests[0]
        assert pr_request["path"] == "/repos/mjw3177109/AgentForge/pulls"
        assert pr_request["payload"]["head"] == "feature/REQ-970001-coupon-real-stack"
        assert pr_request["payload"]["base"] == "main"
        assert pr_request["authorization"] == "Bearer benchmark-token"
    finally:
        model_server.shutdown()
        pr_server.shutdown()

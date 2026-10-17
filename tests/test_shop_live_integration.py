from pathlib import Path
import yaml

from agentforge.live_feature import LiveFeaturePipeline
from agentforge.memory import PostMergeMemoryService
from agentforge.protocol.loader import ProjectProtocol


REPO = Path(__file__).resolve().parents[1]


def test_real_shop_root_is_an_agentforge_project():
    project = ProjectProtocol(REPO).project()
    assert project["project"]["id"] == "SHOP001"
    assert project["repository"]["default_branch"] == "main"
    assert project["stack"]["backend"]["framework"] == "springboot"
    assert project["stack"]["backend"]["version"] == "2.7.18"


def test_real_shop_exposes_runtime_verification_gates():
    checks = ProjectProtocol(REPO).verification_policy()["checks"]
    assert {"backend-test", "admin-build", "miniapp-check"} <= set(checks)
    assert all(checks[name]["type"] == "docker_command" for name in checks)


def test_real_shop_auth_fact_matches_backend_contract():
    fact = yaml.safe_load((REPO / ".agent/facts/FACT-AUTH-001.yaml").read_text(encoding="utf-8"))
    assert "CurrentUser" in fact["statement"]
    assert "X-User-Id" in fact["statement"]
    resolver = (REPO / "server/src/main/java/com/agentforge/shop/auth/CurrentUserArgumentResolver.java").read_text(encoding="utf-8")
    assert "AuthenticationAttributes.USER_ID" in resolver
    assert "X-User-Id" not in resolver


def test_live_and_post_merge_layers_are_importable_together():
    assert LiveFeaturePipeline is not None
    assert PostMergeMemoryService is not None

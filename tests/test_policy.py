import pytest
from agentforge.errors import PolicyDenied
from agentforge.policy import PolicyEngine, matches, norm


def test_path_traversal_denied():
    with pytest.raises(PolicyDenied):
        norm("../secret.txt")
    assert norm("server/../miniapp/a.txt") == "miniapp/a.txt"


def test_deny_wins():
    p = PolicyEngine(read=["**"], write=["server/**"], deny=["server/secrets/**"])
    p.require_write("server/app.py")
    with pytest.raises(PolicyDenied):
        p.require_write("server/secrets/key.txt")


def test_explicit_directory_scope_covers_only_its_subtree():
    scope = "server/src/main/java/com/agentforge/shop/points/"
    assert matches("server/src/main/java/com/agentforge/shop/points/PointsService.java", scope)
    assert matches("server/src/main/java/com/agentforge/shop/points/domain/PointsPolicy.java", scope)
    assert not matches("server/src/main/java/com/agentforge/shop/auth/CurrentUserProvider.java", scope)

    policy = PolicyEngine(write=[scope])
    policy.require_write("server/src/main/java/com/agentforge/shop/points/PointsService.java")
    with pytest.raises(PolicyDenied):
        policy.require_write("server/src/main/java/com/agentforge/shop/auth/CurrentUserProvider.java")

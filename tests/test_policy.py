import pytest
from agentforge.errors import PolicyDenied
from agentforge.policy import PolicyEngine, norm

def test_path_traversal_denied():
    with pytest.raises(PolicyDenied): norm("../secret.txt")
    assert norm("server/../miniapp/a.txt") == "miniapp/a.txt"

def test_deny_wins():
    p = PolicyEngine(read=["**"], write=["server/**"], deny=["server/secrets/**"])
    p.require_write("server/app.py")
    with pytest.raises(PolicyDenied): p.require_write("server/secrets/key.txt")

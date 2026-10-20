"""V1.6 test-suite integrity: untrusted Django code cannot rewrite verifier inputs."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from agentforge_django.docker_verify import (
    build_docker_command, docker_verification, workspace_fingerprint,
)
from agentforge_django.guard import BoundaryDenied


class ReadOnlyDockerBarrierTests(SimpleTestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory(prefix="agentforge-v16-test-")
        self.addCleanup(work.cleanup)
        self.root = Path(work.name) / "fixture"
        self.root.mkdir()
        (self.root / "manage.py").write_text("# test manage file\n", "utf-8")
        (self.root / "app").mkdir()
        (self.root / "app" / "tests.py").write_text(
            "def test_original():\n    assert True\n", "utf-8"
        )

    def test_container_bind_mount_is_explicitly_readonly(self):
        argv = build_docker_command(
            image="agentforge-django-verify:0.4",
            source=self.root, name="agentforge-verify-" + "a" * 20,
            check="test",
        )
        mount = argv[argv.index("--mount") + 1]
        self.assertIn("dst=/workspace,readonly", mount)
        self.assertNotIn(":rw", mount)
        self.assertIn("--network", argv)
        self.assertIn("none", argv)

    def test_worktree_fingerprint_detects_file_edits_and_added_paths(self):
        before = workspace_fingerprint(self.root)
        path = self.root / "app" / "tests.py"
        path.write_text("def test_poisoned():\n    assert False\n", "utf-8")
        self.assertNotEqual(before, workspace_fingerprint(self.root))
        again = workspace_fingerprint(self.root)
        (self.root / "new.py").write_text("x=1\n", "utf-8")
        self.assertNotEqual(again, workspace_fingerprint(self.root))

    def test_worktree_fingerprint_rejects_symlink(self):
        target = self.root / "app" / "tests.py"
        link = self.root / "linked.py"
        link.symlink_to(target)
        with self.assertRaises(BoundaryDenied):
            workspace_fingerprint(self.root)

    def test_mocked_successful_check_that_changes_tests_is_blocked(self):
        runs = []
        def fake_docker(argv, *, timeout):
            if argv[:2] == ["image", "inspect"]:
                return SimpleNamespace(returncode=0, stdout="sha256:" + "a" * 64 + "\n", stderr="")
            if argv[0] == "run":
                runs.append(argv)
                mount = argv[argv.index("--mount") + 1]
                src = Path(mount.split("src=", 1)[1].split(",dst=", 1)[0])
                # Simulate a buggy or compromised Docker runtime ignoring the
                # read-only contract and allowing a check-stage source write.
                (src / "app" / "tests.py").write_text(
                    "def test_poisoned(): pass\n", "utf-8"
                )
                return SimpleNamespace(returncode=0, stdout="OK", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch("agentforge_django.docker_verify.shutil.which",
                   return_value="/usr/bin/docker"), patch(
                   "agentforge_django.docker_verify._run_docker",
                   side_effect=fake_docker):
            result = docker_verification(self.root)
        self.assertFalse(result["passed"])
        self.assertEqual(len(runs), 1)  # 'test' must never execute.
        self.assertEqual(
            result["checks"][0]["reason"], "VERIFICATION_WORKTREE_MUTATED"
        )
        self.assertIn("test_original", (self.root / "app/tests.py").read_text("utf-8"))

    def test_mocked_benign_two_checks_remain_green(self):
        def fake_docker(argv, *, timeout):
            if argv[:2] == ["image", "inspect"]:
                return SimpleNamespace(returncode=0, stdout="sha256:" + "a" * 64 + "\n", stderr="")
            if argv[0] == "run":
                test = "test" in argv
                return SimpleNamespace(
                    returncode=0,
                    stdout="Ran 1 test in 0.001s\nOK\n" if test else "OK",
                    stderr="",
                )
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch("agentforge_django.docker_verify.shutil.which",
                   return_value="/usr/bin/docker"), patch(
                   "agentforge_django.docker_verify._run_docker",
                   side_effect=fake_docker):
            result = docker_verification(self.root)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["checks"]), 2)

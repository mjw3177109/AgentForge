"""V0.4 Docker argv security invariants with mocked daemon (offline CI)."""
import tempfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from agentforge_django.docker_verify import (
    build_docker_command, docker_verification, docker_image,
)
from agentforge_django.guard import BoundaryDenied
from agentforge_django.verification import isolated_verification


class DockerSecurityTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="af-docker-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "manage.py").write_text("# fixture\n", encoding="utf-8")
        (self.root / "myapp.py").write_text("VALUE = 1\n", encoding="utf-8")

    def test_argv_never_grants_network_or_privileges(self):
        cmd = build_docker_command(
            image="agentforge-django-verify:0.4",
            source=self.root,
            name="agentforge-verify-" + "a" * 20,
            check="test",
        )
        rendered = " ".join(cmd)
        for expected in (
            "--network none", "--cap-drop ALL", "--security-opt no-new-privileges",
            "--read-only", "--pull never", "--user 65534:65534",
            "--pids-limit 128", "dst=/workspace,rw",
        ):
            self.assertIn(expected, rendered)
        for forbidden in ("--privileged", "/var/run/docker.sock", "--network host",
                          "AGENTFORGE_LLM_API_KEY", "--device", "--pid host"):
            self.assertNotIn(forbidden, rendered)

    def test_invalid_image_and_subcommand_denied(self):
        with override_settings(AGENTFORGE_DOCKER_VERIFY_IMAGE="repo:latest"):
            with self.assertRaises(BoundaryDenied):
                docker_image()
        with self.assertRaises(BoundaryDenied):
            build_docker_command(
                image="verifier:0.4", source=self.root,
                name="agentforge-verify-" + "0" * 20, check="bash"
            )

    def test_no_docker_does_not_fallback_to_host(self):
        with patch("agentforge_django.docker_verify.shutil.which", return_value=None):
            with self.assertRaises(BoundaryDenied):
                isolated_verification(self.root)

    def test_local_requires_two_explicit_flags(self):
        with override_settings(AGENTFORGE_VERIFICATION_BACKEND="local",
                               AGENTFORGE_ALLOW_UNSAFE_LOCAL_VERIFY=False):
            with self.assertRaises(BoundaryDenied):
                isolated_verification(self.root)

    def test_mocked_offline_docker_gate_runs_two_independent_checks(self):
        commands = []

        def fake_docker(argv, *, timeout):
            commands.append(argv)
            if argv[:2] == ["image", "inspect"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if argv[0] == "run":
                test = "test" in argv
                return SimpleNamespace(
                    returncode=0,
                    stdout="",
                    stderr="Ran 1 test in 0.01s\nOK\n" if test else "System check identified no issues",
                )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("agentforge_django.docker_verify.shutil.which",
                   return_value="/usr/bin/docker"), patch(
                   "agentforge_django.docker_verify._run_docker",
                   side_effect=fake_docker):
            result = docker_verification(self.root)
        self.assertEqual(result["backend"], "docker-offline")
        self.assertTrue(result["passed"])
        self.assertEqual(len([argv for argv in commands if argv[0] == "run"]), 2)
        self.assertFalse((self.root / "myapp.py").is_symlink())

    def test_docker_zero_test_count_is_never_pass(self):
        def fake_docker(argv, *, timeout):
            if argv[:2] == ["image", "inspect"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if argv[0] == "run":
                return SimpleNamespace(
                    returncode=0,
                    stdout="Ran 0 tests in 0.00s" if "test" in argv else "OK",
                    stderr="",
                )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("agentforge_django.docker_verify.shutil.which",
                   return_value="/usr/bin/docker"), patch(
                   "agentforge_django.docker_verify._run_docker",
                   side_effect=fake_docker):
            result = docker_verification(self.root)
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][-1]["reason"], "NO_POSITIVE_DJANGO_TEST_COUNT")

    def test_secret_files_not_copied(self):
        from agentforge_django.verification import copy_workspace
        (self.root / ".env").write_text("API_KEY=SECRET", encoding="utf-8")
        (self.root / "keys.pem").write_text("PRIVATE", encoding="utf-8")
        (self.root / "uploads").mkdir()
        (self.root / "uploads" / "sensitive.txt").write_text("PRIVATE", encoding="utf-8")
        dest = self.root.parent / (self.root.name + "-copied")
        self.addCleanup(lambda: __import__("shutil").rmtree(dest, ignore_errors=True))
        copy_workspace(self.root, dest)
        self.assertFalse((dest / ".env").exists())
        self.assertFalse((dest / "keys.pem").exists())
        self.assertFalse((dest / "uploads").exists())
        self.assertTrue((dest / "myapp.py").is_file())

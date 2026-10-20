"""V1.9 fail-closed Docker cleanup, container inventory and recovery tests."""
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from agentforge_django.docker_verify import (
    build_docker_command, docker_verification, list_verifier_containers,
)
from agentforge_django.guard import BoundaryDenied


NAME = "agentforge-verify-" + "1" * 20
CID = "a" * 64
IMAGE = "sha256:" + "b" * 64


class V19DockerLifecycleTests(SimpleTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="agentforge-v19-lifecycle-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "manage.py").write_text("# synthetic\n", encoding="utf-8")
        (self.root / "tests.py").write_text("def test_safe(): pass\n", encoding="utf-8")

    def test_run_has_dedicated_label_not_user_defined_label(self):
        args = build_docker_command(
            image=IMAGE, source=self.root, name=NAME, check="test"
        )
        self.assertIn("--label", args)
        self.assertEqual(args[args.index("--label") + 1],
                         "org.agentforge.verifier=django-offline")

    def test_inventory_is_read_only_and_bounded(self):
        def fn(args, *, timeout):
            self.assertEqual(args[0], "ps")
            self.assertIn("label=org.agentforge.verifier=django-offline", args)
            self.assertEqual(timeout, 15)
            return SimpleNamespace(
                returncode=0, stdout=f"{CID} {NAME}\n", stderr=""
            )
        with patch("agentforge_django.docker_verify._run_docker", side_effect=fn):
            output = list_verifier_containers()
        self.assertEqual(output, [{"container_id": CID, "name": NAME}])

    def test_docker_error_and_spoofed_label_name_fail_closed(self):
        samples = [
            SimpleNamespace(returncode=1, stdout="", stderr="daemon failed"),
            SimpleNamespace(returncode=0, stdout=f"{CID} other-service\n", stderr=""),
            SimpleNamespace(returncode=0, stdout="this-is-not-an-id " + NAME, stderr=""),
        ]
        for response in samples:
            with self.subTest(response=response), patch(
                "agentforge_django.docker_verify._run_docker",
                return_value=response,
            ):
                with self.assertRaises(BoundaryDenied):
                    list_verifier_containers()

    def test_inventory_timeout_does_not_mean_empty(self):
        with patch("agentforge_django.docker_verify._run_docker",
                   side_effect=subprocess.TimeoutExpired("docker", 15)):
            with self.assertRaises(BoundaryDenied):
                list_verifier_containers()

    def docker_stub(self, argv, *, timeout):
        if argv[:2] == ["image", "inspect"]:
            return SimpleNamespace(returncode=0, stdout=IMAGE + "\n", stderr="")
        if argv[0] == "run":
            tested = "test" in argv
            return SimpleNamespace(
                returncode=0,
                stdout="Ran 1 test in 0.001s\nOK\n" if tested else "OK",
                stderr="",
            )
        if argv[:2] == ["rm", "-f"]:
            # The --rm container already disappeared: docker rm exit=1
            # is normal and should not create a false cleanup failure.
            return SimpleNamespace(returncode=1, stdout="", stderr="No such container")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_docker_already_removed_is_ok_if_ps_proves_absence(self):
        with patch("agentforge_django.docker_verify.shutil.which",
                   return_value="/usr/bin/docker"), patch(
            "agentforge_django.docker_verify._run_docker",
            side_effect=self.docker_stub,
        ):
            result = docker_verification(self.root)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["checks"]), 2)

    def test_cleanup_not_verified_blocks_candidate_even_after_docker_success(self):
        run_calls = []
        def bad_cleanup(argv, *, timeout):
            if argv[0] == "run":
                run_calls.append(argv)
            if argv[:2] == ["ps", "-a"]:
                return SimpleNamespace(
                    returncode=0,
                    stdout=argv[argv.index("--filter") + 1].split("/")[1].rstrip("$") + "\n",
                    stderr="",
                )
            return self.docker_stub(argv, timeout=timeout)
        with patch("agentforge_django.docker_verify.shutil.which",
                   return_value="/usr/bin/docker"), patch(
            "agentforge_django.docker_verify._run_docker",
            side_effect=bad_cleanup,
        ):
            result = docker_verification(self.root)
        self.assertFalse(result["passed"])
        self.assertEqual(len(run_calls), 1)
        self.assertEqual(result["checks"][0]["reason"], "DOCKER_CLEANUP_UNVERIFIED")

    def test_cleanup_inspection_error_is_not_a_pass(self):
        def inspection_failure(argv, *, timeout):
            if argv[:2] == ["ps", "-a"]:
                return SimpleNamespace(returncode=1, stdout="", stderr="daemon unavailable")
            return self.docker_stub(argv, timeout=timeout)
        with patch("agentforge_django.docker_verify.shutil.which",
                   return_value="/usr/bin/docker"), patch(
            "agentforge_django.docker_verify._run_docker",
            side_effect=inspection_failure,
        ):
            result = docker_verification(self.root)
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][0]["reason"], "DOCKER_CLEANUP_UNVERIFIED")

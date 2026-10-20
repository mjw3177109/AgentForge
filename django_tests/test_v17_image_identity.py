"""V1.7 image identity pinning contract and tag-swap attack regressions."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from agentforge_django.docker_verify import (
    docker_verification, resolve_verifier_image
)
from agentforge_django.guard import BoundaryDenied


IMAGE_A = "sha256:" + "a" * 64
IMAGE_B = "sha256:" + "b" * 64


class DockerImageIdentityTests(SimpleTestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory(prefix="agentforge-v17-image-id-")
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        (self.root / "manage.py").write_text("# synthetic fixture\n", "utf-8")
        (self.root / "app").mkdir()
        (self.root / "app" / "tests.py").write_text(
            "def test_original(): pass\n", "utf-8"
        )

    def fake_docker(self, argv, *, timeout):
        if argv[:2] == ["image", "inspect"]:
            return SimpleNamespace(returncode=0, stdout=IMAGE_A + "\n", stderr="")
        if argv[0] == "ps":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout="Ran 1 test in 0.001s\nOK\n" if argv[0] == "run" and "test" in argv else "OK",
            stderr="",
        )

    @override_settings(AGENTFORGE_DOCKER_VERIFY_REQUIRE_PIN=True,
                       AGENTFORGE_DOCKER_VERIFY_IMAGE_ID=IMAGE_A)
    def test_pinned_image_id_used_for_both_docker_phases(self):
        commands = []
        def record(argv, *, timeout):
            commands.append(argv)
            return self.fake_docker(argv, timeout=timeout)
        with patch("agentforge_django.docker_verify.shutil.which", return_value="docker"), patch(
            "agentforge_django.docker_verify._run_docker", side_effect=record
        ):
            report = docker_verification(self.root)
        runs = [x for x in commands if x[0] == "run"]
        self.assertEqual(len(runs), 2)
        for args in runs:
            self.assertIn(IMAGE_A, args)
            self.assertNotIn("agentforge-django-verify:0.4", args)
        self.assertEqual(report["verifier_image_id"], IMAGE_A)
        self.assertTrue(report["passed"])

    @override_settings(AGENTFORGE_DOCKER_VERIFY_REQUIRE_PIN=True,
                       AGENTFORGE_DOCKER_VERIFY_IMAGE_ID=IMAGE_B)
    def test_changed_tag_is_blocked_before_any_docker_run(self):
        with patch("agentforge_django.docker_verify.shutil.which", return_value="docker"), patch(
            "agentforge_django.docker_verify._run_docker",
            side_effect=self.fake_docker
        ) as run:
            with self.assertRaises(BoundaryDenied):
                docker_verification(self.root)
        self.assertEqual(len(run.call_args_list), 1)
        self.assertEqual(run.call_args_list[0].args[0][:2], ["image", "inspect"])

    @override_settings(AGENTFORGE_DOCKER_VERIFY_REQUIRE_PIN=True,
                       AGENTFORGE_DOCKER_VERIFY_IMAGE_ID=None)
    def test_missing_required_image_pin_is_refused_before_inspect(self):
        with patch("agentforge_django.docker_verify._run_docker") as run:
            with self.assertRaises(BoundaryDenied):
                resolve_verifier_image("agentforge-django-verify:0.4")
        run.assert_not_called()

    @override_settings(AGENTFORGE_DOCKER_VERIFY_REQUIRE_PIN=False,
                       AGENTFORGE_DOCKER_VERIFY_IMAGE_ID=None)
    def test_malformed_image_identity_is_denied_even_in_ci(self):
        for image_id in ("", "sha256:fake", "sha256:" + "A" * 64,
                         "sha256:" + "a" * 64 + " EXTRA"):
            with self.subTest(image_id=image_id), patch(
                "agentforge_django.docker_verify._run_docker",
                return_value=SimpleNamespace(returncode=0, stdout=image_id, stderr="")
            ):
                with self.assertRaises(BoundaryDenied):
                    resolve_verifier_image("agentforge-django-verify:0.4")

    @override_settings(AGENTFORGE_DOCKER_VERIFY_REQUIRE_PIN=True,
                       AGENTFORGE_DOCKER_VERIFY_IMAGE_ID="sha256:INVALID")
    def test_incorrect_operator_pin_syntax_is_blocked(self):
        with patch("agentforge_django.docker_verify._run_docker") as run:
            with self.assertRaises(BoundaryDenied):
                resolve_verifier_image("agentforge-django-verify:0.4")
        run.assert_not_called()

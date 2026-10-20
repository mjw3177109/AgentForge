"""V2.1 group termination invariants, without model/network/Docker calls."""
import os
import signal
import subprocess
from types import SimpleNamespace
from unittest.mock import call, patch

from django.test import SimpleTestCase

from agentforge_django.v21_process_guard import (
    group_quiescent, terminate_process_group,
)


class V21ProcessGroupTests(SimpleTestCase):
    def test_parent_exits_on_term_but_final_kill_still_sent_to_descendants(self):
        child = SimpleNamespace(pid=43129, wait=lambda timeout: 0)
        with patch(
            "agentforge_django.v21_process_guard.os.killpg"
        ) as kill, patch(
            "agentforge_django.v21_process_guard.group_quiescent",
            return_value=True,
        ):
            self.assertTrue(
                terminate_process_group(child, term_grace=0.1, kill_grace=0.1)
            )
        self.assertEqual(kill.call_args_list, [
            call(43129, signal.SIGTERM),
            call(43129, signal.SIGKILL),
        ])

    def test_group_persists_after_kill_is_not_a_success(self):
        child = SimpleNamespace(pid=43129, wait=lambda timeout: 0)
        with patch(
            "agentforge_django.v21_process_guard.os.killpg"
        ), patch(
            "agentforge_django.v21_process_guard.group_quiescent",
            return_value=False,
        ), patch(
            "agentforge_django.v21_process_guard.time.sleep"
        ):
            with patch(
                "agentforge_django.v21_process_guard.time.monotonic",
                side_effect=[1.0, 1.1, 2.0],
            ):
                self.assertFalse(
                    terminate_process_group(child, term_grace=.1, kill_grace=.5)
                )

    def test_sigterm_timeout_escalates_to_kill(self):
        times = iter([subprocess.TimeoutExpired("synthetic", 1), 0])
        child = SimpleNamespace(pid=43129, wait=lambda timeout: next(times))
        with patch(
            "agentforge_django.v21_process_guard.os.killpg"
        ) as kill, patch(
            "agentforge_django.v21_process_guard.group_quiescent",
            return_value=True,
        ):
            self.assertTrue(terminate_process_group(child, term_grace=.1, kill_grace=.1))
        self.assertEqual(kill.call_args_list[1], call(43129, signal.SIGKILL))

    def test_failed_group_signal_does_not_claim_success(self):
        child = SimpleNamespace(pid=43129, wait=lambda timeout: 0)
        with patch(
            "agentforge_django.v21_process_guard.os.killpg",
            side_effect=PermissionError,
        ), patch(
            "agentforge_django.v21_process_guard.group_quiescent",
            return_value=True,
        ):
            self.assertFalse(terminate_process_group(child, term_grace=.1, kill_grace=.1))

    def test_group_pid_validation_and_missing_proc(self):
        self.assertFalse(group_quiescent(1))
        self.assertFalse(group_quiescent(-1))
        self.assertFalse(group_quiescent(True))
        with patch(
            "agentforge_django.v21_process_guard.os.killpg",
            side_effect=ProcessLookupError,
        ):
            self.assertTrue(group_quiescent(43129))

    def test_bad_cleanup_durations_do_not_signal_pid(self):
        child = SimpleNamespace(pid=43129)
        with patch("agentforge_django.v21_process_guard.os.killpg") as killed:
            self.assertFalse(terminate_process_group(child, term_grace=0))
            self.assertFalse(terminate_process_group(child, kill_grace=31))
        killed.assert_not_called()

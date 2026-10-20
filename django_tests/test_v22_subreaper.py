"""V2.2 Linux subreaper fail-closed contracts; no paid model calls."""
import os
import signal
from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase
from agentforge_django.v22_subreaper import (
    adopted_child_pids, drain_adopted_children, exclusive_subreaper,
    _kill_adopted_child,
)


class SubreaperSafetyTests(SimpleTestCase):
    def test_exclusive_supervision_denies_preexisting_child_without_prctl(self):
        with patch(
            "agentforge_django.v22_subreaper.adopted_child_pids",
            return_value={9012},
        ), patch(
            "agentforge_django.v22_subreaper.ctypes.CDLL"
        ) as libc:
            with self.assertRaisesRegex(RuntimeError, "already owns child"):
                with exclusive_subreaper():
                    pass
        libc.assert_not_called()

    def test_fail_closed_when_proc_inventory_is_unavailable(self):
        with patch(
            "agentforge_django.v22_subreaper.adopted_child_pids",
            side_effect=PermissionError,
        ):
            self.assertEqual(
                drain_adopted_children(seconds=.2), (False, False)
            )

    def test_pidfd_send_signal_is_only_for_current_adopted_child(self):
        fd = 80
        with patch(
            "agentforge_django.v22_subreaper.os.pidfd_open",
            return_value=fd
        ), patch(
            "agentforge_django.v22_subreaper.adopted_child_pids",
            return_value={9012}
        ), patch(
            "agentforge_django.v22_subreaper.signal.pidfd_send_signal"
        ) as send, patch("agentforge_django.v22_subreaper.os.close"):
            self.assertTrue(_kill_adopted_child(9012))
        send.assert_called_once_with(fd, signal.SIGKILL, None, 0)

    def test_pid_not_current_child_is_never_signalled(self):
        with patch(
            "agentforge_django.v22_subreaper.os.pidfd_open",
            return_value=80
        ), patch(
            "agentforge_django.v22_subreaper.adopted_child_pids",
            return_value=set()
        ), patch(
            "agentforge_django.v22_subreaper.signal.pidfd_send_signal"
        ) as send, patch("agentforge_django.v22_subreaper.os.close"):
            self.assertTrue(_kill_adopted_child(9012))
        send.assert_not_called()

    def test_invalid_timeout_never_starts_cleanup(self):
        with patch(
            "agentforge_django.v22_subreaper.adopted_child_pids"
        ) as child:
            self.assertEqual(drain_adopted_children(seconds=0), (False, False))
            self.assertEqual(drain_adopted_children(seconds=True), (False, False))
            self.assertEqual(drain_adopted_children(seconds=16), (False, False))
        child.assert_not_called()

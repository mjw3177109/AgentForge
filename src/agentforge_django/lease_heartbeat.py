"""Optional PostgreSQL-only worker heartbeat and ownership fence."""
import threading
from django.conf import settings
from django.db import close_old_connections, connections, connection
from django.utils import timezone
from .guard import BoundaryDenied
from .models import AgentJob, JobLease


class LeaseHeartbeat:
    def __init__(self, *, job_id, project_id, token):
        self.job_id = job_id
        self.project_id = project_id
        self.token = token
        self.beats = 0
        self.lost = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if not getattr(settings, "AGENTFORGE_V09_HEARTBEAT_ENABLED", False):
            return self
        if connection.vendor != "postgresql":
            raise BoundaryDenied("V0.9 heartbeat requires PostgreSQL")
        interval = getattr(settings, "AGENTFORGE_V09_HEARTBEAT_INTERVAL", 10)
        if type(interval) is not int or not 1 <= interval <= 60:
            raise BoundaryDenied("V0.9 heartbeat interval must be 1-60 seconds")
        self._thread = threading.Thread(
            target=self._loop, args=(interval,), daemon=True,
            name="agentforge-lease-heartbeat",
        )
        self._thread.start()
        return self

    def _loop(self, interval):
        try:
            close_old_connections()
            while not self._stop.wait(interval):
                updated = JobLease.objects.filter(
                    project_id=self.project_id, job_id=self.job_id,
                    owner_token=self.token,
                ).update(heartbeat_at=timezone.now())
                running = AgentJob.objects.filter(
                    pk=self.job_id, status=AgentJob.Status.RUNNING,
                ).exists()
                if updated != 1 or not running:
                    self.lost.set()
                    return
                self.beats += 1
        except Exception:
            self.lost.set()
        finally:
            connections.close_all()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                self.lost.set()
        return not self.lost.is_set()


def lease_owned(*, project_id, job_id, token):
    return JobLease.objects.filter(
        project_id=project_id, job_id=job_id, owner_token=token,
    ).exists()

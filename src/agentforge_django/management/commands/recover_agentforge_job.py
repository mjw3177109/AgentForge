from django.core.management.base import BaseCommand, CommandError

from agentforge_django.models import AgentJob
from agentforge_django.recovery import RecoveryDenied, recover_stopped_worker


class Command(BaseCommand):
    help = "Explicitly recover a stale lease ONLY after its worker has stopped."

    def add_arguments(self, parser):
        parser.add_argument("job_id")
        parser.add_argument("--confirm-worker-stopped", action="store_true")

    def handle(self, *args, **options):
        try:
            job = recover_stopped_worker(
                options["job_id"],
                operator_confirmed=options["confirm_worker_stopped"],
            )
        except (AgentJob.DoesNotExist, RecoveryDenied, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Recovered: {job.pk} ({job.status})")

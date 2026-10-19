from django.core.management.base import BaseCommand, CommandError

from agentforge_django.models import AgentJob
from agentforge_django.runner import run_job


class Command(BaseCommand):
    help = "Run exactly one queued AgentForge job. Never deploy or modify host project."

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=str)

    def handle(self, *args, **options):
        try:
            job = AgentJob.objects.get(pk=options["job_id"])
        except (AgentJob.DoesNotExist, ValueError, TypeError) as exc:
            raise CommandError("Unknown job_id") from exc
        run_job(job.pk)
        job.refresh_from_db()
        self.stdout.write(f"{job.pk}: {job.status}")
        if job.status not in (AgentJob.Status.PASS, AgentJob.Status.PROPOSED):
            raise CommandError(f"AgentForge gate did not pass: {job.status}")

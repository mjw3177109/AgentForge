from django.core.management.base import BaseCommand, CommandError

from agentforge_django.queue import process_pending


class Command(BaseCommand):
    help = "Process a bounded PENDING queue once. Defaults to static AUDIT tasks only."

    def add_arguments(self, parser):
        parser.add_argument("--max-jobs", type=int, default=1)
        parser.add_argument("--include-verify", action="store_true")
        parser.add_argument("--include-autonomous", action="store_true")
        parser.add_argument("--project-id", type=int)

    def handle(self, *args, **options):
        try:
            result = process_pending(
                max_jobs=options["max_jobs"],
                include_verify=options["include_verify"],
                include_autonomous=options["include_autonomous"],
                project_id=options["project_id"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        for item in result["processed"]:
            self.stdout.write(f"{item['job_id']}: {item['status']}")
        self.stdout.write(
            f"Processed: {len(result['processed'])}; "
            f"busy/skipped: {len(result['busy_or_skipped'])}"
        )

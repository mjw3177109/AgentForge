"""Operationally read-only worker preflight. No migrations or paid calls."""
import json

from django.core.management.base import BaseCommand, CommandError
from agentforge_django.worker_readiness import worker_readiness


class Command(BaseCommand):
    help = "Fail-closed DB, migration, Docker image ID and worker-role preflight."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode", choices=("dedicated", "ci-staging"), default="dedicated"
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        result = worker_readiness(mode=options["mode"])
        if options["json"]:
            self.stdout.write(json.dumps(result, sort_keys=True))
        else:
            for entry in result["checks"]:
                self.stdout.write(
                    f"{entry['check']}: " +
                    ("PASS" if entry["passed"] else entry["failure_code"])
                )
            self.stdout.write(
                f"Checks: {result['checks_passed']}/{result['checks_total']}"
            )
        if not result["ready_to_accept_candidate_only_jobs"]:
            raise CommandError("WORKER_PREFLIGHT_REJECTED")

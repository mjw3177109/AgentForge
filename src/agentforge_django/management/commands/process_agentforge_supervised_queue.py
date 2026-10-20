"""Dedicated VM only: read-only preflight then bounded OS-supervised job."""
import json

from django.core.management.base import BaseCommand

from agentforge_django.v20_supervised import process_one_supervised


class Command(BaseCommand):
    help = "Run at most one task through V2.0 bounded child supervisor."

    def add_arguments(self, parser):
        parser.add_argument("--mode", choices=("dedicated", "ci-staging"),
                            default="dedicated")
        parser.add_argument("--timeout-seconds", type=int, default=780)
        parser.add_argument("--include-autonomous", action="store_true")
        parser.add_argument("--include-verify", action="store_true")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        result = process_one_supervised(
            mode=options["mode"],
            timeout_seconds=options["timeout_seconds"],
            include_autonomous=options["include_autonomous"],
            include_verify=options["include_verify"],
        )
        if options["json"]:
            self.stdout.write(json.dumps(result, sort_keys=True))
        else:
            self.stdout.write(
                f"{result['status']}: {result['selected_job_id'] or 'none'}"
            )

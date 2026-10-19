"""Operator-safe lease inspection; never mutates worker ownership."""
import json

from django.core.management.base import BaseCommand, CommandError

from agentforge_django.lease_diagnostics import lease_diagnostics


class Command(BaseCommand):
    help = "Inspect worker leases without stealing, retrying, or recovering jobs."

    def add_arguments(self, parser):
        parser.add_argument("--stale-after-minutes", type=int, default=20)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        try:
            rows = lease_diagnostics(stale_after_minutes=options["stale_after_minutes"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        if options["json"]:
            self.stdout.write(json.dumps({
                "leases": rows,
                "note": "Suspected stale is NOT proof the old worker stopped",
            }, ensure_ascii=False))
        else:
            for row in rows:
                self.stdout.write(
                    f"{row['project']}: {row['job_id']} {row['job_status']} "
                    f"age={row['age_seconds']}s suspected_stale={row['suspected_stale']}"
                )
            self.stdout.write(f"Leases inspected: {len(rows)}; no mutation performed")

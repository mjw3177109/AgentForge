"""Read-only Docker orphan inspection, never auto-remove unknown containers."""
import json

from django.core.management.base import BaseCommand, CommandError
from agentforge_django.docker_verify import list_verifier_containers
from agentforge_django.guard import BoundaryDenied


class Command(BaseCommand):
    help = "Inspect residual AgentForge-labelled verifier containers; never remove."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--fail-if-any", action="store_true")

    def handle(self, *args, **opts):
        try:
            containers = list_verifier_containers()
        except BoundaryDenied as exc:
            raise CommandError("Docker inventory is unavailable; do not recover tasks") from exc
        report = {
            "schema": "agentforge.django.v19.orphan-container-audit.v1",
            "remaining_count": len(containers),
            "containers": containers,
            "automatic_container_removal": False,
            "safe_to_recover_worker_process": False,
            "note": "Container absence alone does not prove the Worker process exited.",
        }
        if opts["json"]:
            self.stdout.write(json.dumps(report, sort_keys=True))
        else:
            self.stdout.write(
                f"Verifier containers present: {len(containers)} (read-only audit)"
            )
            for item in containers:
                self.stdout.write(item["name"])
        if opts["fail_if_any"] and containers:
            raise CommandError("VERIFIER_CONTAINERS_REMAIN; manual inspection required")

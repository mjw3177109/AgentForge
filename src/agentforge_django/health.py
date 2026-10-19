"""Conservative monitoring statistics; static audits do not prove business behavior."""

from datetime import timedelta

from django.utils import timezone

from .models import AgentJob, ManagedProject


def project_health(project, days=30):
    window = timezone.now() - timedelta(days=days)
    jobs = AgentJob.objects.filter(project=project, created_at__gte=window)
    counters = {status: 0 for status in AgentJob.Status.values}
    counts_by_mode = {mode: 0 for mode in AgentJob.Mode.values}
    for status, mode in jobs.values_list("status", "mode"):
        if status in counters:
            counters[status] += 1
        if mode in counts_by_mode:
            counts_by_mode[mode] += 1

    latest_verify = jobs.filter(mode=AgentJob.Mode.VERIFY).order_by(
        "-created_at", "-pk"
    ).values("status", "created_at", "result").first()
    verified = False
    if latest_verify:
        checks = latest_verify["result"].get("independent_verification", {})
        verified = (
            latest_verify["status"] == AgentJob.Status.PASS
            and checks.get("passed") is True
            and checks.get("business_tests_executed") is True
        )
    completed = (counters[AgentJob.Status.PASS] + counters[AgentJob.Status.PROPOSED] +
                 counters[AgentJob.Status.BLOCKED] + counters[AgentJob.Status.FAIL])
    successful = counters[AgentJob.Status.PASS] + counters[AgentJob.Status.PROPOSED]
    # Descriptive observed task completion only, NOT long-term model reliability.
    rate = round(successful / completed * 100, 1) if completed else None
    if not project.enabled:
        state = "DISABLED"
    elif counters[AgentJob.Status.FAIL] or counters[AgentJob.Status.BLOCKED]:
        state = "ATTENTION"
    elif verified:
        state = "VERIFIED_TESTS"
    elif completed:
        state = "AUDIT_ONLY_OR_UNVERIFIED"
    else:
        state = "NO_DATA"
    return {
        "project": project,
        "state": state,
        "counts": counters,
        "modes": counts_by_mode,
        "observed_completion_pct": rate,
        "latest_verification": latest_verify,
        "verified_business_tests": verified,
        "window_days": days,
    }


def fleet_summary(days=30):
    rows = [project_health(item, days=days) for item in
            ManagedProject.objects.order_by("name")[:100]]
    return {
        "projects": rows,
        "total_projects": len(rows),
        "attention_projects": sum(r["state"] == "ATTENTION" for r in rows),
        "verified_projects": sum(r["verified_business_tests"] for r in rows),
    }

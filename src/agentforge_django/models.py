import uuid

from django.conf import settings
from django.db import models


class ManagedProject(models.Model):
    """Explicitly allowlisted local Django workspace. Not a production deployment target."""

    name = models.CharField(max_length=120, unique=True)
    root_path = models.CharField(max_length=1024)
    enabled = models.BooleanField(default=False)
    autonomous_enabled = models.BooleanField(default=False)
    base_branch = models.CharField(max_length=128, default="main")
    profiles_path = models.CharField(max_length=255, default=".agent/execution-profiles.yaml")
    write_scopes = models.JSONField(default=list, blank=True)
    run_business_tests = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class AgentJob(models.Model):
    class Mode(models.TextChoices):
        AUDIT = "AUDIT", "只读项目巡检"
        VERIFY = "VERIFY", "隔离环境业务验收"
        AUTONOMOUS = "AUTONOMOUS", "授权自治（仅生成候选补丁）"

    class Status(models.TextChoices):
        PENDING = "PENDING", "待执行"
        RUNNING = "RUNNING", "执行中"
        PASS = "PASS", "验证通过"
        PROPOSED = "PROPOSED", "候选补丁待人工审核"
        BLOCKED = "BLOCKED", "权限或条件阻断"
        FAIL = "FAIL", "执行失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(ManagedProject, on_delete=models.PROTECT, related_name="jobs")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.AUDIT)
    request = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    result = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.mode} {self.id}"


class MutationApproval(models.Model):
    """Human approval pins write scopes and repository HEAD at the time of approval."""

    job = models.OneToOneField(AgentJob, on_delete=models.CASCADE, related_name="approval")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    base_commit = models.CharField(max_length=40)
    approved_scopes = models.JSONField(default=list)
    reason = models.TextField()
    approved_at = models.DateTimeField(auto_now_add=True)
    request_sha256 = models.CharField(max_length=64, blank=True, default="")
    configuration_sha256 = models.CharField(max_length=64, blank=True, default="")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("MutationApproval cannot be updated; create a new job")
        from .approvals import approval_digests
        self.request_sha256, self.configuration_sha256 = approval_digests(self.job)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Approval {self.job_id}"


class AuditEvent(models.Model):
    job = models.ForeignKey(AgentJob, on_delete=models.CASCADE, related_name="events")
    sequence = models.PositiveIntegerField()
    phase = models.CharField(max_length=40)
    decision = models.CharField(max_length=24)
    detail = models.JSONField(default=dict)
    previous_hash = models.CharField(max_length=64, blank=True)
    event_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("job_id", "sequence")
        constraints = [
            models.UniqueConstraint(fields=["job", "sequence"], name="af_dj_job_event_sequence")
        ]


class JobLease(models.Model):
    """Single active worker per project. A crash requires explicit operator recovery."""

    project = models.OneToOneField(
        ManagedProject, on_delete=models.CASCADE, related_name="worker_lease"
    )
    job = models.ForeignKey(AgentJob, on_delete=models.PROTECT, related_name="leases")
    owner_token = models.UUIDField(default=uuid.uuid4, editable=False)
    acquired_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Lease {self.project_id}/{self.job_id}"

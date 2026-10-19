from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="ManagedProject",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("root_path", models.CharField(max_length=1024)),
                ("enabled", models.BooleanField(default=False)),
                ("autonomous_enabled", models.BooleanField(default=False)),
                ("base_branch", models.CharField(default="main", max_length=128)),
                ("profiles_path", models.CharField(
                    default=".agent/execution-profiles.yaml", max_length=255)),
                ("write_scopes", models.JSONField(blank=True, default=list)),
                ("run_business_tests", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="AgentJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("mode", models.CharField(choices=[
                    ("AUDIT", "只读项目巡检"), ("VERIFY", "隔离环境业务验收"),
                    ("AUTONOMOUS", "授权自治（仅生成候选补丁）")],
                    default="AUDIT", max_length=16)),
                ("request", models.TextField(blank=True)),
                ("status", models.CharField(choices=[
                    ("PENDING", "待执行"), ("RUNNING", "执行中"),
                    ("PASS", "验证通过"), ("PROPOSED", "候选补丁待人工审核"),
                    ("BLOCKED", "权限或条件阻断"), ("FAIL", "执行失败")],
                    default="PENDING", max_length=16)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                              related_name="jobs",
                                              to="agentforge_django.managedproject")),
                ("requested_by", models.ForeignKey(blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="MutationApproval",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("base_commit", models.CharField(max_length=40)),
                ("approved_scopes", models.JSONField(default=list)),
                ("reason", models.TextField()),
                ("approved_at", models.DateTimeField(auto_now_add=True)),
                ("approved_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to=settings.AUTH_USER_MODEL)),
                ("job", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                             related_name="approval",
                                             to="agentforge_django.agentjob")),
            ],
        ),
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("sequence", models.PositiveIntegerField()),
                ("phase", models.CharField(max_length=40)),
                ("decision", models.CharField(max_length=24)),
                ("detail", models.JSONField(default=dict)),
                ("previous_hash", models.CharField(blank=True, max_length=64)),
                ("event_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                          related_name="events",
                                          to="agentforge_django.agentjob")),
            ],
            options={"ordering": ("job_id", "sequence")},
        ),
        migrations.AddConstraint(
            model_name="auditevent",
            constraint=models.UniqueConstraint(
                fields=("job", "sequence"), name="af_dj_job_event_sequence"),
        ),
    ]

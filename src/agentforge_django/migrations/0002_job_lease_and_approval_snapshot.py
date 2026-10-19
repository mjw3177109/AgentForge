from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("agentforge_django", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="mutationapproval",
            name="request_sha256",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="mutationapproval",
            name="configuration_sha256",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.CreateModel(
            name="JobLease",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                          serialize=False, verbose_name="ID")),
                ("owner_token", models.UUIDField(default=uuid.uuid4, editable=False)),
                ("acquired_at", models.DateTimeField(auto_now_add=True)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                          related_name="leases",
                                          to="agentforge_django.agentjob")),
                ("project", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="worker_lease", to="agentforge_django.managedproject")),
            ],
        ),
    ]

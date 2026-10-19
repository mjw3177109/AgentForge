from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agentforge_django", "0002_job_lease_and_approval_snapshot"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditevent",
            name="decision",
            field=models.CharField(max_length=64),
        ),
    ]

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("agentforge_django", "0003_expand_audit_decision")]

    operations = [
        migrations.AddField(
            model_name="joblease", name="heartbeat_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]

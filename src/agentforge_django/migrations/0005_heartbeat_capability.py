from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agentforge_django", "0004_lease_heartbeat")]

    operations = [
        migrations.AddField(
            model_name="joblease", name="heartbeat_enabled",
            field=models.BooleanField(default=False),
        ),
    ]

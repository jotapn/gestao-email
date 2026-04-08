from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("emails", "0003_workspacesetting"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspacesetting",
            name="google_workspace_alert_email",
            field=models.EmailField(
                blank=True,
                default="sistemas@oratelecom.com.br",
                max_length=254,
                verbose_name="e-mail de alerta do Google Workspace",
            ),
        ),
    ]

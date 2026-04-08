from django.db import migrations, models


def migrate_system_admin(apps, schema_editor):
    UserProfile = apps.get_model("emails", "UserProfile")
    for profile in UserProfile.objects.select_related("user").all():
        if profile.user.is_superuser:
            profile.is_system_admin = True
            profile.is_admin = False
            profile.save(update_fields=["is_system_admin", "is_admin"])


class Migration(migrations.Migration):

    dependencies = [
        ("emails", "0004_workspacesetting_google_workspace_alert_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="is_system_admin",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(migrate_system_admin, migrations.RunPython.noop),
    ]

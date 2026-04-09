from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("emails", "0005_userprofile_is_system_admin"),
    ]

    operations = [
        migrations.AlterField(
            model_name="emaillog",
            name="criado_em",
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
    ]

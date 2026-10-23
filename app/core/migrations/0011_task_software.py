from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_file_sha256'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='task',
            name='tool_version',
        ),
        migrations.AddField(
            model_name='task',
            name='software',
            field=models.JSONField(blank=True, default=list),
        ),
    ]

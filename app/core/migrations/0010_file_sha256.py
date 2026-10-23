from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_task_step_required'),
    ]

    operations = [
        migrations.AddField(
            model_name='file',
            name='sha256',
            field=models.CharField(blank=True, max_length=64),
        ),
    ]

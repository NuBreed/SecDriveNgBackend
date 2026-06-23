from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('journeys', '0002_trackinglink_journeyshare'),
    ]

    operations = [
        migrations.AddField(
            model_name='journey',
            name='group_size',
            field=models.PositiveSmallIntegerField(default=1),
        ),
    ]

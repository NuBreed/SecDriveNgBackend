from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('drivers', '0003_driver_participant_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='DriverPresence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('lat', models.FloatField()),
                ('lng', models.FloatField()),
                ('speed_kmh', models.FloatField(default=0.0)),
                ('heading', models.FloatField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('driver', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='presence',
                    to='drivers.driver',
                )),
            ],
        ),
    ]

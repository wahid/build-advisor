from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wiki", "0008_load_leveling"),
    ]

    operations = [
        migrations.AddField(
            model_name="source",
            name="author",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="source",
            name="updated_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="document",
            name="doc_type",
            field=models.CharField(
                choices=[
                    ("gem", "Gem"),
                    ("unique", "Unique item"),
                    ("ascendancy", "Ascendancy"),
                    ("mechanic", "Mechanic"),
                    ("patch", "Patch notes"),
                    ("guide", "Build guide"),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="chunk",
            name="doc_type",
            field=models.CharField(
                choices=[
                    ("gem", "Gem"),
                    ("unique", "Unique item"),
                    ("ascendancy", "Ascendancy"),
                    ("mechanic", "Mechanic"),
                    ("patch", "Patch notes"),
                    ("guide", "Build guide"),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="MaxrollRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("url", models.URLField(max_length=500)),
                ("requested_at", models.DateTimeField(db_index=True)),
                ("status", models.PositiveSmallIntegerField(blank=True, null=True)),
            ],
            options={"ordering": ["-requested_at"]},
        ),
    ]

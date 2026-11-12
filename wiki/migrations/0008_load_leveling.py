"""Load the shipped leveling data (wiki/fixtures/leveling.json.gz) into empty tables.

refresh_wiki keeps it current afterwards; this gives a server without wiki access
the data right away.
"""

import gzip
import json
from pathlib import Path

from django.db import migrations

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "leveling.json.gz"


def load(apps, schema_editor):
    QuestReward = apps.get_model("wiki", "QuestReward")
    GemLevel = apps.get_model("wiki", "GemLevel")
    if not FIXTURE.exists() or QuestReward.objects.exists():
        return
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    QuestReward.objects.bulk_create(QuestReward(**row) for row in data["rewards"])
    GemLevel.objects.bulk_create(GemLevel(**row) for row in data["gems"])


class Migration(migrations.Migration):
    dependencies = [("wiki", "0007_leveling")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]

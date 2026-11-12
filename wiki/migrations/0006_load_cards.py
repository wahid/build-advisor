"""Load the shipped tooltip cards (wiki/fixtures/cards.jsonl.gz) into existing pages.

Pages fetched from now on get their card when they're downloaded; this fills in
pages a database already has, e.g. on the demo server, which has no page cache.
"""

import gzip
import json
from pathlib import Path

from django.db import migrations

CARDS = Path(__file__).resolve().parent.parent / "fixtures" / "cards.jsonl.gz"


def load(apps, schema_editor):
    if not CARDS.exists():
        return
    Document = apps.get_model("wiki", "Document")
    titles = set(Document.objects.filter(card__isnull=True).values_list("title", flat=True))
    if not titles:
        return
    with gzip.open(CARDS, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["title"] in titles:
                Document.objects.filter(title=row["title"], card__isnull=True).update(card=row["card"])


class Migration(migrations.Migration):
    dependencies = [("wiki", "0005_document_card")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]

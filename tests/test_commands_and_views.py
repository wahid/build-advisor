from io import StringIO

import pytest
from django.core.management import call_command

from wiki.ingest import IngestResult

pytestmark = pytest.mark.django_db


def test_fetch_wiki_runs_ingest(mocker) -> None:
    run = mocker.patch(
        "wiki.management.commands.fetch_wiki.ingest",
        return_value=IngestResult(patch="3.29.3c", created=3, failed=["X"]),
    )
    out = StringIO()

    call_command("fetch_wiki", "--type", "gem", "--limit", "3", stdout=out)

    run.assert_called_once_with(doc_types=["gem"], limit=3, refresh=False)
    assert "3 created" in out.getvalue()
    assert "failed: X" in out.getvalue()


def test_fetch_wiki_async_queues_task(mocker) -> None:
    delay = mocker.patch("wiki.management.commands.fetch_wiki.ingest_wiki.delay")
    delay.return_value.id = "abc"
    out = StringIO()

    call_command("fetch_wiki", "--async", stdout=out)

    delay.assert_called_once_with(doc_types=None, limit=None, refresh=False)
    assert "abc" in out.getvalue()


def test_celery_task_returns_result_dict(mocker) -> None:
    from wiki.tasks import ingest_wiki

    mocker.patch("wiki.tasks.ingest", return_value=IngestResult(patch="3.29.3c", created=1))

    assert ingest_wiki.run(doc_types=["gem"])["created"] == 1


def test_health_endpoint(client) -> None:
    response = client.get("/api/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "documents": 0}

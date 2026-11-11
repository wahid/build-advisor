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

    run.assert_called_once_with(doc_types=["gem"], limit=3, refresh=False, direct=False)
    assert "3 created" in out.getvalue()
    assert "failed: X" in out.getvalue()


def test_fetch_wiki_async_queues_task(mocker) -> None:
    delay = mocker.patch("wiki.management.commands.fetch_wiki.ingest_wiki.delay")
    delay.return_value.id = "abc"
    out = StringIO()

    call_command("fetch_wiki", "--async", stdout=out)

    delay.assert_called_once_with(doc_types=None, limit=None, refresh=False, direct=False)
    assert "abc" in out.getvalue()


def test_fetch_wiki_direct_flag(mocker) -> None:
    run = mocker.patch(
        "wiki.management.commands.fetch_wiki.ingest", return_value=IngestResult(patch="x")
    )

    call_command("fetch_wiki", "--direct", stdout=StringIO())

    assert run.call_args.kwargs["direct"] is True


def test_celery_task_returns_result_dict(mocker) -> None:
    from wiki.tasks import ingest_wiki

    mocker.patch("wiki.tasks.ingest", return_value=IngestResult(patch="3.29.3c", created=1))

    assert ingest_wiki.run(doc_types=["gem"])["created"] == 1


def test_health_endpoint(client) -> None:
    response = client.get("/api/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "documents": 0}


def test_build_index_command(mocker) -> None:
    from wiki.indexing import ChunkResult

    chunks = mocker.patch(
        "wiki.management.commands.build_index.build_chunks",
        return_value=ChunkResult(documents=2, chunks=9, reused_embeddings=1),
    )
    embed = mocker.patch("wiki.management.commands.build_index.embed_pending", return_value=8)
    out = StringIO()

    call_command("build_index", "--limit", "8", stdout=out)

    chunks.assert_called_once_with(force=False)
    embed.assert_called_once_with(limit=8)
    assert "9 chunks" in out.getvalue()
    assert "Embedded 8" in out.getvalue()


def test_build_index_no_embed_and_async(mocker) -> None:
    from wiki.indexing import ChunkResult

    mocker.patch("wiki.management.commands.build_index.build_chunks", return_value=ChunkResult())
    embed = mocker.patch("wiki.management.commands.build_index.embed_pending")
    delay = mocker.patch("wiki.management.commands.build_index.build_index.delay")
    delay.return_value.id = "xyz"

    call_command("build_index", "--no-embed", stdout=StringIO())
    embed.assert_not_called()

    out = StringIO()
    call_command("build_index", "--async", "--force", stdout=out)
    delay.assert_called_once_with(force=True, embed=True)
    assert "xyz" in out.getvalue()


def test_fetch_wiki_reports_block_as_command_error(mocker) -> None:
    from django.core.management import CommandError

    from wiki.client import WikiBlockedError

    mocker.patch(
        "wiki.management.commands.fetch_wiki.ingest", side_effect=WikiBlockedError("blocked")
    )

    with pytest.raises(CommandError, match="continues where it stopped"):
        call_command("fetch_wiki", stdout=StringIO())


def test_fetch_wiki_list_only_downloads_nothing(mocker) -> None:
    from django.utils import timezone

    from wiki.models import Source

    Source.objects.create(
        page_title="Leech", url="https://wiki.test/wiki/Leech", fetched_at=timezone.now()
    )
    client = mocker.Mock()
    client.list_titles.return_value = ["Ignite", "Leech"]
    mocker.patch("wiki.client.WikiClient.from_settings", return_value=client)
    run = mocker.patch("wiki.management.commands.fetch_wiki.ingest")
    out = StringIO()

    call_command("fetch_wiki", "--list-only", "--type", "mechanic", stdout=out)

    run.assert_not_called()
    assert "mechanic: 2 pages, 1 not saved yet" in out.getvalue()
    assert "+ Ignite" in out.getvalue()


def test_fetch_wiki_lists_subcategories(mocker) -> None:
    client = mocker.Mock()
    client.subcategory_sizes.return_value = {"Category:Quests": 300, "Category:Ailments": 12}
    mocker.patch("wiki.client.WikiClient.from_settings", return_value=client)
    out = StringIO()

    call_command("fetch_wiki", "--subcategories", "--type", "mechanic", stdout=out)

    assert "  300  Category:Quests" in out.getvalue()
    assert "   12  Category:Ailments" in out.getvalue()

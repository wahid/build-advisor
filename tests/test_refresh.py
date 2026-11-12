"""Keeping the wiki data current: recent patch notes and the refresh command."""

from datetime import date
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from wiki.client import WikiBlockedError, recent_versions
from wiki.ingest import IngestResult
from wiki.models import DocumentType


@pytest.fixture(autouse=True)
def no_leveling_download(mocker):
    return mocker.patch(
        "wiki.management.commands.refresh_wiki.leveling.update", return_value=(529, 800)
    )


def test_patch_notes_are_the_versions_of_the_last_year() -> None:
    listing = recent_versions(date(2026, 11, 12))

    assert listing.tables == "versions"
    assert 'release_date >= "2025-11-12"' in listing.where
    assert 'release_date <= "2026-11-12"' in listing.where


def test_the_client_lists_version_pages_for_patch_notes(wiki_client, mocker) -> None:
    cargo = mocker.patch.object(
        wiki_client, "_cargo", return_value=[{"page": "Version 3.29.3"}, {"page": "Version 3.29.0"}]
    )

    titles = wiki_client.list_titles(DocumentType.PATCH, today=date(2026, 11, 12))

    assert titles == ["Version 3.29.0", "Version 3.29.3"]
    assert cargo.call_args.kwargs["tables"] == "versions"


@pytest.mark.django_db
def test_refresh_downloads_changes_then_reindexes(mocker) -> None:
    ingest = mocker.patch(
        "wiki.management.commands.refresh_wiki.ingest",
        return_value=IngestResult(patch="3.29.3c", created=2, updated=5, unchanged=2900),
    )
    chunks = mocker.patch("wiki.management.commands.refresh_wiki.build_chunks")
    chunks.return_value.documents, chunks.return_value.chunks = 7, 60
    embed = mocker.patch("wiki.management.commands.refresh_wiki.embed_pending", return_value=60)
    out = StringIO()

    call_command("refresh_wiki", stdout=out)

    assert ingest.call_args.kwargs == {"doc_types": None, "direct": False}  # proxies if set
    embed.assert_called_once()
    text = out.getvalue()
    assert "2 new, 5 changed, 2900 unchanged" in text and "embedded 60 new chunks" in text


@pytest.mark.django_db
def test_refresh_stops_cleanly_when_the_wiki_blocks_us(mocker) -> None:
    mocker.patch(
        "wiki.management.commands.refresh_wiki.ingest", side_effect=WikiBlockedError("Anubis")
    )
    chunks = mocker.patch("wiki.management.commands.refresh_wiki.build_chunks")

    with pytest.raises(CommandError, match="Nothing was reindexed"):
        call_command("refresh_wiki")
    chunks.assert_not_called()


@pytest.mark.django_db
def test_refresh_can_skip_the_proxies(mocker) -> None:
    ingest = mocker.patch(
        "wiki.management.commands.refresh_wiki.ingest", return_value=IngestResult(patch="3.29.3c")
    )
    chunks = mocker.patch("wiki.management.commands.refresh_wiki.build_chunks")
    chunks.return_value.documents, chunks.return_value.chunks = 0, 0
    mocker.patch("wiki.management.commands.refresh_wiki.embed_pending", return_value=0)

    call_command("refresh_wiki", "--direct", "--type", "gem", stdout=StringIO())

    assert ingest.call_args.kwargs == {"doc_types": ["gem"], "direct": True}

from dataclasses import dataclass, field

import pytest

from wiki.client import WikiError, WikiPage
from wiki.ingest import content_hash, ingest
from wiki.models import Document, DocumentType, Source

pytestmark = pytest.mark.django_db


@dataclass
class FakeClient:
    """Stand-in for WikiClient; no network."""

    titles: dict[str, list[str]]
    revisions: dict[str, int]
    html: dict[str, str]
    patch: str = "3.29.3c"
    broken: set[str] = field(default_factory=set)
    fetched: list[str] = field(default_factory=list)

    def current_patch(self) -> str:
        return self.patch

    def list_titles(self, doc_type: str) -> list[str]:
        return self.titles.get(doc_type, [])

    def revision_ids(self, titles: list[str]) -> dict[str, int]:
        return {t: self.revisions[t] for t in titles if t in self.revisions}

    def fetch_page(self, title: str, revision_id: int | None = None) -> WikiPage:
        if title in self.broken:
            raise WikiError("boom")
        self.fetched.append(title)
        return WikiPage(title, page_id=1, revision_id=self.revisions[title], html=self.html[title])

    def page_url_for(self, title: str) -> str:
        return f"https://wiki.test/wiki/{title.replace(' ', '_')}"


@pytest.fixture
def fake() -> FakeClient:
    return FakeClient(
        titles={DocumentType.GEM: ["Righteous Fire", "Fire Trap"]},
        revisions={"Righteous Fire": 10, "Fire Trap": 20},
        html={
            "Righteous Fire": "<p>Burns you and enemies.</p>",
            "Fire Trap": "<p>A trap.</p>",
        },
    )


def test_creates_sources_and_documents(fake: FakeClient) -> None:
    result = ingest([DocumentType.GEM], client=fake)

    assert (result.created, result.updated, result.unchanged) == (2, 0, 0)
    doc = Document.objects.get(title="Righteous Fire")
    assert doc.doc_type == DocumentType.GEM
    assert doc.patch == "3.29.3c"
    assert doc.raw_text == "Burns you and enemies."
    assert doc.content_hash == content_hash("Burns you and enemies.")
    assert doc.source.url == "https://wiki.test/wiki/Righteous_Fire"
    assert doc.source.revision_id == 10


def test_skips_unchanged_revisions(fake: FakeClient) -> None:
    ingest([DocumentType.GEM], client=fake)
    fake.fetched.clear()

    result = ingest([DocumentType.GEM], client=fake)

    assert result.unchanged == 2
    assert fake.fetched == []


def test_refetches_edited_pages(fake: FakeClient) -> None:
    ingest([DocumentType.GEM], client=fake)
    fake.revisions["Fire Trap"] = 21
    fake.html["Fire Trap"] = "<p>A better trap.</p>"

    result = ingest([DocumentType.GEM], client=fake)

    assert (result.updated, result.unchanged) == (1, 1)
    assert Document.objects.get(title="Fire Trap").raw_text == "A better trap."
    assert Source.objects.get(page_title="Fire Trap").revision_id == 21


def test_refresh_reparses_everything(fake: FakeClient) -> None:
    ingest([DocumentType.GEM], client=fake)

    result = ingest([DocumentType.GEM], refresh=True, client=fake)

    assert result.updated == 2


def test_new_patch_updates_unchanged_documents(fake: FakeClient) -> None:
    ingest([DocumentType.GEM], client=fake)
    fake.patch = "3.30.0"

    ingest([DocumentType.GEM], client=fake)

    assert set(Document.objects.values_list("patch", flat=True)) == {"3.30.0"}


def test_patch_setting_overrides_wiki(fake: FakeClient, settings) -> None:
    settings.POE_PATCH = "3.25.0"

    assert ingest([DocumentType.GEM], client=fake).patch == "3.25.0"


def test_limit_and_failures(fake: FakeClient) -> None:
    fake.broken.add("Fire Trap")

    result = ingest([DocumentType.GEM], client=fake)
    assert result.failed == ["Fire Trap"]
    assert Document.objects.count() == 1

    Document.objects.all().delete()
    limited = ingest([DocumentType.GEM], limit=1, client=fake)
    assert limited.created + limited.updated + len(limited.failed) == 1

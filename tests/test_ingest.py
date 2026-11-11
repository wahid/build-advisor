from dataclasses import dataclass, field

import pytest

from wiki.client import WikiBlockedError, WikiError, WikiPage
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
    blocked: set[str] = field(default_factory=set)
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
        if title in self.blocked:
            raise WikiBlockedError("cloudflare")
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


def test_logs_how_many_pages_need_downloading(fake: FakeClient, caplog) -> None:
    ingest([DocumentType.GEM], client=fake)
    fake.revisions["Fire Trap"] = 21
    fake.html["Fire Trap"] = "<p>Edited.</p>"
    caplog.clear()

    with caplog.at_level("INFO", logger="wiki.ingest"):
        ingest([DocumentType.GEM], client=fake)

    assert "gem: 2 pages, 1 to download, 1 unchanged" in caplog.text
    assert "gem: 2/2 pages (100%), downloaded 1/1" in caplog.text


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_progress_estimates_remaining_time_from_downloads(caplog) -> None:
    from wiki.ingest import Progress

    clock = FakeClock()
    progress = Progress("gem", total=100, to_fetch=40, every=10, clock=clock)

    with caplog.at_level("INFO", logger="wiki.ingest"):
        for _ in range(50):  # skipped pages: instant, no report
            progress.step()
        assert caplog.text == ""
        for _ in range(10):
            clock.now += 3
            progress.step(fetched=True)

    # 10 downloads took 30s, so 30 more take ~90s.
    assert "gem: 60/100 pages (60%), downloaded 10/40, ~2 min left" in caplog.text


def test_progress_reports_failures_and_long_gaps(caplog) -> None:
    from wiki.ingest import Progress

    clock = FakeClock()
    progress = Progress("unique", total=10, to_fetch=10, every=100, interval=30, clock=clock)

    with caplog.at_level("INFO", logger="wiki.ingest"):
        clock.now = 31
        progress.step(failed=True)

    assert "unique: 1/10 pages (10%), downloaded 1/10, 1 failed" in caplog.text


def test_duration_formatting() -> None:
    from wiki.ingest import _duration

    assert _duration(20) == "<1 min"
    assert _duration(600) == "10 min"
    assert _duration(4000) == "1 h 07 min"


def test_block_stops_the_run_but_keeps_saved_pages(fake: FakeClient) -> None:
    fake.titles[DocumentType.GEM] = ["Fire Trap", "Righteous Fire"]
    fake.blocked.add("Righteous Fire")

    with pytest.raises(WikiBlockedError):
        ingest([DocumentType.GEM, DocumentType.UNIQUE], client=fake)

    assert list(Document.objects.values_list("title", flat=True)) == ["Fire Trap"]


@dataclass
class SlowWorkerClient(FakeClient):
    """FakeClient whose workers record which thread fetched each page."""

    threads: set[str] = field(default_factory=set)

    def for_worker(self, index: int, total: int = 1) -> "SlowWorkerClient":
        return self

    def fetch_page(self, title: str, revision_id: int | None = None) -> WikiPage:
        import threading
        import time

        self.threads.add(threading.current_thread().name)
        time.sleep(0.05)
        return super().fetch_page(title, revision_id)


def test_downloads_in_parallel_with_workers() -> None:
    titles = [f"Gem {i}" for i in range(8)]
    fake = SlowWorkerClient(
        titles={DocumentType.GEM: titles},
        revisions={t: i for i, t in enumerate(titles, 1)},
        html={t: f"<p>{t}</p>" for t in titles},
    )

    result = ingest([DocumentType.GEM], client=fake, workers=4)

    assert result.created == 8
    assert Document.objects.count() == 8
    assert len(fake.threads) > 1


def test_parallel_failures_are_recorded_and_others_stored() -> None:
    titles = ["A", "B", "C", "D"]
    fake = SlowWorkerClient(
        titles={DocumentType.GEM: titles},
        revisions={t: 1 for t in titles},
        html={t: "<p>x</p>" for t in titles},
        broken={"B"},
    )

    result = ingest([DocumentType.GEM], client=fake, workers=3)

    assert result.failed == ["B"]
    assert sorted(Document.objects.values_list("title", flat=True)) == ["A", "C", "D"]

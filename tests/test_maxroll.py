from datetime import date

import pytest
import responses
from django.core.management import CommandError, call_command

from wiki import maxroll
from wiki.indexing import build_chunks
from wiki.maxroll import (
    GuidePage,
    MaxrollClient,
    MaxrollError,
    fetch_guides,
    long_quotes,
    longest_shared_run,
    normalise_url,
    parse_guide,
    purge,
    store_guide,
)
from wiki.models import Chunk, Document, DocumentType, MaxrollRequest, Source

pytestmark = pytest.mark.django_db

URL = "https://maxroll.gg/poe/build-guides/poison-ranged-animate-weapons-league-starter"

GUIDE_HTML = """<!doctype html><html><head>
<title>Poison Ranged Animate Weapons League Starter for Path of Exile 3.30 Covens of Umbra
 | Maxroll.gg</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Article",
 "headline":"Poison Ranged Animate Weapons","author":{"@type":"Person","name":"Helm Breaker"},
 "dateModified":"2026-11-13T09:00:00Z"}</script>
</head><body><nav>Home Build Guides Tier List</nav>
<article>
  <header>
    <h1>Poison Ranged Animate Weapons League Starter for Path of Exile 3.30 Covens of Umbra</h1>
    <div>Updated November 13, 2026</div>
    <div class="author">Written by <a>Helm Breaker</a> Content Creator
      <p>Hi, I'm Helm Breaker, the "Minion guy" on Maxroll.</p></div>
  </header>
  <section>
    <h2>Introduction</h2>
    <p>Animate Weapon of Ranged Arms raises bows that shoot poison arrows for you.</p>
    <img src="banner.png" alt="Banner">
    <figure><img src="tree.png"><figcaption>Passive tree</figcaption></figure>
    <div class="poe-planner-embed">Embedded planner: Level 1-90 tree</div>
    <iframe src="https://www.youtube.com/embed/abc"></iframe>
  </section>
  <section>
    <h2>Gems</h2>
    <ul><li>Animate Weapon of Ranged Arms</li><li>Unleash Support</li></ul>
  </section>
  <div id="comments"><p>Great guide! — a reader</p></div>
</article>
<footer>Ziff Davis</footer></body></html>"""


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _client(clock: FakeClock | None = None, interval: float = 1.0) -> MaxrollClient:
    clock = clock or FakeClock()
    return MaxrollClient("tests", request_interval=interval, clock=clock, sleep=clock.sleep)

# --- URLs -------------------------------------------------------------------------


def test_urls_are_normalised() -> None:
    assert normalise_url("http://www.maxroll.gg/poe/build-guides/x/?ref=1#gems") == (
        "https://maxroll.gg/poe/build-guides/x"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/poe/x",
        "https://maxroll.gg/d4/build-guides/x",
        "https://maxroll.gg/poe/",
    ],
)
def test_other_urls_are_refused(url: str) -> None:
    with pytest.raises(ValueError):
        normalise_url(url)


# --- rate and monthly limits ------------------------------------------------------


@responses.activate
def test_at_most_one_request_per_second() -> None:
    responses.get(URL, body=GUIDE_HTML)
    clock = FakeClock()
    client = _client(clock, interval=0.1)  # below the licence's minimum
    client.fetch(URL)
    client.fetch(URL)
    assert client.request_interval == 1.0
    assert clock.slept == [1.0]
    assert MaxrollRequest.objects.filter(status=200).count() == 2

@responses.activate
def test_redirects_count_as_requests_and_stay_on_maxroll() -> None:
    responses.get(URL, status=301, headers={"Location": "/poe/build-guides/renamed"})
    responses.get("https://maxroll.gg/poe/build-guides/renamed", body=GUIDE_HTML)
    clock = FakeClock()
    assert "Animate Weapon" in _client(clock).fetch(URL)
    assert MaxrollRequest.objects.count() == 2
    assert clock.slept == [1.0]


@responses.activate
def test_redirect_off_maxroll_is_refused() -> None:
    responses.get(URL, status=302, headers={"Location": "https://elsewhere.test/page"})
    with pytest.raises(ValueError):
        _client().fetch(URL)


@responses.activate
@pytest.mark.parametrize("status", [403, 429, 503])
def test_blocks_and_rate_limits_stop_without_retrying(status: int) -> None:
    responses.get(URL, status=status)
    with pytest.raises(MaxrollError, match="don't retry"):
        _client().fetch(URL)
    assert len(responses.calls) == 1


# --- parsing ----------------------------------------------------------------------


def test_parse_keeps_title_byline_date_and_patch() -> None:
    page = parse_guide(URL, GUIDE_HTML)
    assert page.title.startswith("Poison Ranged Animate Weapons League Starter")
    assert not page.title.endswith("Maxroll.gg")
    assert page.author == "Helm Breaker"
    assert page.updated_on == date(2026, 11, 13)
    assert page.patch == "3.30"


def test_parse_keeps_only_the_article_text() -> None:
    text = parse_guide(URL, GUIDE_HTML).text
    assert "## Introduction" in text
    assert "shoot poison arrows" in text
    assert "Unleash Support" in text
    for excluded in ("Banner", "Passive tree", "Embedded planner", "youtube", "Great guide"):
        assert excluded not in text  # images, embedded tools, video, comments
    assert "Minion guy" not in text  # author bio
    assert "Ziff Davis" not in text and "Tier List" not in text  # site chrome


def test_parse_reads_the_visible_byline_without_metadata() -> None:
    html = """<html><body><article><div>Updated November 2, 2026</div>
    <div>Written by</div><div>Some Author</div><h2>Gear</h2><p>Bows with poison chance.</p>
    </article></body></html>"""
    page = parse_guide(URL, html)
    assert page.author == "Some Author"
    assert page.updated_on == date(2026, 11, 2)
    assert "Bows with poison chance." in page.text


def test_intro_before_the_first_heading_is_kept_without_a_byline() -> None:
    html = "<article><p>An intro paragraph before any heading.</p><h2>Gems</h2><p>x</p></article>"
    assert "An intro paragraph" in parse_guide(URL, html).text


# --- storing, indexing, purging ---------------------------------------------------


def _page(
    text: str = "## Gems\n\nAnimate Weapon of Ranged Arms with Unleash Support.",
) -> GuidePage:
    return GuidePage(URL, "Poison Ranged AW", "Helm Breaker", date(2026, 11, 13), "3.30", text)


def test_store_guide_keeps_attribution_and_skips_unchanged_text() -> None:
    assert store_guide(_page()) == "created"
    assert store_guide(_page()) == "unchanged"
    assert store_guide(_page("## Gems\n\nNew gem setup for the league.")) == "updated"
    source = Source.objects.get(wiki="maxroll")
    assert (source.url, source.author, source.updated_on) == (
        URL,
        "Helm Breaker",
        date(2026, 11, 13),
    )
    document = Document.objects.get(source=source)
    assert (document.doc_type, document.patch) == (DocumentType.GUIDE, "3.30")


@responses.activate
def test_fetch_guides_stores_pages_and_reports_failures() -> None:
    responses.get(URL, body=GUIDE_HTML)
    broken = "https://maxroll.gg/poe/build-guides/gone"
    responses.get(broken, status=404)
    result = fetch_guides([URL, broken], client=_client())
    assert (result.created, result.failed) == (1, [broken])


def test_guides_are_chunked_and_purged_with_their_chunks() -> None:
    store_guide(_page())
    build_chunks()
    assert Chunk.objects.filter(doc_type=DocumentType.GUIDE, url=URL).exists()
    assert purge() > 0
    assert not Source.objects.filter(wiki="maxroll").exists()
    assert not Chunk.objects.filter(doc_type=DocumentType.GUIDE).exists()


def test_purge_command_needs_confirmation(monkeypatch) -> None:
    store_guide(_page())
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    call_command("purge_maxroll")
    assert Source.objects.filter(wiki="maxroll").exists()
    call_command("purge_maxroll", "--yes")
    assert not Source.objects.filter(wiki="maxroll").exists()


def test_wiki_ingest_does_not_ask_the_wiki_for_guides() -> None:
    from wiki.models import WIKI_DOC_TYPES

    assert DocumentType.GUIDE not in WIKI_DOC_TYPES


# --- quote limit ------------------------------------------------------------------


def test_longest_shared_run_counts_words_case_insensitively() -> None:
    assert (
        longest_shared_run("Use Unleash support, then CURSE", "use unleash Support then curse x")
        == 5
    )
    assert longest_shared_run("", "anything") == 0


def test_long_quotes_flags_only_quotes_over_the_limit() -> None:
    source = " ".join(f"word{i}" for i in range(150))
    short = " ".join(f"word{i}" for i in range(100))
    long = " ".join(f"word{i}" for i in range(101))
    assert long_quotes(short, {1: source}) == {}
    assert long_quotes(long, {1: source}) == {1: 101}


def test_prompt_and_answer_sources_credit_the_guide() -> None:
    from advisor.prompts import format_sources
    from advisor.rag import Source as AnswerSource
    from wiki.search import SearchHit

    store_guide(_page())
    build_chunks()
    chunk = Chunk.objects.select_related("document__source").filter(doc_type="guide").first()
    hit = SearchHit(chunk, 1.0)
    assert "(Maxroll guide by Helm Breaker, updated 2026-11-13, patch 3.30)" in format_sources(
        [hit]
    )
    source = AnswerSource.from_hit(1, hit)
    assert (source.url, source.author, source.updated) == (URL, "Helm Breaker", "2026-11-13")

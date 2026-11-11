from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from wiki import client as client_module
from wiki.client import WikiClient, WikiError
from wiki.models import DocumentType

from .conftest import API_URL


def _params(call: responses.Call) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(call.request.url).query).items()}


@responses.activate
def test_list_titles_pages_through_cargo(wiki_client: WikiClient, monkeypatch) -> None:
    monkeypatch.setattr(client_module, "CARGO_PAGE_SIZE", 2)
    pages = [["B gem", "A gem"], ["Abberath&#039;s Horn"]]
    for batch in pages:
        responses.get(API_URL, json={"cargoquery": [{"title": {"page": p}} for p in batch]})

    titles = wiki_client.list_titles(DocumentType.GEM)

    assert titles == ["A gem", "Abberath's Horn", "B gem"]
    assert _params(responses.calls[1])["offset"] == "2"
    assert _params(responses.calls[0])["action"] == "cargoquery"
    assert _params(responses.calls[0])["maxlag"] == "5"


@responses.activate
def test_list_titles_follows_category_continuation(wiki_client: WikiClient) -> None:
    responses.get(
        API_URL,
        json={
            "continue": {"cmcontinue": "page|x", "continue": "-||"},
            "query": {"categorymembers": [{"title": "Chieftain"}]},
        },
    )
    responses.get(API_URL, json={"query": {"categorymembers": [{"title": "Ascendant"}]}})

    assert wiki_client.list_titles(DocumentType.ASCENDANCY) == ["Ascendant", "Chieftain"]
    assert _params(responses.calls[1])["cmcontinue"] == "page|x"


@responses.activate
def test_revision_ids_maps_normalised_titles_back(wiki_client: WikiClient) -> None:
    responses.get(
        API_URL,
        json={
            "query": {
                "normalized": [{"from": "righteous_Fire", "to": "Righteous fire"}],
                "redirects": [{"from": "Righteous fire", "to": "Righteous Fire"}],
                "pages": [
                    {"title": "Righteous Fire", "revisions": [{"revid": 42}]},
                    {"title": "Gone", "missing": True},
                ],
            }
        },
    )

    assert wiki_client.revision_ids(["righteous_Fire", "Gone"]) == {"righteous_Fire": 42}


@responses.activate
def test_fetch_page_uses_cache_for_known_revision(wiki_client: WikiClient) -> None:
    responses.get(API_URL, json={"parse": {"pageid": 1, "revid": 7, "text": "<p>Hello</p>"}})

    first = wiki_client.fetch_page("Some Page")
    second = wiki_client.fetch_page("Some Page", revision_id=7)

    assert first == second
    assert len(responses.calls) == 1


@responses.activate
def test_retries_after_rate_limit(wiki_client: WikiClient) -> None:
    waits: list[float] = []
    wiki_client._sleep = waits.append
    responses.get(API_URL, status=429, headers={"Retry-After": "30"})
    responses.get(API_URL, json={"cargoquery": [{"title": {"version": "3.29.3c"}}]})

    assert wiki_client.current_patch(today=date(2026, 11, 11)) == "3.29.3c"
    assert 30.0 in waits  # a longer Retry-After than our backoff is respected


@responses.activate
def test_rate_limit_slows_down_later_requests(wiki_client: WikiClient) -> None:
    waits: list[float] = []
    wiki_client._sleep = waits.append
    wiki_client.base_interval = wiki_client.request_interval = 1.0
    responses.get(API_URL, status=429)
    responses.get(API_URL, status=429)
    responses.get(API_URL, json={"cargoquery": [{"title": {"version": "3.29.3c"}}]})

    wiki_client.current_patch(today=date(2026, 11, 11))

    assert [w for w in waits if w >= 5] == [5.0, 10.0]  # backoff doubles per retry
    assert wiki_client.request_interval == pytest.approx(4.0 * 0.95)


def test_interval_recovers_but_not_below_base(wiki_client: WikiClient) -> None:
    wiki_client.base_interval = wiki_client.request_interval = 1.0
    wiki_client._slow_down()
    assert wiki_client.request_interval == 2.0

    for _ in range(100):
        wiki_client._speed_up()

    assert wiki_client.request_interval == 1.0


def test_interval_is_capped(wiki_client: WikiClient) -> None:
    wiki_client.max_interval = 30.0
    for _ in range(20):
        wiki_client._slow_down()

    assert wiki_client.request_interval == 30.0


@responses.activate
def test_gives_up_after_max_retries(wiki_client: WikiClient) -> None:
    wiki_client.max_retries = 3
    for _ in range(3):
        responses.get(API_URL, status=429)

    with pytest.raises(WikiError, match="Gave up"):
        wiki_client.current_patch(today=date(2026, 11, 11))
    assert len(responses.calls) == 3


@responses.activate
def test_current_patch_ignores_unreleased_versions(wiki_client: WikiClient) -> None:
    responses.get(API_URL, json={"cargoquery": [{"title": {"version": "3.29.3c"}}]})

    wiki_client.current_patch(today=date(2026, 11, 11))

    params = _params(responses.calls[0])
    assert params["where"] == 'release_date <= "2026-11-11"'
    assert params["order_by"] == "release_date DESC"


@responses.activate
def test_api_errors_raise(wiki_client: WikiClient) -> None:
    responses.get(API_URL, json={"error": {"code": "missingtitle", "info": "nope"}})

    with pytest.raises(WikiError, match="missingtitle"):
        wiki_client.fetch_page("Nope")


def test_page_url_for(wiki_client: WikiClient) -> None:
    assert wiki_client.page_url_for("Abberath's Horn") == "https://wiki.test/wiki/Abberath's_Horn"

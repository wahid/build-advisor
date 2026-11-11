import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from wiki import client as client_module
from wiki.client import ProxyPool, WikiBlockedError, WikiClient, WikiError
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
        responses.get(API_URL, json={"error": {"code": "maxlag", "info": "lagged"}})

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


# --- proxies ----------------------------------------------------------------


def _proxy_client(tmp_path, proxies, **kwargs) -> WikiClient:
    return WikiClient(
        api_url=API_URL,
        page_url="https://wiki.test/wiki/",
        user_agent="tests",
        cache_dir=tmp_path / "cache",
        request_interval=0,
        proxies=proxies,
        sleep=lambda _seconds: None,
        **kwargs,
    )


class _RecordingSession(requests.Session):
    """Fails for the proxies in `broken`, otherwise returns `payload`."""

    def __init__(self, broken: set[str], payload: dict, status: int = 200) -> None:
        super().__init__()
        self.broken = broken
        self.payload = payload
        self.status = status
        self.used: list[str | None] = []

    def get(self, url, params=None, proxies=None, **kwargs):  # type: ignore[override]
        proxy = proxies["https"] if proxies else None
        self.used.append(proxy)
        response = requests.Response()
        if proxy in self.broken:
            if self.status != 200:
                response.status_code = self.status
                return response
            raise requests.ConnectionError("proxy down")
        response.status_code = 200
        response._content = json.dumps(self.payload).encode()
        return response


PATCH_PAYLOAD = {"cargoquery": [{"title": {"version": "3.29.3c"}}]}


def test_failed_proxy_retries_on_next_one(tmp_path) -> None:
    client = _proxy_client(tmp_path, ["http://p1:8080", "http://p2:8080"])
    client.session = _RecordingSession({"http://p1:8080"}, PATCH_PAYLOAD)

    assert client.current_patch(today=date(2026, 11, 11)) == "3.29.3c"
    assert client.session.used == ["http://p1:8080", "http://p2:8080"]

    # The failed proxy is on cooldown, so the next request goes straight to p2.
    client.current_patch(today=date(2026, 11, 11))
    assert client.session.used[-1] == "http://p2:8080"


def test_proxy_auth_error_switches_proxy(tmp_path) -> None:
    client = _proxy_client(tmp_path, ["http://p1:8080", "http://p2:8080"])
    client.session = _RecordingSession({"http://p1:8080"}, PATCH_PAYLOAD, status=407)

    assert client.current_patch(today=date(2026, 11, 11)) == "3.29.3c"
    assert client.session.used == ["http://p1:8080", "http://p2:8080"]


def test_rate_limited_proxy_switches_proxy(tmp_path) -> None:
    client = _proxy_client(tmp_path, ["http://p1:8080", "http://p2:8080"])
    client.session = _RecordingSession({"http://p1:8080"}, PATCH_PAYLOAD, status=429)

    assert client.current_patch(today=date(2026, 11, 11)) == "3.29.3c"
    assert client.session.used == ["http://p1:8080", "http://p2:8080"]


def test_unavailable_through_proxy_switches_proxy(tmp_path) -> None:
    client = _proxy_client(tmp_path, ["http://p1:8080", "http://p2:8080"])
    client.session = _RecordingSession({"http://p1:8080"}, PATCH_PAYLOAD, status=503)

    assert client.current_patch(today=date(2026, 11, 11)) == "3.29.3c"
    assert client.session.used == ["http://p1:8080", "http://p2:8080"]


@responses.activate
def test_direct_retries_after_rate_limit(wiki_client: WikiClient) -> None:
    waits: list[float] = []
    wiki_client._sleep = waits.append
    responses.get(API_URL, status=429, headers={"Retry-After": "30"})
    responses.get(API_URL, json={"cargoquery": [{"title": {"version": "3.29.3c"}}]})

    assert wiki_client.current_patch(today=date(2026, 11, 11)) == "3.29.3c"
    assert 30.0 in waits  # a longer Retry-After than our backoff is respected


@responses.activate
def test_direct_rate_limit_slows_down_later_requests(wiki_client: WikiClient) -> None:
    waits: list[float] = []
    wiki_client._sleep = waits.append
    wiki_client.base_interval = wiki_client.request_interval = 1.0
    responses.get(API_URL, status=503)
    responses.get(API_URL, status=429)
    responses.get(API_URL, json={"cargoquery": [{"title": {"version": "3.29.3c"}}]})

    wiki_client.current_patch(today=date(2026, 11, 11))

    assert [w for w in waits if w >= 5] == [5.0, 10.0]  # backoff doubles per retry
    assert wiki_client.request_interval == pytest.approx(4.0 * 0.95)


@responses.activate
def test_direct_cloudflare_challenge_stops_immediately(wiki_client: WikiClient) -> None:
    responses.get(API_URL, status=429, headers={"cf-mitigated": "challenge"}, body="<html>")

    with pytest.raises(WikiBlockedError):
        wiki_client.current_patch(today=date(2026, 11, 11))
    assert len(responses.calls) == 1


def test_from_settings_direct_ignores_proxies(settings) -> None:
    settings.WIKI_PROXIES = ["http://p1:8080"]

    assert len(WikiClient.from_settings().proxy_pool) == 1
    assert len(WikiClient.from_settings(direct=True).proxy_pool) == 0


def test_all_proxies_failing_gives_up(tmp_path) -> None:
    proxies = ["http://p1:8080", "http://p2:8080"]
    client = _proxy_client(tmp_path, proxies, max_retries=2)
    client.session = _RecordingSession(set(proxies), PATCH_PAYLOAD)

    with pytest.raises(WikiError, match="Request failed"):
        client.current_patch(today=date(2026, 11, 11))
    # One free switch per proxy, then the normal retries.
    assert len(client.session.used) == 4


def test_workers_get_their_own_home_proxy(tmp_path) -> None:
    pool = ProxyPool(["http://p1:8080", "http://p2:8080", "http://p3:8080"])
    base = _proxy_client(tmp_path, pool)
    workers = [base.for_worker(i, 3) for i in range(3)]

    assert [w.proxy_pool.pick(w.proxy_index) for w in workers] == [
        "http://p1:8080",
        "http://p2:8080",
        "http://p3:8080",
    ]
    assert all(w.proxy_pool is pool for w in workers)
    assert len({id(w.session) for w in workers}) == 3

    pool.mark_failed("http://p2:8080")
    assert workers[1].proxy_pool.pick(1) == "http://p3:8080"


def test_home_proxies_are_spread_over_a_long_list(tmp_path) -> None:
    proxies = [f"http://p{i}:8080" for i in range(100)]
    base = _proxy_client(tmp_path, proxies)

    assert [base.for_worker(i, 4).proxy_index for i in range(4)] == [0, 25, 50, 75]


def test_worker_keeps_its_replacement_proxy(tmp_path) -> None:
    client = _proxy_client(tmp_path, ["http://p1:8080", "http://p2:8080", "http://p3:8080"])
    client.session = _RecordingSession({"http://p1:8080"}, PATCH_PAYLOAD)

    client.current_patch(today=date(2026, 11, 11))

    assert client.proxy_index == 1


def test_pool_falls_back_to_soonest_recovering_proxy() -> None:
    now = [0.0]
    pool = ProxyPool(["a", "b"], cooldown=10, clock=lambda: now[0])
    pool.mark_failed("a")
    now[0] = 1.0
    pool.mark_failed("b")

    assert pool.pick(1) == "a"
    now[0] = 10.5
    assert pool.pick(1) == "a"  # b is still cooling down


def test_socks_proxies_are_skipped_without_pysocks(caplog) -> None:
    pool = ProxyPool(["socks5://a:1", "http://b:2"], socks_supported=lambda: False)

    assert pool.proxies == ["http://b:2"]
    assert "Skipping 1 SOCKS proxies" in caplog.text


def test_redact_hides_credentials() -> None:
    assert client_module._redact("http://user:secret@host:8080") == "http://host:8080"
    assert client_module._redact("http://host:8080") == "http://host:8080"


def test_read_proxy_file(tmp_path) -> None:
    from config.settings import read_proxy_file

    path = tmp_path / "proxies.txt"
    path.write_text("# comment\nhttp://a:1\n\n  http://b:2  # second\n", encoding="utf-8")

    assert read_proxy_file(path) == ["http://a:1", "http://b:2"]
    assert read_proxy_file(tmp_path / "missing.txt") == []


@responses.activate
def test_mechanics_follow_subcategories_once(wiki_client: WikiClient) -> None:
    def members(*items):
        return {"query": {"categorymembers": [{"title": t, "ns": ns} for t, ns in items]}}

    responses.get(
        API_URL,
        json=members(("Leech", 0), ("Category:Ailments", 14), ("Category:Charges", 14)),
    )
    responses.get(API_URL, json=members(("Ignite", 0), ("Category:Game mechanics", 14)))
    responses.get(API_URL, json=members(("Endurance charge", 0), ("Leech", 0)))

    titles = wiki_client.list_titles(DocumentType.MECHANIC)

    assert titles == ["Endurance charge", "Ignite", "Leech"]
    assert _params(responses.calls[0])["cmnamespace"] == "0|14"
    assert _params(responses.calls[1])["cmtitle"] == "Category:Ailments"
    assert _params(responses.calls[1])["cmnamespace"] == "0"  # depth used up: articles only
    assert len(responses.calls) == 3  # the cycle back to Game mechanics isn't followed


@responses.activate
def test_anubis_block_page_stops_the_run(wiki_client: WikiClient) -> None:
    html = "<html><title>Oh noes!</title>Protected by Anubis. Access Denied</html>"
    responses.get(API_URL, status=403, body=html, content_type="text/html")

    with pytest.raises(WikiBlockedError, match="Anubis"):
        wiki_client.current_patch(today=date(2026, 11, 11))
    assert len(responses.calls) == 1


@responses.activate
def test_non_json_response_is_a_clear_error(wiki_client: WikiClient) -> None:
    responses.get(API_URL, status=200, body="<html>maintenance</html>", content_type="text/html")

    with pytest.raises(WikiError, match="web page instead of API data"):
        wiki_client.current_patch(today=date(2026, 11, 11))

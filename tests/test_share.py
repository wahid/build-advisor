"""Sharing a chat as a read-only public page."""

import pytest

from advisor.models import QuestionLog, SharedChat

pytestmark = pytest.mark.django_db

SOURCE = {
    "number": 1,
    "title": "Poison",
    "section": "",
    "url": "https://w/Poison",
    "doc_type": "mechanic",
}


def _log(question: str, answer: str, completed: bool = True) -> str:
    log = QuestionLog.objects.create(
        question=question, answer=answer, completed=completed, sources=[SOURCE], cited=[1]
    )
    return str(log.id)


def _share(client, ids):
    return client.post("/api/share/", {"log_ids": ids}, content_type="application/json")


def test_a_chat_is_shared_from_the_log_in_the_given_order(client) -> None:
    second = _log("And bleed?", "Only the strongest counts.")
    first = _log("How does poison stack?", "Without limit [1].")
    stopped = _log("stopped", "", completed=False)

    response = _share(client, [first, second, stopped])

    assert response.status_code == 201
    body = response.json()
    assert body["url"].endswith(f"/c/{body['slug']}/") and body["delete_key"]
    shared = client.get(f"/api/share/{body['slug']}/").json()
    assert shared["title"] == "How does poison stack?"
    assert [t["question"] for t in shared["turns"]] == ["How does poison stack?", "And bleed?"]
    assert shared["turns"][0]["sources"][0]["patch"] == ""  # older logs have no patch
    assert "delete_key" not in shared


def test_only_logged_answers_can_be_shared(client) -> None:
    unknown = "00000000-0000-4000-8000-000000000000"

    assert _share(client, [unknown]).status_code == 400
    assert _share(client, []).status_code == 400
    assert _share(client, ["<script>"]).status_code == 400
    assert not SharedChat.objects.exists()


def test_the_sharer_can_take_the_page_down(client) -> None:
    body = _share(client, [_log("q", "a")]).json()
    url = f"/api/share/{body['slug']}/"

    wrong = client.delete(url, {"delete_key": "nope"}, content_type="application/json")
    assert wrong.status_code == 403 and SharedChat.objects.count() == 1
    right = client.delete(url, {"delete_key": body["delete_key"]}, content_type="application/json")
    assert right.status_code == 204
    assert client.get(url).status_code == 404


def test_the_page_has_the_chats_title_in_its_link_preview(client, settings, tmp_path) -> None:
    (tmp_path / "index.html").write_text(
        '<title>Build Advisor</title><meta property="og:title" content="Build Advisor: x" />'
        '<meta property="og:url" content="__PAGE_URL__" />'
    )
    settings.FRONTEND_DIST = tmp_path
    slug = _share(client, [_log('Is "Cyclone" <b>good</b>?', "Yes.")]).json()["slug"]

    html = client.get(f"/c/{slug}/").content.decode()

    assert "<title>Is &quot;Cyclone&quot; &lt;b&gt;good&lt;/b&gt;? | Build Advisor</title>" in html
    assert 'og:title" content="Is &quot;Cyclone&quot;' in html
    assert f"/c/{slug}/" in html
    assert "Build Advisor: x" in client.get("/c/unknown/").content.decode()

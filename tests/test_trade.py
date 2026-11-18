"""Trade links: pob-mcp's trade_search as a link the app shows (advisor.trade)."""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from advisor import trade
from advisor.llm import ToolCall
from advisor.pob import (
    DEFAULT_TOOLS,
    NO_BUILD_ERROR,
    ToolResult,
    openai_tool_definitions,
    sanitize_arguments,
)
from advisor.rag import _ToolRunner

ROOT = "https://www.pathofexile.com/trade/search/"
# pob-mcp's compressed link: the trade site answers it with "search is no longer valid".
COMPRESSED = ROOT + "Covens%20of%20Umbra/H4sIAAAAAAAAC_compressed"


def trade_result(slot: str = "Ring 1") -> dict:
    """What pob-mcp's trade_search returns (shortened)."""
    query = {
        "query": {
            "status": {"option": "online"},
            "stats": [{"type": "weight", "filters": [], "value": {"min": 120.5}}],
            "filters": {"type_filters": {"filters": {"rarity": {"option": "nonunique"}}}},
        },
        "sort": {"statgroup.0": "desc"},
    }
    return {
        "league": "Covens of Umbra",
        "slot": slot,
        "category": "accessory.ring",
        "currentItem": "Doom Loop, Coral Ring",
        "minimumWeightedSum": 120.5,
        "statWeights": [
            {"text": "+(13-16) to all Attributes", "weight": 38.2, "scoreAtExample": 15.8},
            {"text": "+(351-480) to Accuracy Rating", "weight": 10, "scoreAtExample": 123.7},
            *({"text": f"mod {n}", "scoreAtExample": n} for n in range(8)),
        ],
        "url": COMPRESSED,
        "url_plain": ROOT + "Covens%20of%20Umbra?q=plain",
        "query": query,
    }


def _decode(url: str) -> dict:
    """The query in a link, which must be the site's ?q= form for that league."""
    parts = urlsplit(url)
    assert url.startswith(ROOT) and parts.path == "/trade/search/Covens%20of%20Umbra"
    return json.loads(parse_qs(parts.query)["q"][0])


def test_a_search_keeps_the_link_and_names_the_heaviest_mods() -> None:
    result = trade_result()
    found = trade.search(result)

    assert _decode(found["url"]) == result["query"]  # not pob-mcp's compressed link
    assert (found["slot"], found["league"], found["item"]) == (
        "Ring 1",
        "Covens of Umbra",
        "Doom Loop, Coral Ring",
    )
    assert found["better_than_current"] is True
    assert (found["max_price"], found["currency"]) == (None, None)
    assert found["stats"][:2] == ["+(351-480) to Accuracy Rating", "+(13-16) to all Attributes"]
    assert len(found["stats"]) == trade.MAX_STATS


def test_a_price_cap_is_added_to_the_search() -> None:
    result = trade_result()
    found = trade.search(result, 50, "divine")

    query = _decode(found["url"])
    assert query["query"]["filters"]["trade_filters"] == {
        "filters": {"price": {"max": 50, "option": "divine"}}
    }
    assert query["query"]["stats"] == result["query"]["query"]["stats"]  # rest unchanged
    assert "trade_filters" not in result["query"]["query"]["filters"]  # not edited in place
    assert (found["max_price"], found["currency"]) == (50, "divine")


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"url": "https://evil.example/trade/search/x", "league": "Covens"},
        {"url": COMPRESSED, "league": "Covens", "query": {"sort": {}}},
        {"url": COMPRESSED, "query": {"query": {}}},
    ],
)
def test_a_result_without_a_query_and_league_gives_no_link(data) -> None:
    with pytest.raises(trade.TradeError):
        trade.search(data)


def test_the_model_gets_the_mods_but_no_link() -> None:
    text = trade.for_model(trade.search(trade_result()))

    assert "Accuracy Rating" in text and "Ring 1" in text
    assert "pathofexile.com" not in text and "don't write a URL" in text


@pytest.mark.parametrize(
    ("arguments", "cap"),
    [
        ({"max_price": 5, "currency": "divine"}, (5.0, "divine")),
        ({"max_price": "20"}, (20.0, "chaos")),
        ({"max_price": 0}, (None, "chaos")),
        ({"max_price": "lots", "currency": "exalted"}, (None, "chaos")),
        ({}, (None, "chaos")),
    ],
)
def test_price_cap_arguments(arguments: dict, cap: tuple) -> None:
    assert trade.price_cap(arguments) == cap


def test_the_model_can_set_the_slot_and_price_but_not_the_league() -> None:
    assert "trade_search" in DEFAULT_TOOLS
    tool = SimpleNamespace(
        name="trade_search",
        description="Build a trade search",
        input_schema={
            "properties": {
                "slot": {"type": "string"},
                "weights": {"type": "object"},
                "league": {"type": "string"},
                "max_stats": {"type": "integer"},
                "online_only": {"type": "boolean"},
            },
            "required": ["slot"],
        },
    )
    [definition] = openai_tool_definitions([tool], {"trade_search"})
    assert set(definition["function"]["parameters"]["properties"]) == {
        "slot",
        "weights",
        "max_price",
        "currency",
    }
    sent = sanitize_arguments(
        "trade_search", {"slot": "Ring 1", "league": "Standard", "max_price": 5, "max_stats": 99}
    )
    assert sent == {"slot": "Ring 1"}


class Toolbox:
    def __init__(self, result: ToolResult | None = None, has_build: bool = True) -> None:
        self.has_build = has_build
        self.result = result or ToolResult(ok=True, text="", data=trade_result())
        self.calls: list[tuple[str, dict]] = []

    def call(self, name: str, arguments: dict) -> ToolResult:
        self.calls.append((name, arguments))
        return self.result


def test_the_tool_sends_the_link_to_the_user_and_the_mods_to_the_model() -> None:
    toolbox = Toolbox()
    call = ToolCall(
        "t1", "trade_search", '{"slot": "Ring 1", "max_price": 2, "currency": "divine"}'
    )

    events, text = _ToolRunner(toolbox).run(call)

    assert [e["type"] for e in events] == ["tool_call", "tool_result", "trade_search"]
    link = events[-1]
    assert (link["slot"], link["max_price"], link["currency"]) == ("Ring 1", 2, "divine")
    price = _decode(link["url"])["query"]["filters"]["trade_filters"]["filters"]["price"]
    assert price == {"max": 2, "option": "divine"}
    assert "pathofexile.com" not in text and "Accuracy Rating" in text
    assert "pathofexile.com" not in events[1]["preview"]
    assert toolbox.calls[0][0] == "trade_search"


def test_a_failed_search_goes_back_to_the_model_as_an_error() -> None:
    failed = ToolResult(ok=False, text="No mod on this base improves the chosen stats", data=None)

    events, text = _ToolRunner(Toolbox(failed)).run(ToolCall("t1", "trade_search", '{"slot": "x"}'))

    assert events[-1]["ok"] is False and "No mod on this base" in text
    assert NO_BUILD_ERROR not in text


def test_rare_searches_skip_slots_that_cant_be_searched() -> None:
    def call(name: str, arguments: dict) -> ToolResult:
        if name == "rank_gear_upgrades":
            assert arguments == {"per_slot": 1, "slots": ["Ring 1", "Belt"]}
            ranked = [
                {"slot": "Belt", "add": "life", "score": 1},
                {"slot": "Ring 1", "add": "res", "score": 5},
                {"slot": "Ring 1", "add": "dex", "score": 3},
            ]
            return ToolResult(ok=True, text="", data={"upgrades": ranked})
        if arguments["slot"] == "Belt":
            return ToolResult(ok=False, text="No mod on this base", data=None)
        return ToolResult(ok=True, text="", data=trade_result(arguments["slot"]))

    found = trade.rare_searches(call, 30, "chaos", ["Ring 1", "Belt"])

    assert [(f["slot"], f["best_mod"], f["max_price"]) for f in found] == [("Ring 1", "res", 30)]

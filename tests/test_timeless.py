"""find_timeless_jewel (pob-mcp 0.5.3): arguments, trade links, and the chat tool."""

import base64
import gzip
import json
from urllib.parse import parse_qs, urlparse

import pytest

from advisor import timeless
from advisor.llm import ToolCall
from advisor.pob import PobToolError, ToolResult
from advisor.rag import _ToolRunner

QUERY = {
    "query": {
        "status": {"option": "online"},
        "stats": [
            {
                "type": "count",
                "value": {"min": 1},
                "filters": [{"id": "explicit.x", "value": {"min": 12345, "max": 12345}}],
            }
        ],
    },
    "sort": {"price": "asc"},
}


def compressed(query: dict, league: str = "Mirage") -> str:
    """The link pob-mcp's trade_url makes (gzip + base64, URL-safe)."""
    code = base64.b64encode(gzip.compress(json.dumps(query).encode())).decode()
    code = code.replace("+", "-").replace("/", "_")
    return f"https://www.pathofexile.com/trade/search/{league}/{code}"


def raw_result(**overrides) -> dict:
    seed = {
        "seed": 12345,
        "socket": 61419,
        "socketNear": "Ironwood",
        "socketAllocated": True,
        "socketPathCost": 0,
        "notables": [
            {
                "node": "Juggernaut",
                "becomes": "Chainbreaker",
                "allocated": True,
                "pointsToReach": 0,
                "valuePct": 2.1,
            },
            {
                "node": "Iron Grip",
                "adds": ["Add Strength", "Add Life"],
                "allocated": False,
                "pointsToReach": 2,
                "valuePct": 0.4,
            },
        ],
        "pickUp": None,
        "extraPoints": 2,
        "changePct": {"dps": 6.1, "ehp": -1.5, "life": 0.0},
        "scoreGainPct": 4.2,
        "trade": compressed(QUERY),
        "tradeAnyConqueror": compressed(QUERY),
    }
    return {
        "jewel": "Lethal Pride",
        "conqueror": "Akoya",
        "mode": "balanced",
        "currentTimeless": None,
        "best": seed,
        "alternatives": [{**seed, "seed": 11111, "scoreGainPct": 1.0}] * 6,
        "applied": None,
        "socketsScanned": 5,
        "seedsPerSocket": 8001,
        "pointValuePct": 0.31,
        "seconds": 6.2,
        "tradeTopSeeds": compressed(QUERY),
        "verdict": "Seed 12345 near Ironwood: +4.2% score on the current tree (not rebuilt).",
        **overrides,
    }


def test_arguments_keep_the_run_within_a_chat_answer() -> None:
    args = timeless.arguments_for_pob(
        {"jewel": "lethal pride", "conqueror": "AKOYA", "max_path": 30, "apply": "yes", "jobs": 8}
    )
    assert args == {
        "jewel": "Lethal Pride",
        "conqueror": "Akoya",
        "mode": "balanced",
        "max_path": timeless.MAX_PATH,
        "max_pick": timeless.PICK,
        "apply": False,  # only a real true applies
        "rebuild": 0,
        "max_seconds": timeless.MAX_SECONDS,
        "jobs": 1,
    }


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"jewel": "Glorious Vanity", "conqueror": "Doryani"}, "Glorious Vanity isn't supported"),
        ({"jewel": "Lethal Pride", "conqueror": "Cadiro"}, "Kaom, Rakiata, Akoya"),
    ],
)
def test_jewels_and_conquerors_are_checked(arguments, message) -> None:
    with pytest.raises(timeless.TimelessError, match=message):
        timeless.arguments_for_pob(arguments)


def test_compressed_trade_links_become_plain_ones() -> None:
    url = timeless.plain_trade_link(compressed(QUERY, league="Mirage Hardcore"))
    parsed = urlparse(url)
    assert parsed.path == "/trade/search/Mirage%20Hardcore"
    assert json.loads(parse_qs(parsed.query)["q"][0]) == QUERY
    assert timeless.plain_trade_link("https://example.com/nope") == ""
    assert timeless.plain_trade_link("https://www.pathofexile.com/trade/search/Mirage/@@@") == ""


def test_the_summary_has_links_and_the_model_text_has_none() -> None:
    summary = timeless.summarise(raw_result())
    assert summary["best"]["seed"] == 12345
    assert summary["best"]["notables"][1]["becomes"] == "Add Strength; Add Life"
    assert summary["best"]["trade_url"].startswith(timeless.TRADE_ROOT + "Mirage?q=")
    assert len(summary["alternatives"]) == timeless.ALTERNATIVES
    assert summary["top_seeds_url"]
    assert "seeds_tied" not in summary["best"]
    tied = timeless.summarise(raw_result(best={**raw_result()["best"], "seedsTiedWithBest": 40}))
    assert tied["best"]["seeds_tied"] == 40
    text = timeless.for_model(summary)
    assert "pathofexile.com/trade" not in text
    assert "12345" in text and "estimate" in text


NO_ITEMS = ToolResult(ok=True, text="", data={"items": []})
SOCKETED = {
    "base": "Timeless Jewel",
    "id": 8,
    "name": "Lethal Pride, Timeless Jewel",
    "rarity": "UNIQUE",
    "raw": (
        "Rarity: UNIQUE\nLethal Pride\nTimeless Jewel\nLeague: Legion\nRadius: Large\n"
        "Limited to: 1\nImplicits: 0\nCommanded leadership over 11403 warriors under Kaom\n"
        "Passives in radius are Conquered by the Karui\nHistoric"
    ),
    "slot": "Jewel socket 61419",
}
RARE = {
    "base": "Cobalt Jewel",
    "name": "Honour Vessel, Cobalt Jewel",
    "raw": "",
    "slot": "Jewel socket 1",
}


class FakeToolbox:
    has_build = True

    def __init__(self, result: ToolResult, items: ToolResult = NO_ITEMS) -> None:
        self.result = result
        self.items = items
        self.calls: list[tuple[str, dict]] = []

    def call_internal(self, name: str, arguments: dict) -> ToolResult:
        self.calls.append((name, arguments))
        return self.items if name == "get_items" else self.result

    def searched(self) -> list[dict]:
        return [args for name, args in self.calls if name == timeless.TOOL_NAME]


def test_the_runner_shows_the_seeds_and_reports_errors() -> None:
    toolbox = FakeToolbox(ToolResult(ok=True, text="", data=raw_result()))
    runner = _ToolRunner(toolbox)  # type: ignore[arg-type]
    call = ToolCall(
        "t1", timeless.TOOL_NAME, json.dumps({"jewel": "Lethal Pride", "conqueror": "Akoya"})
    )
    events, text = runner.run(call)
    assert toolbox.searched()[0]["rebuild"] == 0
    assert events[-1]["type"] == "timeless"
    assert events[-1]["best"]["trade_url"]
    assert "trade/search" not in text

    failing = FakeToolbox(ToolResult(ok=False, text="No jewel socket near the tree.", data=None))
    events, text = _ToolRunner(failing).run(call)  # type: ignore[arg-type]
    assert events[-1]["ok"] is False
    assert text == "Error: No jewel socket near the tree."


def test_a_bad_conqueror_never_reaches_path_of_building() -> None:
    toolbox = FakeToolbox(ToolResult(ok=True, text="", data=raw_result()))
    call = ToolCall(
        "t1", timeless.TOOL_NAME, json.dumps({"jewel": "Lethal Pride", "conqueror": "Bob"})
    )
    events, text = _ToolRunner(toolbox).run(call)  # type: ignore[arg-type]
    assert toolbox.searched() == []
    assert text.startswith("Error: Lethal Pride's conqueror")


def test_an_unreadable_result_is_an_error() -> None:
    with pytest.raises(PobToolError):
        timeless.find(
            FakeToolbox(ToolResult(ok=True, text="", data=None)).call_internal,
            {"jewel": "Lethal Pride", "conqueror": "Kaom"},
        )


def test_the_socketed_jewel_is_read_from_the_items() -> None:
    assert timeless.socketed({"items": [RARE, SOCKETED]}) == {
        "jewel": "Lethal Pride",
        "seed": 11403,
        "conqueror": "Kaom",
        "socket": 61419,
    }
    assert timeless.socketed({"items": [RARE]}) is None
    vanity = {
        **SOCKETED,
        "name": "Glorious Vanity, Timeless Jewel",
        "raw": (
            "Glorious Vanity\nImplicits: 0\n"
            "Bathed in the blood of 2000 sacrificed in the name of Doryani"
        ),
    }
    assert timeless.socketed({"items": [vanity]})["seed"] == 2000


def test_with_a_jewel_socketed_the_search_starts_from_it() -> None:
    current = timeless.socketed({"items": [SOCKETED]})
    args = timeless.arguments_for_pob({}, current)
    assert (args["jewel"], args["conqueror"]) == ("Lethal Pride", "Kaom")
    assert args["max_pick"] == timeless.PICK_WITH_JEWEL  # transformed notables further out
    # Another jewel: its conqueror must be given.
    with pytest.raises(timeless.TimelessError, match="Cadiro"):
        timeless.arguments_for_pob({"jewel": "Elegant Hubris"}, current)
    with pytest.raises(timeless.TimelessError, match="no timeless jewel socketed"):
        timeless.arguments_for_pob({})


def test_results_in_the_current_jewels_socket_are_swaps() -> None:
    toolbox = FakeToolbox(
        ToolResult(ok=True, text="", data=raw_result()),
        ToolResult(ok=True, text="", data={"items": [SOCKETED]}),
    )
    result = timeless.find(toolbox.call_internal, {})
    assert toolbox.searched()[0]["jewel"] == "Lethal Pride"
    assert result["current"]["seed"] == 11403
    assert result["best"]["replaces_current"] is True
    assert "straight swap" in result["note"]

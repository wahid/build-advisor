"""pob-mcp integration: argument safety and the process pool over real MCP stdio."""

import sys
from pathlib import Path

import pytest

from advisor.pob import (
    PobPool,
    PobToolError,
    openai_tool_definitions,
    sanitize_arguments,
    validate_build_source,
)

FAKE_SERVER = [sys.executable, str(Path(__file__).with_name("fake_pob_server.py"))]
ALLOWED = (
    "new_build",
    "get_build_summary",
    "load_build",
    "export_build",
    "slow",
    "fail",
    "received",
    "resets",
)
SHARE_CODE = "eNrtW1tz2jgUft" * 10


# --- argument safety -----------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        SHARE_CODE,
        f"  {SHARE_CODE[:60]}\n{SHARE_CODE[60:]}  ",
        "https://pobb.in/AbC123",
        "https://pastebin.com/xyz",
    ],
)
def test_accepts_share_codes_and_known_links(source: str) -> None:
    assert validate_build_source(source)


@pytest.mark.parametrize(
    "source",
    [
        "/etc/passwd",
        "C:\\Users\\me\\build.xml",
        "<PathOfBuilding></PathOfBuilding>",
        "http://pobb.in/AbC123",  # not https
        "https://evil.example/pobb.in",
        "https://pobb.in/",
        "https://poe.ninja/builds/character/x",
        "short",
    ],
)
def test_rejects_paths_xml_and_other_hosts(source: str) -> None:
    with pytest.raises(PobToolError):
        validate_build_source(source)


def test_sanitize_strips_file_arguments() -> None:
    assert sanitize_arguments("export_build", {"format": "xml", "save_to": "/tmp/x"}) == {
        "format": "code"
    }
    assert sanitize_arguments("load_build", {"source": SHARE_CODE, "name": "../x"}) == {
        "source": SHARE_CODE
    }
    assert sanitize_arguments("get_stats", {"filter": "Life"}) == {"filter": "Life"}


def test_tool_definitions_follow_the_allowlist_and_hide_file_parameters() -> None:
    from types import SimpleNamespace

    tools = [
        SimpleNamespace(
            name="export_build",
            description="Export",
            input_schema={
                "title": "x",
                "type": "object",
                "properties": {"format": {}, "save_to": {}},
            },
        ),
        SimpleNamespace(
            name="load_build",
            description="Load",
            input_schema={
                "type": "object",
                "properties": {"source": {}, "name": {}},
                "required": ["source"],
            },
        ),
        SimpleNamespace(name="save_to_pob", description="Save", input_schema={"type": "object"}),
    ]

    definitions = openai_tool_definitions(tools, {"export_build", "load_build"})

    by_name = {d["function"]["name"]: d["function"]["parameters"] for d in definitions}
    assert set(by_name) == {"export_build", "load_build"}
    assert by_name["export_build"]["properties"] == {}
    assert set(by_name["load_build"]["properties"]) == {"source"}
    assert "title" not in by_name["export_build"]


# --- pool over real MCP stdio --------------------------------------------------


@pytest.fixture
def pool():
    p = PobPool(FAKE_SERVER, env={}, size=1, allowed=ALLOWED, call_timeout=5, startup_timeout=30)
    yield p
    p.close()


def test_each_checkout_starts_with_an_empty_build(pool: PobPool) -> None:
    with pool.toolbox() as toolbox:
        toolbox.call("new_build", {"ascendancy": "Slayer"})
        assert toolbox.call("get_build_summary", {}).data == {"ascendancy": "Slayer"}

    with pool.toolbox() as toolbox:
        assert toolbox.call("get_build_summary", {}).data == {"ascendancy": None}


def test_model_never_sees_or_reaches_tools_outside_the_allowlist(pool: PobPool) -> None:
    with pool.toolbox() as toolbox:
        names = {d["function"]["name"] for d in toolbox.definitions}
        assert "save_to_pob" not in names
        with pytest.raises(PobToolError, match="Unknown tool"):
            toolbox.call("save_to_pob", {"name": "x"})


def test_file_arguments_never_reach_the_server(pool: PobPool) -> None:
    with pool.toolbox() as toolbox:
        exported = toolbox.call("export_build", {"save_to": "/tmp/evil.xml", "format": "xml"})
        toolbox.call("load_build", {"source": SHARE_CODE, "name": "../../etc"})
        received = toolbox.call("received", {}).data

    assert exported.data == {"code": "eNrFAKE", "format": "code", "save_to": None}
    assert received == [{"load_build": {"source": SHARE_CODE, "name": None}}]


def test_tool_errors_are_results_not_crashes(pool: PobPool) -> None:
    with pool.toolbox() as toolbox:
        result = toolbox.call("fail", {})
        assert result.ok is False
        assert "fail" in result.text
        assert toolbox.call("get_build_summary", {}).ok  # still usable


def test_a_hung_server_is_replaced(pool: PobPool) -> None:
    pool.call_timeout = 1
    with pool.toolbox() as toolbox, pytest.raises(PobToolError, match="longer than"):
        toolbox.call("slow", {"seconds": 5})

    with pool.toolbox() as toolbox:  # a fresh process
        assert toolbox.call("get_build_summary", {}).data == {"ascendancy": None}


# --- keeping a loaded build for follow-up questions --------------------------------


def _resets(toolbox) -> int:
    # Straight to the process: the test-only tool would count as a change otherwise.
    return toolbox._server.call("resets", {}, 5).data


def _load(pool: PobPool, source: str) -> None:
    with pool.toolbox(build=source) as toolbox:
        assert toolbox.reused is False
        toolbox.call("load_build", {"source": source})
        toolbox.mark_loaded(source)


def test_a_follow_up_with_the_same_build_keeps_it_loaded(pool: PobPool) -> None:
    _load(pool, SHARE_CODE)

    with pool.toolbox(build=SHARE_CODE) as toolbox:
        before = _resets(toolbox)
        toolbox.call("get_build_summary", {})  # reading doesn't change the build
    with pool.toolbox(build=SHARE_CODE) as toolbox:
        assert toolbox.reused is True
        assert _resets(toolbox) == before


def test_another_build_starts_from_a_reset(pool: PobPool) -> None:
    _load(pool, SHARE_CODE)

    with pool.toolbox(build="https://pobb.in/other") as toolbox:
        assert toolbox.reused is False
        resets = _resets(toolbox)
    with pool.toolbox() as toolbox:  # no build: empty, but already clean
        assert toolbox.reused is False
        assert _resets(toolbox) == resets


def test_a_changed_build_is_loaded_again(pool: PobPool) -> None:
    _load(pool, SHARE_CODE)
    with pool.toolbox(build=SHARE_CODE) as toolbox:
        toolbox.call("new_build", {"ascendancy": "Slayer"})  # any changing tool

    with pool.toolbox(build=SHARE_CODE) as toolbox:
        assert toolbox.reused is False
        assert toolbox.call("get_build_summary", {}).data == {"ascendancy": None}


def test_an_exported_build_can_be_continued_without_loading(pool: PobPool) -> None:
    _load(pool, SHARE_CODE)
    with pool.toolbox(build=SHARE_CODE) as toolbox:
        toolbox.call("new_build", {"ascendancy": "Slayer"})
        code = toolbox.call("export_build", {}).data["code"]

    with pool.toolbox(build=code) as toolbox:
        assert toolbox.reused is True
        assert toolbox.call("get_build_summary", {}).data == {"ascendancy": "Slayer"}

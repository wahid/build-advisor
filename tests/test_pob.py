"""pob-mcp integration: argument safety and the process pool over real MCP stdio."""

import base64
import sys
import zlib
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


def test_leveling_uses_the_quick_planner_and_tools_start_no_extra_processes() -> None:
    from types import SimpleNamespace

    assert sanitize_arguments(
        "plan_leveling", {"levels": [40], "method": "nested", "jobs": 4, "mode": "dps"}
    ) == {"levels": [40], "method": "greedy"}
    assert sanitize_arguments("auto_allocate_passives", {"points": 5, "jobs": 4}) == {"points": 5}

    tools = [
        SimpleNamespace(
            name="plan_leveling",
            description="nested takes a minute or two",
            input_schema={
                "type": "object",
                "properties": {"levels": {}, "weights": {}, "method": {}, "mode": {}, "jobs": {}},
            },
        ),
        SimpleNamespace(
            name="rank_passives",
            description="Rank",
            input_schema={"type": "object", "properties": {"top": {}, "jobs": {}}},
        ),
    ]
    by_name = {
        d["function"]["name"]: d["function"]
        for d in openai_tool_definitions(tools, {"plan_leveling", "rank_passives"})
    }
    assert set(by_name["plan_leveling"]["parameters"]["properties"]) == {"levels", "weights"}
    assert "minute" not in by_name["plan_leveling"]["description"]
    assert set(by_name["rank_passives"]["parameters"]["properties"]) == {"top"}


# --- pool over real MCP stdio --------------------------------------------------


def _summary(toolbox) -> dict:
    """What the process holds, read past the toolbox's no-build check."""
    return toolbox._server.call("get_build_summary", {}, 5).data


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
        assert _summary(toolbox) == {"ascendancy": None}


def test_without_a_build_tools_that_need_one_say_so(pool: PobPool) -> None:
    with pool.toolbox() as toolbox:
        with pytest.raises(PobToolError, match="No build is loaded"):
            toolbox.call("get_build_summary", {})
        toolbox.call("new_build", {"ascendancy": "Slayer"})  # now there is one
        assert toolbox.call("get_build_summary", {}).data == {"ascendancy": "Slayer"}


def test_model_never_sees_or_reaches_tools_outside_the_allowlist(pool: PobPool) -> None:
    with pool.toolbox() as toolbox:
        names = {d["function"]["name"] for d in toolbox.definitions}
        assert "save_to_pob" not in names
        with pytest.raises(PobToolError, match="Unknown tool"):
            toolbox.call("save_to_pob", {"name": "x"})


def test_file_arguments_never_reach_the_server(pool: PobPool) -> None:
    with pool.toolbox() as toolbox:
        toolbox.call("new_build", {})
        exported = toolbox.call("export_build", {"save_to": "/tmp/evil.xml", "format": "xml"})
        toolbox.call("load_build", {"source": SHARE_CODE, "name": "../../etc"})
        received = toolbox.call("received", {}).data

    assert exported.data == {"code": "eNrFAKE", "format": "code", "save_to": None}
    assert received == [{"load_build": {"source": SHARE_CODE, "name": None}}]


def test_tool_errors_are_results_not_crashes(pool: PobPool) -> None:
    with pool.toolbox() as toolbox:
        toolbox.call("new_build", {})
        result = toolbox.call("fail", {})
        assert result.ok is False
        assert "fail" in result.text
        assert toolbox.call("get_build_summary", {}).ok  # still usable


def test_a_hung_server_is_replaced(pool: PobPool) -> None:
    pool.call_timeout = 1
    with pool.toolbox() as toolbox, pytest.raises(PobToolError, match="longer than"):
        toolbox.call("new_build", {})
        toolbox.call("slow", {"seconds": 5})

    with pool.toolbox() as toolbox:  # a fresh process
        assert _summary(toolbox) == {"ascendancy": None}


def test_a_crashed_path_of_building_is_replaced(pool: PobPool) -> None:
    with pool.toolbox() as toolbox:
        toolbox.call("new_build", {})
        result = toolbox._server.call("crash", {}, 5)
        assert result.ok is False
        assert result.text.startswith("Path of Building crashed on this build (In 'OnFrame': ")
        assert "Build.lua:872: attempt to index a nil value)" in result.text
        assert "Press Enter" not in result.text
        assert toolbox._server.call("get_stats", {}, 5).ok is False  # stuck on its crash screen

    with pool.toolbox() as toolbox:  # the next question gets a fresh process
        assert toolbox._server.call("get_stats", {}, 5).data == {"Life": 5000}


def test_a_build_with_an_unknown_tree_is_refused_and_harms_no_one_else(pool: PobPool) -> None:
    with pool.toolbox() as toolbox:
        result = toolbox.call("load_build", {"source": "https://pobb.in/newer-tree"})
        assert result.ok
        result = toolbox.call_internal("load_build", {"source": "newer-tree"})
        assert result.ok is False
        assert "newest passive tree is 3.29" in result.text
        assert toolbox.has_build is True  # from the first load

    with pool.toolbox(build="other") as toolbox:  # the next question: a fresh process
        assert toolbox.call("load_build", {"source": "https://pobb.in/other"}).ok
        assert toolbox._server.call("get_stats", {}, 5).data == {"Life": 5000}


def _code(nodes: str) -> str:
    xml = f'<PathOfBuilding><Tree activeSpec="1"><Spec treeVersion="3_30" nodes="{nodes}"/></Tree>'
    xml += "<Notes>" + "x" * 200 + "</Notes></PathOfBuilding>"
    return base64.urlsafe_b64encode(zlib.compress(xml.encode())).decode()


def test_a_share_code_says_whether_the_build_has_passives() -> None:
    from advisor.pob import allocated_in_source, tree_lost

    with_tree, without = _code("1,2,3,4,5"), _code("1,2")
    assert allocated_in_source(with_tree) == 3  # two are the class and ascendancy starts
    assert allocated_in_source(without) == 0
    assert allocated_in_source("https://pobb.in/abc") is None
    assert allocated_in_source("A" * 200) is None  # not a build

    empty_duelist = {"className": "Duelist", "level": 90, "passivePointsUsed": 0}
    empty_scion = {"className": "Scion", "ascendancy": "None", "level": 90, "passivePointsUsed": 0}
    assert tree_lost(with_tree, empty_scion) is True
    assert tree_lost(with_tree, {**empty_scion, "passivePointsUsed": 3}) is False
    # A build that simply has no passives yet (e.g. one the app just created) loads.
    assert tree_lost(without, empty_duelist) is False
    assert tree_lost(without, empty_scion) is False
    # A link can't be read here: only the empty Scion an unknown tree leaves counts.
    assert tree_lost("https://pobb.in/abc", empty_scion) is True
    assert tree_lost("https://pobb.in/abc", empty_duelist) is False
    assert tree_lost("https://pobb.in/abc", {**empty_scion, "level": 2}) is False


def test_a_reset_that_crashes_gets_a_fresh_process(pool: PobPool) -> None:
    with pool.toolbox() as toolbox:
        toolbox._server.call("load_build", {"source": "newer-tree"}, 5)  # unnoticed
        toolbox._server.changed = True

    with pool.toolbox() as toolbox:
        assert toolbox._server.crashed is False
        assert toolbox._server.call("get_stats", {}, 5).data == {"Life": 5000}


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
        assert _summary(toolbox) == {"ascendancy": None}


def test_an_exported_build_can_be_continued_without_loading(pool: PobPool) -> None:
    _load(pool, SHARE_CODE)
    with pool.toolbox(build=SHARE_CODE) as toolbox:
        toolbox.call("new_build", {"ascendancy": "Slayer"})
        code = toolbox.call("export_build", {}).data["code"]

    with pool.toolbox(build=code) as toolbox:
        assert toolbox.reused is True
        assert toolbox.call("get_build_summary", {}).data == {"ascendancy": "Slayer"}


def test_a_character_import_takes_only_an_account_and_a_name() -> None:
    from advisor.pob import sanitize_arguments

    clean = sanitize_arguments(
        "import_character",
        {
            "account": " Some Name#1234 ",
            "character": "MyArcher",
            "realm": "XBOX",
            "json_path": "/etc/passwd",
        },
    )
    assert clean == {"account": "Some Name#1234", "character": "MyArcher", "realm": "xbox"}
    for bad in (
        {"account": "NoNumber", "character": "MyArcher"},
        {"account": "Name#1234", "character": "../../etc"},
        {"json_path": "/etc/passwd"},
    ):
        with pytest.raises(PobToolError):
            sanitize_arguments("import_character", bad)

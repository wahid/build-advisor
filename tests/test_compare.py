"""Comparing two builds in Path of Building."""

from types import SimpleNamespace

import pytest

from advisor.compare import compare, rows
from advisor.pob import PobToolError, split_build_links

CODE_A = "eNrA" * 30
LINK_B = "https://pobb.in/other"
STATS = {
    "A": {"CombinedDPS": 1000.0, "Life": 4000.0, "FireResist": 75.0, "EnergyShield": 0.0},
    "B": {"CombinedDPS": 1500.0, "Life": 3000.0, "FireResist": 75.0, "EnergyShield": 0.0},
}


class FakeToolbox:
    def __init__(self, fail_b: bool = False) -> None:
        self.loaded = "A"
        self.calls: list[tuple[str, dict]] = []
        self.marked = ""
        self.fail_b = fail_b

    def call_internal(self, name, args):
        self.calls.append((name, args))
        ok = lambda data: SimpleNamespace(ok=True, data=data, text="")  # noqa: E731
        if name == "get_stats":
            return ok(STATS[self.loaded])
        if name == "get_build_summary":
            return ok({"ascendancy": "Slayer" if self.loaded == "A" else "Champion", "level": 95})
        if name == "export_build":
            return ok({"code": CODE_A})
        if name == "load_build":
            if args["source"] == LINK_B and self.fail_b:
                return SimpleNamespace(ok=False, data=None, text="pobb.in is down")
            self.loaded = "B" if args["source"] == LINK_B else "A"
            return ok({})
        raise AssertionError(name)

    def mark_loaded(self, source):
        self.marked = source


def test_two_builds_are_compared_and_the_first_is_loaded_again() -> None:
    toolbox = FakeToolbox()

    result = compare(toolbox, "https://pobb.in/mine", LINK_B)

    assert result["a"]["ascendancy"] == "Slayer" and result["b"]["ascendancy"] == "Champion"
    by_stat = {r["stat"]: r for r in result["rows"]}
    assert by_stat["CombinedDPS"]["change_pct"] == 50.0
    assert by_stat["Life"]["change_pct"] == -25.0
    assert "EnergyShield" not in by_stat  # zero on both sides says nothing
    assert toolbox.loaded == "A"
    assert ("load_build", {"source": CODE_A}) in toolbox.calls
    assert toolbox.marked == "https://pobb.in/mine"


def test_a_build_that_wont_load_is_an_error() -> None:
    with pytest.raises(PobToolError, match="pobb.in is down"):
        compare(FakeToolbox(fail_b=True), "https://pobb.in/mine", LINK_B)


def test_rows_handle_a_zero_on_one_side() -> None:
    [row] = rows({"EnergyShield": 0.0}, {"EnergyShield": 500.0})

    assert row["change_pct"] is None and row["b"] == 500.0


def test_two_links_in_a_question_are_both_found() -> None:
    rest, links = split_build_links("Compare https://pobb.in/aaa with https://pobb.in/bbb please")

    assert links == ["https://pobb.in/aaa", "https://pobb.in/bbb"]
    assert rest == "Compare build A with build B please"


@pytest.mark.django_db
def test_the_ask_endpoint_takes_the_second_link_as_the_comparison(client, mocker) -> None:
    stream = mocker.patch("advisor.views.answer_stream", return_value=iter([]))
    body = {
        "question": "Which is tankier, https://pobb.in/aaa or https://pobb.in/bbb?",
        "stream": False,
    }

    assert client.post("/api/ask/", body, content_type="application/json").status_code == 200

    kwargs = stream.call_args.kwargs
    assert (kwargs["build"], kwargs["compare_build"]) == (
        "https://pobb.in/aaa",
        "https://pobb.in/bbb",
    )
    assert stream.call_args.args[0] == "Which is tankier, build A or build B?"

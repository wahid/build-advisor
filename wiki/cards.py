"""In-game style tooltip cards, from the item box on a wiki page.

The wiki draws gems and items like the game's tooltips: a header (name, and
base type for uniques), then groups of lines, each piece of text marked as a
value, a modifier, a gem description, flavour text and so on. This keeps that
structure as JSON, so the frontend can draw the same tooltip (without the
game's images).

A card: {"frame": "gem" | "unique" | ..., "header": [lines],
         "groups": [{"style": "mod", "lines": [[{"t": text, "s": style}, ...], ...]}]}
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

MAX_GROUPS = 12
MAX_LINES = 40
MAX_TEXT = 400
BOX_SLICE = 40_000  # characters of HTML from the item box on; enough for any box
STYLE_RE = re.compile(r"^-([a-z]+)$")


def _style(tag: Tag, inherited: str) -> str:
    classes = tag.get("class") or []
    if "tc" in classes:
        for name in classes:
            match = STYLE_RE.match(name)
            if match:
                return match.group(1)
    return inherited


def _segments(node: Tag, style: str) -> list[list[dict[str, str]]]:
    """Lines of styled text segments, split at <br>."""
    lines: list[list[dict[str, str]]] = [[]]

    def walk(element: Tag | NavigableString, current: str) -> None:
        if isinstance(element, NavigableString):
            text = re.sub(r"\s+", " ", str(element))
            if text:
                line = lines[-1]
                if line and line[-1]["s"] == current:
                    line[-1]["t"] += text
                else:
                    line.append({"t": text, "s": current})
            return
        if element.name == "br":
            lines.append([])
            return
        if element.name in ("img", "script", "style") or "symbol" in (element.get("class") or []):
            return
        inner = _style(element, current)
        for child in element.children:
            walk(child, inner)

    for child in node.children:
        walk(child, style)

    cleaned: list[list[dict[str, str]]] = []
    for line in lines:
        if line:
            line[0]["t"] = line[0]["t"].lstrip()
            line[-1]["t"] = line[-1]["t"].rstrip()
        line = [{"t": s["t"][:MAX_TEXT], "s": s["s"]} for s in line if s["t"]]
        if line or (cleaned and cleaned[-1]):  # keep one blank line as a spacer
            cleaned.append(line)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return cleaned[:MAX_LINES]


def parse_card(html: str) -> dict[str, Any] | None:
    """The tooltip card of a page, or None if the page has no item box."""
    start = html.find('class="item-box')
    if start < 0:
        return None
    tag_start = html.rfind("<", 0, start)
    soup = BeautifulSoup(html[tag_start : tag_start + BOX_SLICE], "html.parser")
    box = soup.select_one(".item-box")
    if box is None:
        return None
    frame = next((m.group(1) for c in box.get("class") or [] if (m := STYLE_RE.match(c))), "normal")
    header_tag = box.select_one(".header")
    header = (
        [" ".join(s["t"] for s in line) for line in _segments(header_tag, "header") if line]
        if header_tag
        else []
    )
    stats = box.select_one(".item-stats")
    groups = []
    for group in (stats.find_all("span", class_="group", recursive=False) if stats else [])[
        :MAX_GROUPS
    ]:
        style = _style(group, "default")
        lines = _segments(group, style)
        if lines:
            groups.append({"style": style, "lines": lines})
    if not header and not groups:
        return None
    return {"frame": frame, "header": header[:2], "groups": groups}

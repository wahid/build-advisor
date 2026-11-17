"""Text from Maxroll's Build Progression Tool.

Since 2026 a Maxroll build guide's article is only an introduction; the build
itself (overview, gem setups per level, gearing milestones, FAQs) is in the
Build Progression Tool embedded in the page:

    <div class="poe-embed" data-poe-profile="ef5hj0rf" data-poe-id="11"
         data-poe-type="leveling">

The tool loads the profile as JSON from planners.maxroll.gg; `planner_text`
turns the "leveling" embed in it into the same Markdown-like text as the rest
of a stored guide. Written text and gem setups are kept. Passive trees and
equipment sets are stored as node and stat ids, which mean nothing without the
game's data, so only their names are listed; the showcase video is skipped.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

PROFILE_URL = "https://planners.maxroll.gg/profiles/load/poe/{profile_id}"
PROFILE_ID_RE = re.compile(r"^[a-z0-9]{4,16}$")
EMBED_TYPE = "leveling"

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_ALT_RE = re.compile(r"Alt[XYZ]$")
_SMALL_WORDS = {"Of", "To", "The", "And", "On", "In", "With"}
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def planner_ref(html: str) -> tuple[str, int | None] | None:
    """(profile id, embed id) of the page's Build Progression Tool, if it has one."""
    soup = BeautifulSoup(html, "html.parser")
    for element in soup.select("[data-poe-profile]"):
        if not isinstance(element, Tag):
            continue
        if str(element.get("data-poe-type", EMBED_TYPE)) != EMBED_TYPE:
            continue
        profile_id = str(element.get("data-poe-profile", "")).strip()
        if not PROFILE_ID_RE.match(profile_id):
            continue
        embed_id = str(element.get("data-poe-id", ""))
        return profile_id, int(embed_id) if embed_id.isdigit() else None
    return None


def profile_url(profile_id: str) -> str:
    if not PROFILE_ID_RE.match(profile_id):
        raise ValueError(f"Not a Maxroll planner profile id: {profile_id}")
    return PROFILE_URL.format(profile_id=profile_id)


def planner_text(profile: Any, embed_id: int | None = None) -> str:
    """The progression tool's content as text; "" when the profile has none.

    The format is Maxroll's own and not documented, so anything unexpected is
    logged and skipped instead of failing the guide.
    """
    try:
        data = profile.get("data") if isinstance(profile, dict) else None
        if isinstance(data, str):
            data = json.loads(data)
        embeds = [e for e in _list(_dict(data).get("embeds")) if isinstance(e, dict)]
        return _Planner(embeds).text(embed_id)
    except Exception:  # noqa: BLE001 - an unknown format must not lose the article
        logger.warning("Couldn't read the Maxroll progression tool data", exc_info=True)
        return ""


def gem_name(gem_id: str) -> str:
    """ "SupportChanceToPoison" -> "Chance to Poison Support" (the planner stores ids)."""
    transfigured = bool(_ALT_RE.search(gem_id))
    words = _CAMEL_RE.split(_ALT_RE.sub("", gem_id))
    support = len(words) > 1 and words[0] == "Support"
    if support:
        words = words[1:]
    words = [w.lower() if i and w in _SMALL_WORDS else w for i, w in enumerate(words)]
    name = " ".join(words) + (" Support" if support else "")
    return f"{name} (transfigured version)" if transfigured else name


def rich_text(node: Any, heading: str = "###") -> str:
    """Plain text of the tool's rich-text JSON (a Lexical editor state).

    heading: the Markdown prefix for the text's top-level headings.
    """
    blocks = [_block(child, heading) for child in _list(_dict(_dict(node).get("root"), node))]
    text = "\n\n".join(block for block in blocks if block.strip())
    return _BLANK_LINES_RE.sub("\n\n", text).strip()


def _dict(value: Any, default: Any = None) -> dict:
    if isinstance(value, dict):
        return value
    return default if isinstance(default, dict) else {}


def _list(value: Any) -> list:
    if isinstance(value, dict):
        value = value.get("children")
    return value if isinstance(value, list) else []


def _inline(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return str(node.get("text") or "")
    if kind == "linebreak":
        return "\n"
    if kind == "embed":
        # An item, skill or passive shown with its icon: its name. Ads have no text.
        return str(node.get("text") or "") if node.get("embedType") != "ad" else ""
    return "".join(_inline(child) for child in _list(node))


def _block(node: Any, heading: str) -> str:
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "heading":
        text = " ".join(_inline(node).split())
        extra = "#" if str(node.get("tag", "h1")) not in ("h1", "") else ""
        return f"{heading}{extra} {text}" if text else ""
    if kind == "list":
        items = []
        for item in _list(node):
            nested = [c for c in _list(item) if isinstance(c, dict) and c.get("type") == "list"]
            own = {**item, "children": [c for c in _list(item) if c not in nested]}
            text = " ".join(_inline(own).split())
            if text:
                items.append(f"- {text}")
            items.extend(_block(n, heading) for n in nested)
        return "\n".join(i for i in items if i)
    if kind in ("horizontalrule", "page-break"):
        return ""
    lines = [" ".join(line.split()) for line in _inline(node).split("\n")]
    return "\n".join(lines).strip()


class _Planner:
    def __init__(self, embeds: list[dict]) -> None:
        self.embeds = embeds
        self.by_id = {e.get("id"): e for e in embeds}

    def text(self, embed_id: int | None) -> str:
        guide = self.by_id.get(embed_id)
        if _dict(guide).get("type") != EMBED_TYPE:
            guide = next((e for e in self.embeds if e.get("type") == EMBED_TYPE), None)
        if guide is None:
            return ""
        overview = _dict(guide.get("overview"))
        sections: list[str] = []
        tabs = [t for t in _list(guide.get("tabs")) if isinstance(t, dict)]
        for tab in tabs or [{"id": "overview"}, {"id": "leveling"}, {"id": "progression"}]:
            name = str(tab.get("name") or "").strip()
            if tab.get("id") == "overview":
                sections.append(self._overview(guide, overview))
                sections.append(self._setups("## Skill gem setups", overview.get("skills")))
            elif tab.get("id") == "leveling":
                sections.append(self._leveling(guide))
            elif tab.get("id") == "progression":
                sections.extend(self._milestones(guide))
            elif "content" in tab and name:
                body = rich_text(tab["content"], "###")
                sections.append(f"## {name}\n\n{body}" if body else "")
        return "\n\n".join(s for s in sections if s.strip())

    def _overview(self, guide: dict, overview: dict) -> str:
        parts = [f"## Build overview: {str(overview.get('title') or '').strip()}".rstrip(": ")]
        facts = []
        if overview.get("league"):
            facts.append(f"League: {overview['league']}")
        ascendancy = _dict(self.by_id.get(_dict(overview.get("ascendancy")).get("id")))
        if ascendancy.get("ascendancy"):
            facts.append(f"Ascendancy: {ascendancy['ascendancy']}")
        if overview.get("bandits"):
            bandit = str(overview["bandits"])
            facts.append("Bandits: kill all" if bandit == "all" else f"Bandits: help {bandit}")
        for rating in _list(overview.get("buildRating")):
            if isinstance(rating, dict) and rating.get("title") and rating.get("subtitle"):
                facts.append(f"{rating['title']}: {rating['subtitle']}")
        if facts:
            parts.append("\n".join(f"- {fact}" for fact in facts))
        parts.append(rich_text(overview.get("introduction")))
        verdict = _dict(overview.get("strengthsAndWeaknesses"))
        for key, label in (("strengths", "Strengths"), ("weaknesses", "Weaknesses")):
            values = [str(v) for v in _list(verdict.get(key)) if v]
            if values:
                parts.append(f"{label}: {', '.join(values)}.")
        pobs = [
            f"- {pob.get('label') or 'Path of Building'}: {pob['link']}"
            for pob in _list(guide.get("pobs"))
            if isinstance(pob, dict) and pob.get("link")
        ]
        if pobs:
            parts.append("Path of Building links:\n" + "\n".join(pobs))
        trees = _dict(self.by_id.get(_dict(overview.get("passives")).get("id")))
        names = [
            f"{v.get('name')} ({len(_list(v.get('history')))} points)"
            for v in _list(trees.get("variants"))
            if isinstance(v, dict) and v.get("name")
        ]
        if names:
            parts.append(
                "Passive trees in Maxroll's planner (open the guide for the nodes): "
                + ", ".join(names)
                + "."
            )
        return "\n\n".join(p for p in parts if p.strip())

    def _groups(self, step: Any) -> str:
        lines = []
        for group in _list(_dict(step).get("skills")):
            gems = [
                gem_name(str(g["id"]))
                for g in _list(_dict(group).get("gems"))
                if isinstance(g, dict) and g.get("id")
            ]
            if gems:
                lines.append("- " + " + ".join(gems))
        return "\n".join(lines)

    def _steps(self, ref: Any) -> list:
        return _list(_dict(self.by_id.get(_dict(ref).get("id"))).get("steps"))

    def _setups(self, title: str, ref: Any) -> str:
        """Every step of a skills embed (e.g. "Early", "Mid", "Late"), one link per line."""
        parts = []
        for step in self._steps(ref):
            groups = self._groups(step)
            if groups:
                parts.append(f"### {str(_dict(step).get('name') or 'Setup').strip()}\n\n{groups}")
        return f"{title}\n\n" + "\n\n".join(parts) if parts else ""

    def _leveling(self, guide: dict) -> str:
        parts = []
        previous = None
        for step in _list(guide.get("steps")):
            ref = _dict(_dict(step).get("skills"))
            key = (ref.get("id"), ref.get("index"))
            steps = self._steps(ref)
            index = ref.get("index")
            if key == previous or not isinstance(index, int) or not 0 <= index < len(steps):
                continue
            previous = key
            groups = self._groups(steps[index])
            if groups:
                level = _dict(step).get("level") or 1
                parts.append(f"### From level {level}\n\n{groups}")
        if guide.get("showTipsAndTricks", True):
            tips = rich_text(guide.get("tipsAndTricks"), "####")
            if tips:
                parts.append(f"### Tips and tricks\n\n{tips}")
        if not parts:
            return ""
        return "## Leveling: skill gems by level\n\n" + "\n\n".join(parts)

    def _milestones(self, guide: dict) -> list[str]:
        sections = []
        for milestone in _list(guide.get("milestones")):
            parts = []
            for item in _list(_dict(milestone).get("items")):
                body = rich_text(_dict(item).get("content"), "####")
                title = str(_dict(item).get("title") or "").strip()
                if body:
                    parts.append(f"### {title}\n\n{body}" if title else body)
            title = str(_dict(milestone).get("title") or "").strip()
            if parts:
                sections.append(f"## Progression: {title}\n\n" + "\n\n".join(parts))
        return sections

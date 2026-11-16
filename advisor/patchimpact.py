"""The patch_changes tool: what recent patch notes say about a build's parts.

The wiki's "Version x.y.z" pages are stored as patch-note documents. This finds
the lines in them that name the build's skill gems, supports, unique items and
ascendancy (or names given by the model), for the current major version and its
hotfixes, each with the heading it stands under. A plain text match on the
database: no model and no Path of Building needed, so it can't invent a change.
"""

from __future__ import annotations

import re
from typing import Any

from wiki.models import Document, DocumentType

from .pob import PobToolbox

TOOL_NAME = "patch_changes"
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)([a-z]?)")
MAX_NAMES = 30
MAX_LINES = 40
MAX_LINE_CHARS = 320
MAX_MAJORS = 3
SUPPORT_SUFFIX = " Support"

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Find what the recent patch notes say about specific skill gems, support gems, "
            "unique items or ascendancies: the exact lines from the wiki's patch-note pages "
            "for the current major version and its hotfixes. Use it for 'what did the patch "
            "change for my build', 'was X nerfed' or 'what changed for Y this league'. "
            "Without names it uses the attached build's gems, uniques and ascendancy. "
            "Quote or paraphrase only the lines it returns; no line means no change is "
            "mentioned, not that nothing changed indirectly."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Gem, item or ascendancy names, as written in the game.",
                },
                "major_versions": {
                    "type": "integer",
                    "description": "How many major versions (leagues) back to look; default 1.",
                },
            },
        },
    },
}


def version_key(title: str) -> tuple[int, int, int, str]:
    match = VERSION_RE.search(title)
    if not match:
        return (0, 0, 0, "")
    return (int(match[1]), int(match[2]), int(match[3]), match[4])


def _build_names(toolbox: PobToolbox) -> list[str]:
    names: list[str] = []
    summary = toolbox.call_internal("get_build_summary", {}).data
    if isinstance(summary, dict) and summary.get("ascendancy"):
        names.append(str(summary["ascendancy"]))
    skills = toolbox.call_internal("get_skills", {}).data
    groups = skills.get("groups", []) if isinstance(skills, dict) else []
    groups = sorted(groups, key=lambda g: not (isinstance(g, dict) and g.get("isMain")))
    for group in groups:
        for gem in group.get("gems", []) if isinstance(group, dict) else []:
            if isinstance(gem, dict) and gem.get("enabled", True) and gem.get("name"):
                names.append(str(gem["name"]))
    items = toolbox.call_internal("get_items", {}).data
    for item in items.get("items", []) if isinstance(items, dict) else []:
        if isinstance(item, dict) and str(item.get("rarity", "")).upper() == "UNIQUE":
            names.append(str(item.get("name", "")).split(",")[0])
    return names


def _pattern(name: str) -> re.Pattern[str]:
    # Patch notes write "Brutality Support" and "Brutality" alike.
    base = name.removesuffix(SUPPORT_SUFFIX)
    # Not "Frenzy Charges" for the Frenzy gem, nor "Cold Snap of Power" for a "Power ..." gem.
    return re.compile(
        rf"(?<![\w'])(?<!\bof ){re.escape(base)}(?![\w'])(?!/)(?! charges?\b)", re.IGNORECASE
    )


def find(names: list[str], major_versions: int = 1) -> dict[str, Any]:
    """Lines naming any of `names` in the newest major versions' patch notes."""
    wanted = list(dict.fromkeys(n.strip() for n in names if n and len(n.strip()) >= 3))[:MAX_NAMES]
    documents = sorted(
        Document.objects.filter(doc_type=DocumentType.PATCH),
        key=lambda d: version_key(d.title),
        reverse=True,
    )
    majors = list(dict.fromkeys(version_key(d.title)[:2] for d in documents))
    keep = set(majors[: max(1, min(major_versions, MAX_MAJORS))])
    documents = [d for d in documents if version_key(d.title)[:2] in keep]
    patterns = [(name, _pattern(name)) for name in wanted]

    changes: list[dict[str, str]] = []
    for document in documents:
        version = document.title.removeprefix("Version ").strip()
        heading = ""
        for line in document.raw_text.splitlines():
            text = line.strip()
            if text.startswith("#"):
                heading = text.lstrip("# ").strip()
                continue
            if len(text) < 12:
                continue
            for name, pattern in patterns:
                if pattern.search(text):
                    changes.append(
                        {
                            "version": version,
                            "name": name,
                            "section": heading,
                            "line": text.lstrip("-• ").strip()[:MAX_LINE_CHARS],
                            "url": document.source.url,
                        }
                    )
                    break
    mentioned = {c["name"] for c in changes}
    return {
        "versions": [d.title.removeprefix("Version ").strip() for d in documents],
        "changes": changes[:MAX_LINES],
        "more": max(0, len(changes) - MAX_LINES),
        "not_mentioned": [n for n in wanted if n not in mentioned],
        "note": (
            "Lines from the wiki's patch-note pages that name these things. Changes that "
            "affect a build without naming its parts (general mechanics, monsters, the "
            "passive tree) aren't included."
        ),
    }


def run(arguments: dict[str, Any], toolbox: PobToolbox | None) -> dict[str, Any]:
    names = [str(n) for n in arguments.get("names") or [] if isinstance(n, str)]
    if not names and toolbox is not None and toolbox.has_build:
        names = _build_names(toolbox)
    if not names:
        raise ValueError("Name the gems or items to look up (no build is attached).")
    try:
        majors = int(arguments.get("major_versions") or 1)
    except (TypeError, ValueError):
        majors = 1
    return find(names, majors)

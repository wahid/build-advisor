"""The quest_rewards tool: where the gems for a build come from while leveling.

A database lookup (wiki/leveling.py), so it works without Path of Building. With a
build loaded, the gems and class can come from the build itself.
"""

from __future__ import annotations

from typing import Any

from wiki.leveling import lookup

from .pob import PobToolbox

TOOL_NAME = "quest_rewards"
CLASSES = ("Marauder", "Duelist", "Ranger", "Shadow", "Witch", "Templar", "Scion")

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Look up, from the wiki, when gems become available while leveling: the level "
            "each gem needs, which quest gives it as a reward to the class, and which vendor "
            "sells it in which act. Use it for leveling plans, 'when can I get X' and "
            "league-start questions. Without gems, it uses the attached build's gems; "
            "without a class, the build's class."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "gems": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Gem names, e.g. ['Cyclone', 'Brutality Support'].",
                },
                "class_name": {
                    "type": "string",
                    "enum": list(CLASSES),
                    "description": "The base class (Slayer is a Duelist, etc.).",
                },
            },
        },
    },
}


def _build_gems(toolbox: PobToolbox) -> list[str]:
    skills = toolbox.call_internal("get_skills", {}).data
    groups = skills.get("groups", []) if isinstance(skills, dict) else []
    # The main group first: its gems matter most.
    groups = sorted(groups, key=lambda g: not (isinstance(g, dict) and g.get("isMain")))
    names = []
    for group in groups:
        for gem in group.get("gems", []) if isinstance(group, dict) else []:
            if isinstance(gem, dict) and gem.get("enabled", True) and gem.get("name"):
                names.append(str(gem["name"]))
    return names


def run(arguments: dict[str, Any], toolbox: PobToolbox | None) -> dict[str, Any]:
    gems = [str(g) for g in arguments.get("gems") or [] if isinstance(g, str)]
    class_name = arguments.get("class_name") if arguments.get("class_name") in CLASSES else ""
    has_build = toolbox is not None and toolbox.has_build
    if has_build and (not gems or not class_name):
        assert toolbox is not None
        if not gems:
            gems = _build_gems(toolbox)
        if not class_name:
            summary = toolbox.call_internal("get_build_summary", {}).data
            if isinstance(summary, dict) and summary.get("className") in CLASSES:
                class_name = summary["className"]
    if not gems:
        raise ValueError("Name the gems to look up (no build is attached to take them from).")
    rows = lookup(gems, class_name)
    return {
        "class_name": class_name,
        "gems": rows,
        "note": (
            "From the wiki's quest reward and vendor tables. Quest rewards are for this class; "
            "vendors sell a gem after that quest is done (Lilly Roth in act 6 sells most gems "
            "to every class). Gems not listed are drops or need another source."
        ),
    }

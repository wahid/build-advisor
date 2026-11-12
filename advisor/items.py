"""Items pasted from the game (Ctrl+C on an item): parse them and try them on a build.

The game copies an item as plain text: "Item Class:", "Rarity:", the name and base,
then sections separated by "--------". Path of Building reads that text directly
(an `equip_item` edit), so trying an item is one compare_changes call per slot it
could go in; for rings both slots are tried and the better one is shown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .compare import STATS
from .pob import PobToolbox, PobToolError

SEPARATOR = "--------"
MAX_ITEM_TEXT = 6000
ITEM_START_RE = re.compile(r"^(Item Class|Rarity):", re.MULTILINE)
# Ctrl+Alt+C adds affix details in braces; Path of Building and the card don't need them.
ADVANCED_RE = re.compile(r"^\{.*\}$")
TAG_RE = re.compile(r"\s*\((implicit|crafted|enchant|fractured|scourge|crucible)\)$")
PROPERTY_RE = re.compile(r"^([^:]{1,40}):\s*(.+)$")

# Item class -> slots it can be equipped in (tried in this order).
ONE_HANDED = (
    "Claws",
    "Daggers",
    "Rune Daggers",
    "Wands",
    "One Hand Swords",
    "Thrusting One Hand Swords",
    "One Hand Axes",
    "One Hand Maces",
    "Sceptres",
)
TWO_HANDED = ("Bows", "Staves", "Warstaves", "Two Hand Swords", "Two Hand Axes", "Two Hand Maces")
SLOTS: dict[str, tuple[str, ...]] = {
    "Rings": ("Ring 1", "Ring 2"),
    "Amulets": ("Amulet",),
    "Belts": ("Belt",),
    "Helmets": ("Helmet",),
    "Body Armours": ("Body Armour",),
    "Gloves": ("Gloves",),
    "Boots": ("Boots",),
    "Shields": ("Weapon 2",),
    "Quivers": ("Weapon 2",),
    **{name: ("Weapon 1",) for name in (*ONE_HANDED, *TWO_HANDED)},
}
FRAMES = {"normal", "magic", "rare", "unique", "gem", "currency"}
DPS_STATS = ("FullDPS", "CombinedDPS", "TotalDPS")
EHP_WEIGHT = 0.5


class ItemError(ValueError):
    """The text isn't an item, or it can't go on this build."""


@dataclass
class Item:
    text: str
    item_class: str
    rarity: str
    name: str
    base: str
    card: dict[str, Any] = field(default_factory=dict)

    @property
    def slots(self) -> tuple[str, ...]:
        return SLOTS.get(self.item_class, ())

    @property
    def title(self) -> str:
        return f"{self.name}, {self.base}" if self.base and self.base != self.name else self.name

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base": self.base,
            "item_class": self.item_class,
            "rarity": self.rarity,
            "card": self.card,
        }


def split_item(question: str) -> tuple[str, str]:
    """Pull pasted item text out of a question: (the question without it, the item text)."""
    match = ITEM_START_RE.search(question)
    if not match or SEPARATOR not in question[match.start() :]:
        return question, ""
    start = match.start()
    lines = question[start:].splitlines()
    end = len(lines)
    # The item runs until a blank line followed by ordinary text (or the end).
    for i, line in enumerate(lines):
        if not line.strip() and i + 1 < len(lines) and not _item_like(lines[i + 1]):
            end = i
            break
    item = "\n".join(lines[:end]).strip()
    after = "\n".join(lines[end:]).strip()
    rest = "\n".join(part for part in (question[:start].strip(), after) if part)
    return rest, item[:MAX_ITEM_TEXT]


def _item_like(line: str) -> bool:
    return line.strip() == SEPARATOR or bool(ITEM_START_RE.match(line))


def parse_item(text: str) -> Item:
    """Read the game's item text; raises ItemError when it isn't one."""
    text = text.replace("\r\n", "\n").strip()[:MAX_ITEM_TEXT]
    lines = [line.rstrip() for line in text.split("\n") if not ADVANCED_RE.match(line.strip())]
    sections: list[list[str]] = [[]]
    for line in lines:
        if line.strip() == SEPARATOR:
            sections.append([])
        elif line.strip():
            sections[-1].append(line.strip())
    head = sections[0]
    item_class = rarity = ""
    names: list[str] = []
    for line in head:
        if line.startswith("Item Class:"):
            item_class = line.split(":", 1)[1].strip()
        elif line.startswith("Rarity:"):
            rarity = line.split(":", 1)[1].strip().lower()
        else:
            names.append(line)
    if not rarity or not names:
        raise ItemError("That doesn't look like an item copied from the game (Ctrl+C).")
    name, base = names[0], names[1] if len(names) > 1 else names[0]
    item = Item(
        text="\n".join(lines),
        item_class=item_class,
        rarity=rarity,
        name=name,
        base=base,
    )
    item.card = _card(item, names, sections[1:])
    return item


def item_title(text: str) -> str:
    """The item's name for logs; empty when it can't be read."""
    try:
        return parse_item(text).title
    except ItemError:
        return ""


def _card(item: Item, names: list[str], sections: list[list[str]]) -> dict[str, Any]:
    """The in-game tooltip, in the format of wiki cards (see wiki/cards.py)."""
    groups = []
    unique = item.rarity == "unique"
    last_text_section = max(
        (i for i, s in enumerate(sections) if s and s != ["Corrupted"] and not _is_note(s)),
        default=-1,
    )
    for i, section in enumerate(sections):
        if not section or _is_note(section):
            continue
        if section == ["Corrupted"]:
            groups.append(_group("corrupted", [[("Corrupted", "corrupted")]]))
            continue
        has_digits = any(c.isdigit() for c in "".join(section))
        flavour = unique and i == last_text_section and not has_digits
        lines = []
        for line in section:
            tag = TAG_RE.search(line)
            text = TAG_RE.sub("", line)
            if flavour:
                lines.append([(text, "flavour")])
            elif tag:
                kind = tag.group(1)
                style = {"implicit": "mod", "enchant": "enchanted"}.get(kind, kind)
                lines.append([(text, style)])
            elif (prop := PROPERTY_RE.match(line)) and not _looks_like_mod(line):
                lines.append([(f"{prop.group(1)}: ", "default"), (prop.group(2), "value")])
            elif line.endswith(":"):
                lines.append([(line, "default")])
            else:
                lines.append([(line, "mod")])
        style = "flavour" if flavour else lines[0][0][1] if lines else "default"
        groups.append(_group(style, lines))
    frame = item.rarity if item.rarity in FRAMES else "normal"
    header = names[:2] if frame in {"rare", "unique"} else names[:1]
    return {"frame": frame, "header": header, "groups": groups[:12]}


def _is_note(section: list[str]) -> bool:
    return len(section) == 1 and section[0].startswith("Note:")


def _looks_like_mod(line: str) -> bool:
    """'Adds 1 to 2 Fire Damage: ...' style lines are mods even though they hold a colon:
    property names ('Item Level', 'Armour') have no numbers."""
    return any(c.isdigit() or c in "+%" for c in line.split(":", 1)[0])


def _group(style: str, lines: list[list[tuple[str, str]]]) -> dict[str, Any]:
    return {"style": style, "lines": [[{"t": t, "s": s} for t, s in line] for line in lines]}


def _score(changes: dict[str, Any]) -> float:
    def pct(stat: str) -> float:
        value = changes.get(stat, {}).get("pct")
        return float(value) if isinstance(value, int | float) else 0.0

    dps = next((pct(s) for s in DPS_STATS if s in changes), 0.0)
    return dps + EHP_WEIGHT * pct("TotalEHP")


def _rows(changes: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, label, higher_is_better in STATS:
        change = changes.get(key)
        if not isinstance(change, dict):
            continue
        before, after = change.get("before"), change.get("after")
        if not isinstance(before, int | float) or not isinstance(after, int | float):
            continue
        pct = None if before == 0 else round((after - before) / abs(before) * 100, 1)
        rows.append(
            {
                "stat": key,
                "label": label,
                "a": before,
                "b": after,
                "change_pct": pct,
                "higher_is_better": higher_is_better,
            }
        )
    return rows


def _equipped(toolbox: PobToolbox) -> dict[str, str]:
    result = toolbox.call_internal("get_items", {})
    items = result.data.get("items", []) if isinstance(result.data, dict) else []
    return {i.get("slot", ""): i.get("name", "") for i in items if isinstance(i, dict)}


def check_item(toolbox: PobToolbox, item: Item) -> dict[str, Any]:
    """Try the item on the loaded build in every slot it fits; report the best one.

    The build is left exactly as it was (compare_changes restores it).
    """
    if not item.slots:
        kind = item.item_class or item.rarity
        raise ItemError(
            f"Trying {kind} items isn't supported; it works for gear "
            "(weapons, armour, jewellery, belts)."
        )
    equipped = _equipped(toolbox)
    best: tuple[float, str, dict[str, Any]] | None = None
    error = ""
    for slot in item.slots:
        edit = {"op": "equip_item", "slot": slot, "item_text": item.text}
        result = toolbox.call_internal(
            "compare_changes", {"edits": [edit], "extra_stats": [key for key, _, _ in STATS]}
        )
        if not result.ok or not isinstance(result.data, dict):
            error = result.text
            continue
        changes = result.data.get("changes", {})
        score = _score(changes)
        if best is None or score > best[0]:
            best = (score, slot, changes)
    if best is None:
        raise PobToolError(f"Path of Building couldn't equip the item: {error[:300]}")
    _, slot, changes = best
    return {
        "item": item.as_dict(),
        "slot": slot,
        "replaces": equipped.get(slot, ""),
        "rows": _rows(changes),
        "tried": list(item.slots),
    }

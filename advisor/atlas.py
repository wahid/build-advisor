"""The atlas_tree tool: read an atlas passive tree and plan it for a farm.

An atlas tree link (poeplanner.com/atlas-tree/... or pathofexile.com's
atlas-skill-tree/...) is decoded against GGG's atlas tree export
(advisor/data/atlastree.json.gz, written by `build_atlastree`). Every node
belongs to the mechanic of its cluster: the export puts one mastery node in each
cluster, and its name ("Essence", "Delirium", "Settlers of Kalguur") is the label.

For a farm (a few mechanics), the plan is counted in points, not guessed:

1. Keep every allocated node of the farmed mechanics and of map sustain ("Maps"),
   and drop allocated nodes that aren't needed to reach them (pruned from the
   leaves, so nothing kept moves).
2. Spend the freed and unspent points on the farmed mechanics' notables, then
   their small nodes, then map sustain, cheapest path first (breadth-first
   search from the kept tree, counting the travel nodes on the way).

Keystones are never added: they have drawbacks, so they're listed with their
path cost for the model to explain. How much a notable is worth isn't in the
data; the model explains that from the wiki and guides.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import json
import re
from collections import Counter, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent / "data" / "atlastree.json.gz"
TOOL_NAME = "atlas_tree"
SUSTAIN = "Maps"
CHOICE = "Content choice"  # notables that boost a content type the player picks
ROOT = 0  # the tree's start: not a node, costs nothing
MAX_KEYSTONES = 6
MAX_STATS_CHARS = 240

POEPLANNER = "poeplanner"
GGG = "ggg"
POEPLANNER_URL = "https://poeplanner.com/atlas-tree/"
URL_RE = re.compile(
    r"https?://(?:www\.)?(?:"
    r"poeplanner\.com/atlas-tree/"
    r"|pathofexile\.com/(?:fullscreen-)?atlas-skill-tree/(?:\d+\.\d+\.\d+[a-z]?/)?"
    r")([A-Za-z0-9_\-]+={0,2})"
)
# Questions that get the tool without a link ("best atlas tree for essence").
ATLAS_RE = re.compile(
    r"\batlas\b|\bpoeplanner\b|\bfarm(?:s|ed|ing)?\b|\bmap(?:ping)? strateg(?:y|ies)\b",
    re.IGNORECASE,
)
# What players call a mechanic -> the cluster's mastery name in the export.
ALIASES = {
    "harvest": "Sacred Flora",
    "kingsmarch": "Settlers of Kalguur",
    "settlers": "Settlers of Kalguur",
    "ore": "Settlers of Kalguur",
    "ore deposits": "Settlers of Kalguur",
    "lost shipments": "Settlers of Kalguur",
    "syndicate": "Betrayal",
    "jun": "Betrayal",
    "einhar": "Bestiary",
    "beasts": "Bestiary",
    "alva": "Incursion",
    "temple": "Incursion",
    "bosses": "Unique Monsters",
    "boss": "Unique Monsters",
    "map bosses": "Unique Monsters",
    "div cards": "Divination Cards",
    "divination": "Divination Cards",
    "exarch": "The Searing Exarch",
    "eater": "The Eater of Worlds",
    "eldritch": "The Searing Exarch,The Eater of Worlds",
    "shaper": "The Shaper and Elder",
    "elder": "The Shaper and Elder",
    "deli": "Delirium",
    "mercs": "Mercenaries",
    "sustain": SUSTAIN,
    "map sustain": SUSTAIN,
    "memories": "Atlas Memories",
    "anomalies": "Atlas Anomalies",
    "wildwood": "Viridian Wildwood",
}

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Read an atlas passive tree and plan it for a farm. With a link "
            "(poeplanner.com/atlas-tree or pathofexile.com atlas-skill-tree) it lists the "
            "points spent per mechanic, the notables and keystones taken and the unspent "
            "points. With farm (the mechanics to farm) it also counts which allocated nodes "
            "don't help that farm and where those points go instead, cheapest path first, "
            "and makes a new tree link (the app shows it). Without a link it plans a tree "
            "from scratch for the farm. It counts points, not value: explain from the "
            "sources why the picks matter. Use it for atlas tree, atlas strategy and "
            "'what should I farm' questions. If an atlas link is in the conversation, it is "
            "used when url is left out."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Atlas tree link. Leave out to plan from scratch.",
                },
                "farm": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Mechanics to farm, e.g. ['Essence', 'Delirium']. Names as on the "
                        "atlas: Essence, Delirium, Breach, Legion, Expedition, Ritual, "
                        "Harvest, Blight, Shrines, Strongboxes, Settlers of Kalguur, "
                        "Abyss, Beyond, Torment, Rogue Exiles, Bestiary, Betrayal, "
                        "Incursion, Ultimatum, The Searing Exarch, The Eater of Worlds, "
                        "Unique Monsters (map bosses), Divination Cards and more. Map "
                        "sustain is always kept."
                    ),
                },
                "keep": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "More mechanics to keep as they are, without spending extra points on them."
                    ),
                },
            },
        },
    },
}


class AtlasError(ValueError):
    """A link that can't be read, or a farm that isn't on the atlas."""


@dataclass(frozen=True)
class Node:
    id: int
    name: str
    stats: tuple[str, ...]
    kind: str  # notable, keystone, small or gateway
    mechanic: str  # "" for travel nodes outside a cluster
    choices: tuple[tuple[str, ...], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        stats = "; ".join(self.stats)
        if self.choices:
            options = " / ".join("; ".join(choice) for choice in self.choices)
            stats = f"{stats} (choose one: {options})" if stats else f"choose one: {options}"
        return {
            "name": self.name,
            "kind": self.kind,
            "mechanic": self.mechanic or "travel",
            "stats": stats[:MAX_STATS_CHARS],
        }


@dataclass
class Tree:
    version: str
    points: int
    nodes: dict[int, Node]
    adjacent: dict[int, set[int]] = field(default_factory=dict)

    @property
    def mechanics(self) -> list[str]:
        return sorted({n.mechanic for n in self.nodes.values() if n.mechanic})

    @property
    def minor_version(self) -> int:
        match = re.match(r"\d+\.(\d+)", self.version)
        return int(match.group(1)) if match else 0


@dataclass(frozen=True)
class Link:
    """A decoded tree link: its nodes, and the bytes around them to write it back."""

    nodes: tuple[int, ...]
    layout: str
    head: bytes = b""
    tail: bytes = b""

    @property
    def link_minor_version(self) -> int | None:
        """poeplanner stores the league's minor version (30 for 3.30) after its format."""
        if self.layout == POEPLANNER and len(self.head) >= 4:
            return int.from_bytes(self.head[2:4], "little")
        return None


# --- data -----------------------------------------------------------------------------


def trim_export(export: dict[str, Any], version: str) -> dict[str, Any]:
    """GGG's atlas tree export -> what this tool needs (about a tenth of the size)."""
    raw: dict[str, dict[str, Any]] = export["nodes"]
    # The start is "root" and the nameless hub after it: both are free, so both are ROOT.
    start = {"root"} | {
        key for key in raw.get("root", {}).get("out", []) if not raw.get(key, {}).get("name")
    }
    mastery_of_group = {
        node["group"]: node["name"] for node in raw.values() if node.get("isMastery")
    }
    # A notable outside a mastery's cluster still belongs to a mechanic: the one whose
    # nodes use the same icon ("EssenceNode2.png" -> Essence).
    icon_votes: dict[str, Counter[str]] = {}
    for node in raw.values():
        mechanic = mastery_of_group.get(node.get("group"))
        if mechanic and not node.get("isMastery") and node.get("icon"):
            icon_votes.setdefault(_icon_stem(node["icon"]), Counter())[mechanic] += 1
    nodes: dict[str, Any] = {}
    gateways: dict[str, list[str]] = {}
    for key, node in raw.items():
        if key in start or node.get("isMastery") or not node.get("name"):
            continue
        kind = (
            "keystone"
            if node.get("isKeystone")
            else "notable"
            if node.get("isNotable")
            else "gateway"
            if node.get("isWormhole")
            else "small"
        )
        mechanic = mastery_of_group.get(node.get("group"), "")
        if not mechanic and kind in ("notable", "keystone"):
            votes = icon_votes.get(_icon_stem(node.get("icon", "")))
            if votes:
                mechanic = votes.most_common(1)[0][0]
            elif node.get("isMultipleChoiceVariant"):
                mechanic = CHOICE
        entry: dict[str, Any] = {
            "name": node["name"],
            "stats": [str(s).replace("\n", " ") for s in node.get("stats", [])],
            "kind": kind,
            "mechanic": mechanic,
        }
        choices = [
            [str(s).replace("\n", " ") for s in v.get("stats", [])]
            for v in node.get("variantEffects", [])
        ]
        if choices:
            entry["choices"] = choices
        nodes[key] = entry
        if kind == "gateway":
            gateways.setdefault(node["name"], []).append(key)
    edges: set[tuple[int, int]] = set()
    for key, node in raw.items():
        here = ROOT if key in start else int(key)
        if key not in start and key not in nodes:
            continue
        for other in [*node.get("out", []), *node.get("in", [])]:
            there = ROOT if other in start else int(other)
            if (other not in start and other not in nodes) or here == there:
                continue
            edges.add((min(here, there), max(here, there)))
    # Gateways of the same name are linked through the map (a wormhole).
    for pair in gateways.values():
        for a, b in zip(pair, pair[1:], strict=False):
            edges.add((min(int(a), int(b)), max(int(a), int(b))))
    if not nodes or not edges:
        raise ValueError("no nodes or links")
    return {
        "version": version,
        "points": int(export.get("points", {}).get("totalPoints") or 0),
        "nodes": nodes,
        "edges": sorted(edges),
    }


def _icon_stem(icon: str) -> str:
    """'Art/.../EssenceNode2.png' -> 'essencenode'."""
    return re.sub(r"\d+$", "", Path(icon).stem).lower()


def tree_from_data(data: dict[str, Any]) -> Tree:
    nodes = {
        int(key): Node(
            id=int(key),
            name=value["name"],
            stats=tuple(value.get("stats", [])),
            kind=value["kind"],
            mechanic=value.get("mechanic", ""),
            choices=tuple(tuple(c) for c in value.get("choices", [])),
        )
        for key, value in data["nodes"].items()
    }
    tree = Tree(version=data["version"], points=data["points"], nodes=nodes)
    tree.adjacent = {ROOT: set(), **{n: set() for n in nodes}}
    for a, b in data["edges"]:
        tree.adjacent[a].add(b)
        tree.adjacent[b].add(a)
    return tree


@lru_cache(maxsize=1)
def load(path: Path = DATA) -> Tree:
    if not path.is_file():
        raise AtlasError("The atlas tree data isn't installed (run build_atlastree).")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return tree_from_data(json.load(handle))


# --- links ----------------------------------------------------------------------------


def urls_in(text: str) -> list[str]:
    return [match.group(0) for match in URL_RE.finditer(text)]


def strip_urls(text: str) -> str:
    """The question without its atlas links: their codes mean nothing to a search."""
    return URL_RE.sub("(atlas tree link)", text)


def _decode_bytes(code: str) -> bytes:
    code = code.strip().rstrip("=")
    try:
        return base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
    except (binascii.Error, ValueError) as exc:
        raise AtlasError("That atlas tree link is damaged: it isn't valid base64.") from exc


def _candidates(data: bytes) -> Iterable[Link]:
    # poeplanner: u16 format, u16 league minor version, a byte, u16 node count, u16 ids
    # (little-endian), then the rest (choices) kept as it is.
    if len(data) >= 7:
        count = int.from_bytes(data[5:7], "little")
        end = 7 + 2 * count
        if count > 0 and end <= len(data):
            ids = tuple(int.from_bytes(data[i : i + 2], "little") for i in range(7, end, 2))
            yield Link(ids, POEPLANNER, data[:5], data[end:])
    # pathofexile.com: u32 version, class, ascendancy, u8 node count, u16 ids (big-endian).
    if len(data) >= 7 and 0 < int.from_bytes(data[:4], "big") < 16:
        count = data[6]
        end = 7 + 2 * count
        if count > 0 and end <= len(data):
            ids = tuple(int.from_bytes(data[i : i + 2], "big") for i in range(7, end, 2))
            yield Link(ids, GGG, data[:6], data[end:])


def decode(url: str, tree: Tree | None = None) -> Link:
    """A tree link -> its allocated nodes. Only a reading where every id is a node counts."""
    tree = tree or load()
    match = URL_RE.search(url)
    code = match.group(1) if match else url
    for link in _candidates(_decode_bytes(code)):
        if all(node in tree.nodes for node in link.nodes):
            return link
    raise AtlasError(
        "That atlas tree link couldn't be read: its nodes aren't on the current atlas tree "
        f"({tree.version}). Links from poeplanner.com and pathofexile.com work."
    )


def encode(nodes: Iterable[int], tree: Tree, like: Link | None = None) -> str:
    """A poeplanner link for these nodes, keeping the rest of `like` (a poeplanner link)."""
    wanted = set(nodes) - {ROOT}
    before = [n for n in like.nodes if n in wanted] if like is not None else []
    ids = before + sorted(wanted - set(before))
    if like is not None and like.layout == POEPLANNER:
        head, tail = like.head, like.tail
    else:
        # A new link: format 5, this league, no choices picked (an empty gzip block).
        head = (5).to_bytes(2, "little") + tree.minor_version.to_bytes(2, "little") + b"\0"
        tail = b"\0\0" + gzip.compress(b"", mtime=0)
    body = len(ids).to_bytes(2, "little") + b"".join(i.to_bytes(2, "little") for i in ids)
    code = base64.urlsafe_b64encode(head + body + tail).decode()
    return POEPLANNER_URL + code


# --- farms ----------------------------------------------------------------------------


def resolve_mechanics(names: Sequence[str], tree: Tree) -> tuple[list[str], list[str]]:
    """Farm names as players write them -> mastery names; and the ones not found."""
    known = {m.lower(): m for m in tree.mechanics}
    short = {m.lower().removeprefix("the "): m for m in tree.mechanics}
    found: list[str] = []
    unknown: list[str] = []
    for raw in names:
        name = re.sub(r"\s+", " ", str(raw)).strip().lower()
        if not name:
            continue
        targets = ALIASES.get(name) or ALIASES.get(name.rstrip("s")) or ""
        hits = [t for t in targets.split(",") if t in tree.mechanics] if targets else []
        if not hits:
            for candidate in (name, name.rstrip("s"), name + "s", name.removeprefix("the ")):
                hit = known.get(candidate) or short.get(candidate)
                if hit:
                    hits = [hit]
                    break
        if not hits:
            hits = [m for m in tree.mechanics if name in m.lower()][:1]
        if hits:
            found.extend(h for h in hits if h not in found)
        else:
            unknown.append(str(raw))
    return found, unknown


# --- analysis -------------------------------------------------------------------------


def _connected(allocated: set[int], tree: Tree) -> set[int]:
    """The allocated nodes reachable from the start through allocated nodes."""
    seen = {ROOT}
    queue = deque([ROOT])
    while queue:
        here = queue.popleft()
        for there in tree.adjacent.get(here, ()):
            if there in allocated and there not in seen:
                seen.add(there)
                queue.append(there)
    return seen - {ROOT}


def breakdown(allocated: set[int], tree: Tree) -> dict[str, Any]:
    points: Counter[str] = Counter()
    notables: dict[str, list[str]] = {}
    for node_id in sorted(allocated):
        node = tree.nodes[node_id]
        mechanic = node.mechanic or "travel"
        points[mechanic] += 1
        if node.kind == "notable":
            notables.setdefault(mechanic, []).append(node.name)
    rows = [
        {"mechanic": mechanic, "points": count, "notables": notables.get(mechanic, [])}
        for mechanic, count in points.most_common()
    ]
    focus = [
        row["mechanic"]
        for row in rows
        if row["mechanic"] not in (SUSTAIN, CHOICE, "travel") and len(row["notables"]) >= 2
    ]
    return {"mechanics": rows, "focus": focus}


def _prune(allocated: set[int], required: set[int], tree: Tree) -> set[int]:
    """Drop allocated leaves that aren't required, until none is left: what remains is
    the required nodes and the paths to them, as they are now."""
    kept = set(allocated)
    changed = True
    while changed:
        changed = False
        for node in sorted(kept - required):
            links = sum(1 for n in tree.adjacent[node] if n in kept or n == ROOT)
            if links <= 1:
                kept.discard(node)
                changed = True
    return kept


def _paths(kept: set[int], tree: Tree) -> tuple[dict[int, int], dict[int, int]]:
    """Breadth-first search from the kept tree: the cost (unallocated nodes, the target
    included) to reach each node, and the step before it."""
    cost: dict[int, int] = {n: 0 for n in kept | {ROOT}}
    parent: dict[int, int] = {}
    queue = deque(sorted(kept | {ROOT}))
    while queue:
        here = queue.popleft()
        for there in sorted(tree.adjacent.get(here, ())):
            if there not in cost:
                cost[there] = cost[here] + 1
                parent[there] = here
                queue.append(there)
    return cost, parent


def _tier(node: Node, farm: set[str]) -> int | None:
    """Which nodes points go to first; None: never added by the plan."""
    if node.kind in ("keystone", "gateway"):
        return None
    if node.mechanic in farm:
        return 0 if node.kind == "notable" else 1
    if node.mechanic == SUSTAIN:
        return 2 if node.kind == "notable" else 3
    return None


def plan(
    allocated: set[int], farm: list[str], keep: list[str], tree: Tree
) -> tuple[set[int], dict[str, Any]]:
    """The new allocation for this farm, and what changed."""
    kept_mechanics = {*farm, *keep, SUSTAIN, CHOICE}
    required = {n for n in allocated if tree.nodes[n].mechanic in kept_mechanics}
    kept = _prune(allocated, required, tree)
    removed = sorted(allocated - kept)
    budget = max(tree.points - len(kept), 0)
    farm_set = set(farm)
    added: list[dict[str, Any]] = []
    while budget > 0:
        cost, parent = _paths(kept, tree)
        best: tuple[int, int, int] | None = None  # (tier, cost, node)
        for node_id, steps in cost.items():
            if node_id == ROOT or steps == 0 or steps > budget:
                continue
            tier = _tier(tree.nodes[node_id], farm_set)
            if tier is not None and (best is None or (tier, steps, node_id) < best):
                best = (tier, steps, node_id)
        if best is None:
            break
        _, steps, target = best
        path = [target]
        while parent.get(path[-1], ROOT) not in kept | {ROOT}:
            path.append(parent[path[-1]])
        kept.update(path)
        budget -= steps
        node = tree.nodes[target]
        if node.kind == "notable":
            added.append({**node.as_dict(), "cost": steps})
        elif added and added[-1].get("small_nodes") is not None:
            added[-1]["small_nodes"] += steps
        else:
            added.append({"name": f"{node.mechanic} small nodes", "small_nodes": steps})
    cost, _ = _paths(kept, tree)
    keystones = sorted(
        (
            {**tree.nodes[n].as_dict(), "cost": c}
            for n, c in cost.items()
            if n != ROOT and c > 0 and tree.nodes[n].kind == "keystone"
        ),
        key=lambda row: row["cost"],
    )[:MAX_KEYSTONES]
    return kept, {
        "farm": farm,
        "kept_mechanics": sorted(kept_mechanics),
        "remove": _grouped(removed, tree),
        "points_freed": len(removed),
        "add": added,
        "points_after": len(kept),
        # Left when the farm and map sustain have nothing more in reach.
        "points_left": max(tree.points - len(kept), 0),
        "keystones_in_reach": keystones,
    }


def _grouped(node_ids: Iterable[int], tree: Tree) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for node_id in node_ids:
        node = tree.nodes[node_id]
        mechanic = node.mechanic or "travel"
        group = groups.setdefault(mechanic, {"mechanic": mechanic, "points": 0, "notables": []})
        group["points"] += 1
        if node.kind in ("notable", "keystone"):
            group["notables"].append(node.name)
    return sorted(groups.values(), key=lambda g: -g["points"])


def analyse(
    url: str = "",
    farm: Sequence[str] = (),
    keep: Sequence[str] = (),
    tree: Tree | None = None,
) -> dict[str, Any]:
    tree = tree or load()
    link = decode(url, tree) if url else None
    allocated = set(link.nodes) if link else set()
    reached = _connected(allocated, tree)
    result: dict[str, Any] = {
        "tree_version": tree.version,
        "points_total": tree.points,
        "points_used": len(allocated),
        "points_unspent": max(tree.points - len(allocated), 0),
    }
    notes: list[str] = []
    if link is not None:
        minor = link.link_minor_version
        if minor and tree.minor_version and minor != tree.minor_version:
            notes.append(
                f"The link was made for 3.{minor}; the atlas tree here is {tree.version}, "
                "so nodes may have moved or changed."
            )
        if len(reached) < len(allocated):
            notes.append(
                f"{len(allocated) - len(reached)} allocated nodes aren't connected to the "
                "start; they were left out of the plan."
            )
            allocated = reached
        result.update(breakdown(allocated, tree))
        result["keystones"] = [
            tree.nodes[n].as_dict() for n in sorted(allocated) if tree.nodes[n].kind == "keystone"
        ]
        choices = [tree.nodes[n].name for n in sorted(allocated) if tree.nodes[n].choices]
        if choices:
            notes.append(
                "Choice nodes allocated (the option picked isn't read from the link): "
                + ", ".join(choices)
            )
    farm_names, unknown = resolve_mechanics(farm, tree)
    keep_names, unknown_keep = resolve_mechanics(keep, tree)
    if unknown or unknown_keep:
        raise AtlasError(
            f"Not an atlas mechanic: {', '.join([*unknown, *unknown_keep])}. "
            f"The atlas has: {', '.join(tree.mechanics)}."
        )
    if farm_names:
        new, changes = plan(allocated, farm_names, keep_names, tree)
        result["plan"] = changes
        result["link"] = encode(new, tree, link)
    elif link is None:
        raise AtlasError("Give an atlas tree link, or the mechanics to farm to plan a tree.")
    if notes:
        result["notes"] = notes
    return result


def run(arguments: dict[str, Any], linked: Sequence[str] = ()) -> dict[str, Any]:
    """The tool call. linked: atlas links in the conversation, newest last."""
    url = str(arguments.get("url") or "").strip()
    if not url and linked:
        url = linked[-1]
    farm = arguments.get("farm") or []
    keep = arguments.get("keep") or []
    if isinstance(farm, str):
        farm = [farm]
    if isinstance(keep, str):
        keep = [keep]
    return analyse(url, [str(f) for f in farm], [str(k) for k in keep])


def for_model(result: dict[str, Any]) -> str:
    """The result without the link (the app shows it), as JSON."""
    shown = {k: v for k, v in result.items() if k != "link"}
    if "link" in result:
        shown["link"] = "The app shows the new tree's poeplanner link below your answer."
    return json.dumps(shown, ensure_ascii=False)

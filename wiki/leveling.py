"""Where gems come from while leveling: quest rewards, vendors, and required levels.

The wiki keeps quest rewards and the gems vendors sell after each quest in Cargo
tables (quest_rewards, vendor_rewards), stored on the reward's own page, and each
gem's required level in the items table. `update` copies them into the database;
the data ships as wiki/fixtures/leveling.json.gz for servers without wiki access.
"""

from __future__ import annotations

import gzip
import html
import json
from pathlib import Path
from typing import Any

from django.db import transaction

from .client import CARGO_PAGE_SIZE, WikiClient
from .models import GemLevel, QuestReward

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "leveling.json.gz"
SUPPORT_SUFFIX = " Support"
MAX_GEMS = 20


def _rows(client: WikiClient, **query: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    offset = 0
    while True:
        page = client._cargo(**query, limit=CARGO_PAGE_SIZE, offset=offset)
        rows.extend(page)
        if len(page) < CARGO_PAGE_SIZE:
            return rows
        offset += CARGO_PAGE_SIZE


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _classes(value: Any) -> list[str]:
    return [c.strip() for c in str(value or "").split(",") if c.strip()]


def fetch(client: WikiClient) -> dict[str, list[dict[str, Any]]]:
    """Read the three tables from the wiki into plain rows."""
    rewards = []
    quest_fields = "_pageName=reward,quest,act,classes"
    for row in _rows(client, tables="quest_rewards", fields=quest_fields):
        rewards.append(
            {
                "reward": html.unescape(row["reward"]),
                "kind": QuestReward.Kind.QUEST,
                "quest": html.unescape(row.get("quest") or ""),
                "act": _int(row.get("act")),
                "classes": _classes(row.get("classes")),
                "npc": "",
            }
        )
    vendor_fields = "_pageName=reward,quest,act,classes,npc"
    for row in _rows(client, tables="vendor_rewards", fields=vendor_fields):
        rewards.append(
            {
                "reward": html.unescape(row["reward"]),
                "kind": QuestReward.Kind.VENDOR,
                "quest": html.unescape(row.get("quest") or ""),
                "act": _int(row.get("act")),
                "classes": _classes(row.get("classes")),
                "npc": html.unescape(row.get("npc") or ""),
            }
        )
    gems = []
    gem_rows = _rows(
        client,
        tables="items",
        fields="name,required_level,class_id",
        where='class_id IN ("Active Skill Gem","Support Skill Gem")',
    )
    seen = set()
    for row in gem_rows:
        name, level = html.unescape(row.get("name") or ""), _int(row.get("required level"))
        if name and level is not None and name not in seen:
            seen.add(name)
            gems.append(
                {
                    "name": name,
                    "required_level": level,
                    "support": row.get("class id") == "Support Skill Gem",
                }
            )
    return {"rewards": rewards, "gems": gems}


@transaction.atomic
def store(data: dict[str, list[dict[str, Any]]]) -> tuple[int, int]:
    """Replace the stored rewards and gem levels; returns (rewards, gems)."""
    if not data.get("rewards") or not data.get("gems"):
        raise ValueError("Leveling data is empty; keeping what's stored.")
    QuestReward.objects.all().delete()
    QuestReward.objects.bulk_create(QuestReward(**row) for row in data["rewards"])
    GemLevel.objects.all().delete()
    GemLevel.objects.bulk_create(GemLevel(**row) for row in data["gems"])
    return len(data["rewards"]), len(data["gems"])


def update(client: WikiClient) -> tuple[int, int]:
    return store(fetch(client))


def export(path: Path = FIXTURE) -> None:
    data = {
        "rewards": list(
            QuestReward.objects.order_by("reward", "kind", "act", "id").values(
                "reward", "kind", "quest", "act", "classes", "npc"
            )
        ),
        "gems": list(GemLevel.objects.order_by("name").values("name", "required_level", "support")),
    }
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)


def load(path: Path = FIXTURE) -> dict[str, list[dict[str, Any]]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _for_class(row: QuestReward, class_name: str) -> bool:
    return not class_name or not row.classes or class_name in row.classes


def lookup(gems: list[str], class_name: str = "") -> list[dict[str, Any]]:
    """For each gem: its level, the first quest that rewards it to this class, and
    where it can be bought (earliest first). Unknown names are reported as such."""
    names = list(dict.fromkeys(g.strip() for g in gems if g and g.strip()))[:MAX_GEMS]
    wanted = {}
    for name in names:
        # "Brutality" and "Brutality Support" both mean the support gem.
        wanted[name] = [name, f"{name}{SUPPORT_SUFFIX}", name.removesuffix(SUPPORT_SUFFIX)]
    all_names = {n for options in wanted.values() for n in options}
    levels = {g.name: g for g in GemLevel.objects.filter(name__in=all_names)}
    rewards: dict[str, list[QuestReward]] = {}
    for row in QuestReward.objects.filter(reward__in=all_names):
        rewards.setdefault(row.reward, []).append(row)

    out = []
    for name in names:
        title = next((n for n in wanted[name] if n in levels or n in rewards), name)
        rows = [r for r in rewards.get(title, []) if _for_class(r, class_name)]
        quests = [r for r in rows if r.kind == QuestReward.Kind.QUEST]
        vendors = [r for r in rows if r.kind == QuestReward.Kind.VENDOR]
        level = levels.get(title)
        out.append(
            {
                "gem": title,
                "known": title in levels or title in rewards,
                "required_level": level.required_level if level else None,
                "quest_reward": (
                    {"act": quests[0].act, "quest": quests[0].quest} if quests else None
                ),
                "vendors": [
                    {"act": v.act, "npc": v.npc, "after_quest": v.quest} for v in vendors[:3]
                ],
            }
        )
    out.sort(key=lambda g: (_first_act(g), g["required_level"] or 0))
    return out


def _first_act(gem: dict[str, Any]) -> int:
    acts = [gem["quest_reward"]["act"]] if gem["quest_reward"] else []
    acts += [v["act"] for v in gem["vendors"] if v["act"]]
    return min((a for a in acts if a), default=99)

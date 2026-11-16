"""Check simple game facts in an answer against Path of Building's data.

The number guardrail catches figures that came from nowhere; this catches a few
kinds of wrong statements about things that have a definite answer:

- a weapon base called one-handed when it is two-handed, or the reverse;
- a skill gem called an attack when it is a spell, or the reverse;
- a gem's required level stated wrongly.

The facts come from Path of Building (item bases and gem tags, saved to
advisor/data/gamefacts.json.gz by `build_gamefacts`) and the wiki's gem levels.
It is pattern matching on sentences, deliberately narrow: it only speaks up when
a sentence makes one of these claims plainly, and stays silent when unsure
(comparisons, negations, several weapons in one sentence).
"""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent / "data" / "gamefacts.json.gz"
TWO_HANDED_TYPES = {"Two Handed Axe", "Two Handed Mace", "Two Handed Sword", "Staff", "Bow"}
ONE_HANDED_TYPES = {
    "One Handed Axe",
    "One Handed Mace",
    "One Handed Sword",
    "Claw",
    "Dagger",
    "Wand",
    "Sceptre",
}
ONE_RE = re.compile(r"\b(?:one|1)[- ]?hand(?:ed|er)?\b|\b1h\b", re.IGNORECASE)
TWO_RE = re.compile(r"\b(?:two|2)[- ]?hand(?:ed|er)?\b|\b2h\b", re.IGNORECASE)
# Sentences that compare or negate: too easy to misread, so they're skipped.
HEDGE_RE = re.compile(
    r"\bnot\b|n't\b|\binstead\b|\brather than\b|\bunlike\b|\bversus\b|\bvs\b|\bor\b|\bif\b|\?",
    re.IGNORECASE,
)
SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")
KIND_CLAIM = r"\s+is\s+an?\s+(?:\w+\s+){{0,2}}?(attack|spell)\b"
LEVEL_CLAIM = r"\s+(?:requires?|needs?|is available at|unlocks at)\s+(?:character\s+)?level\s+(\d+)"
MIN_NAME = 5


@dataclass(frozen=True)
class WrongFact:
    text: str  # the thing the claim is about, as written
    context: str  # the sentence
    fact: str  # what the data says


@lru_cache(maxsize=1)
def load(path: Path = DATA) -> dict[str, Any]:
    if not path.is_file():
        return {"weapons": {}, "gems": {}}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _names_in(sentence: str, names: list[str]) -> list[str]:
    found = []
    for name in names:
        if name in sentence and re.search(rf"(?<![\w']){re.escape(name)}(?![\w'])", sentence):
            found.append(name)
    # "Vaal Axe" inside "Despot Vaal Axe"-like longer names: keep the longest.
    return [n for n in found if not any(n != other and n in other for other in found)]


def _handedness(sentence: str, weapons: dict[str, str]) -> WrongFact | None:
    says_one, says_two = bool(ONE_RE.search(sentence)), bool(TWO_RE.search(sentence))
    if says_one == says_two or HEDGE_RE.search(sentence):
        return None
    names = _names_in(sentence, [n for n in weapons if len(n) >= MIN_NAME])
    if len(names) != 1:
        return None
    kind = weapons[names[0]]
    if says_one and kind in TWO_HANDED_TYPES:
        hands = "two-handed"
    elif says_two and kind in ONE_HANDED_TYPES:
        hands = "one-handed"
    else:
        return None
    label = kind.lower().replace(" handed", "-handed")
    fact = f"{names[0]} is a {label}" + ("." if "handed" in label else f", which is {hands}.")
    return WrongFact(names[0], sentence.strip(), fact)


def _gem_kind(sentence: str, gems: dict[str, dict[str, Any]]) -> list[WrongFact]:
    if HEDGE_RE.search(sentence):
        return []
    wrong = []
    for name in _names_in(sentence, [n for n in gems if len(n) >= MIN_NAME]):
        match = re.search(re.escape(name) + KIND_CLAIM.format(), sentence, re.IGNORECASE)
        if not match:
            continue
        claimed = match.group(1).lower()
        tags = {t.strip().lower() for t in str(gems[name].get("tags", "")).split(",")}
        other = "spell" if claimed == "attack" else "attack"
        if claimed not in tags and other in tags:
            wrong.append(
                WrongFact(
                    name, sentence.strip(), f"{name} is tagged {other.title()}, not {claimed}."
                )
            )
    return wrong


def _gem_level(sentence: str, levels: dict[str, int]) -> list[WrongFact]:
    wrong = []
    for name in _names_in(sentence, [n for n in levels if len(n) >= MIN_NAME]):
        match = re.search(re.escape(name) + LEVEL_CLAIM, sentence, re.IGNORECASE)
        if match and int(match.group(1)) != levels[name]:
            wrong.append(
                WrongFact(
                    name,
                    sentence.strip(),
                    f"{name} requires level {levels[name]}, not {match.group(1)}.",
                )
            )
    return wrong


def gem_levels() -> dict[str, int]:
    from wiki.models import GemLevel

    return dict(GemLevel.objects.values_list("name", "required_level"))


def check(
    answer: str, facts: dict[str, Any] | None = None, levels: dict[str, int] | None = None
) -> dict[str, Any]:
    """Wrong statements found in the answer: {"wrong": [{text, context, fact}]}."""
    facts = load() if facts is None else facts
    levels = gem_levels() if levels is None else levels
    wrong: list[WrongFact] = []
    for match in SENTENCE_RE.finditer(answer):
        sentence = match.group(0)
        if len(sentence) < 12:
            continue
        hand = _handedness(sentence, facts.get("weapons", {}))
        wrong += [hand] if hand else []
        wrong += _gem_kind(sentence, facts.get("gems", {}))
        wrong += _gem_level(sentence, levels)
    unique = list({(w.text, w.fact): w for w in wrong}.values())
    return {"wrong": [asdict(w) for w in unique[:10]]}

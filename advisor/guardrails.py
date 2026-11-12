"""Check the numbers in an answer against what the model was given.

LLMs are most convincing, and most often wrong, with numbers. After an answer is
written, every number in it is looked up in the evidence: the wiki sources, web
results and tool results (Path of Building's calculations, the leveling tables)
the model saw, plus the user's own question, pasted item and earlier questions.
A number that appears nowhere, even after rounding, is flagged so the app can mark
it. Numbers in sentences labelled "(general game knowledge)" aren't expected to be
in the sources; they're counted apart, not flagged.

This is deliberately simple string-and-number matching, not a model: it can't
tell whether a found number is used correctly, but it reliably catches figures
that came from nowhere.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass

# 1,234.5 / 12.5 / 40 with an optional k, M or % right after it ("0.4 m" is metres).
# Ranges ("20-44%") yield two numbers.
NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?P<suffix>[kK]\b|M\b|%)?"
)
CITATION_RE = re.compile(r"\[\d+(?:\s*[,\-–]\s*\d+)*\]")
VERSION_RE = re.compile(r"\b\d+\.\d+\.\d+[a-z]?\b")  # patch 3.29.3c
LIST_MARKER_RE = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
KNOWLEDGE = "general game knowledge"
SMALL = 10  # bare whole numbers below this ("2 sockets", "act 3") aren't checked
CONTEXT_CHARS = 40


@dataclass(frozen=True)
class Claim:
    text: str  # as written, e.g. "45%"
    value: float
    decimals: int
    scaled: bool  # written with k/M: compare loosely
    start: int


@dataclass
class NumberCheck:
    checked: int
    unsupported: list[dict[str, str]]
    knowledge: int  # numbers in general-knowledge sentences, not checked

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _value(raw: str, suffix: str) -> tuple[float, int, bool]:
    digits = raw.replace(",", "")
    decimals = len(digits.split(".", 1)[1]) if "." in digits else 0
    value = float(digits)
    if suffix in ("k", "K"):
        return value * 1_000, decimals, True
    if suffix == "M":
        return value * 1_000_000, decimals, True
    return value, decimals, False


def _blank(text: str, pattern: re.Pattern[str]) -> str:
    return pattern.sub(lambda m: " " * len(m.group(0)), text)


def claims(text: str) -> list[Claim]:
    """The numbers in an answer worth checking."""
    cleaned = _blank(_blank(_blank(text, CITATION_RE), VERSION_RE), LIST_MARKER_RE)
    found = []
    for match in NUMBER_RE.finditer(cleaned):
        raw, suffix = match.group("num"), match.group("suffix") or ""
        value, decimals, scaled = _value(raw, suffix)
        if suffix != "%" and not scaled and decimals == 0 and value < SMALL:
            continue
        if decimals == 0 and not suffix and 1990 <= value <= 2100:
            continue  # a year
        found.append(Claim(match.group(0).strip(), value, decimals, scaled, match.start()))
    return found


def evidence_numbers(texts: list[str]) -> set[float]:
    """Every number in the evidence, also as a fraction or percentage of itself
    (the wiki's "60% less" is the answer's "x 0.4" or "0.6 of it")."""
    numbers = set()
    for text in texts:
        for match in NUMBER_RE.finditer(text):
            value, decimals, _ = _value(match.group("num"), match.group("suffix") or "")
            forms = {value}
            if match.group("suffix") == "%":
                forms |= {value / 100, 1 - value / 100, 1 + value / 100}
            elif decimals and value < 10:
                forms.add(value * 100)
            numbers |= forms | {-f for f in forms}
    return numbers


def _supported(claim: Claim, numbers: set[float]) -> bool:
    for known in numbers:
        if claim.scaled:
            if known and math.isclose(claim.value, known, rel_tol=0.05):
                return True
        elif abs(known - claim.value) <= 0.5 * 10**-claim.decimals + 1e-9 or (
            claim.decimals == 0 and math.floor(known) == claim.value
        ):
            return True  # the same number, rounded (or cut) to the digits written
    return False


def _in_knowledge_sentence(text: str, start: int) -> bool:
    """Whether the number is in a sentence (or list item) labelled general game knowledge."""
    left = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    ends = [i for i in (text.find(". ", start), text.find("\n", start)) if i != -1]
    right = min(ends) if ends else len(text)
    return KNOWLEDGE in text[left + 1 : right + 1].lower()


def _sentence(text: str, start: int) -> tuple[int, int]:
    left = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start)) + 1
    ends = [i for i in (text.find(". ", start), text.find("\n", start)) if i != -1]
    return left, min(ends) if ends else len(text)


def _derived(claim: Claim, sentence: str, numbers: set[float]) -> bool:
    """Arithmetic the answer shows: a sum, difference, product or ratio of two
    supported numbers in the same sentence ("1229 -> 1294 (+65)", "3 x 0.6 = 1.8").
    Small whole numbers (counts) may be operands without a source."""
    values = []
    for match in NUMBER_RE.finditer(sentence):
        value, decimals, scaled = _value(match.group("num"), match.group("suffix") or "")
        operand = Claim(match.group(0), value, decimals, scaled, 0)
        if value == claim.value and match.group(0).strip() == claim.text:
            continue
        if (decimals == 0 and value < SMALL) or _supported(operand, numbers):
            values.append(value)
    results = set()
    for i, a in enumerate(values):
        for b in values[i + 1 :]:
            results |= {a + b, abs(a - b), a * b}
            if a and b:
                results |= {a / b, b / a}
    return _supported(claim, results)


def check(answer: str, evidence: list[str]) -> NumberCheck:
    numbers = evidence_numbers(evidence)
    result = NumberCheck(checked=0, unsupported=[], knowledge=0)
    seen: set[str] = set()
    found = claims(answer)
    for claim in found:
        if _in_knowledge_sentence(answer, claim.start):
            result.knowledge += 1
            continue
        result.checked += 1
        if _supported(claim, numbers) or claim.text in seen:
            continue
        left, right = _sentence(answer, claim.start)
        if _derived(claim, _blank(answer[left:right], CITATION_RE), numbers):
            continue
        seen.add(claim.text)
        left = max(0, claim.start - CONTEXT_CHARS)
        context = answer[left : claim.start + len(claim.text) + CONTEXT_CHARS]
        result.unsupported.append({"text": claim.text, "context": " ".join(context.split())})
    return result

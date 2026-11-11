"""Split documents into section-based chunks.

`parsing.html_to_text` marks headings with `##`/`###`. Each section becomes
one chunk; long sections are split on paragraph boundaries so chunks stay
under `max_chars`. Every chunk starts with "<title> — <section path>" so the
embedding knows what page and section it came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{2,6}) (.+)$")

# Sections that add noise rather than answers.
SKIP_SECTIONS = {"references", "see also", "navigation", "external links", "gallery"}
MIN_CHARS = 40


@dataclass(frozen=True)
class ChunkData:
    position: int
    section: str
    text: str


@dataclass
class _Section:
    path: list[str]
    lines: list[str]


def chunk_text(title: str, text: str, max_chars: int = 1500) -> list[ChunkData]:
    chunks: list[ChunkData] = []
    for section in _sections(text):
        if section.path and section.path[0].lower() in SKIP_SECTIONS:
            continue
        body = "\n".join(section.lines).strip()
        if len(body) < MIN_CHARS:
            continue
        label = " > ".join(section.path)
        header = f"{title} — {label}" if label else title
        budget = max(max_chars - len(header) - 2, 200)
        for piece in _split(body, budget):
            chunks.append(ChunkData(len(chunks), label, f"{header}\n\n{piece}"))
    return chunks


def _sections(text: str) -> list[_Section]:
    sections = [_Section(path=[], lines=[])]
    path: list[tuple[int, str]] = []
    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if not match:
            sections[-1].lines.append(line)
            continue
        level, heading = len(match.group(1)), match.group(2).strip()
        path = [(lvl, name) for lvl, name in path if lvl < level] + [(level, heading)]
        sections.append(_Section(path=[name for _, name in path], lines=[]))
    return sections


def _split(body: str, budget: int) -> list[str]:
    """Pack paragraphs greedily; hard-wrap any paragraph that is still too long."""
    if len(body) <= budget:
        return [body]
    pieces: list[str] = []
    current = ""
    for paragraph in _paragraphs(body, budget):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= budget:
            current = candidate
        else:
            pieces.append(current)
            current = paragraph
    if current:
        pieces.append(current)
    return [p for p in pieces if p]


def _paragraphs(body: str, budget: int) -> list[str]:
    result: list[str] = []
    for paragraph in re.split(r"\n{2,}", body):
        while len(paragraph) > budget:
            cut = paragraph.rfind("\n", 0, budget)
            if cut <= 0:
                cut = paragraph.rfind(" ", 0, budget)
            if cut <= 0:
                cut = budget
            result.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if paragraph:
            result.append(paragraph)
    return result

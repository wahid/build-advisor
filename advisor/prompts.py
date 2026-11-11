"""Prompt construction: the model may only answer from numbered sources."""

from __future__ import annotations

import json
from typing import Any

from wiki.search import SearchHit

from .llm import Message

SYSTEM_PROMPT = """\
You are Build Advisor, an assistant for Path of Exile 1 build questions.

Rules:
1. Answer ONLY with information from the numbered sources below. Do not use
   outside knowledge about Path of Exile, even if you are confident.
2. Cite the sources you use with their number in square brackets, e.g. [2],
   right after the claim they support. Every factual claim needs a citation.
   Write citations only as [n]: no links or URLs, the app links them.
3. If the sources don't contain the answer, say plainly that the wiki pages
   you found don't cover it. Never guess or invent gems, items, numbers or
   mechanics. A partial answer is fine if you say what is missing.
4. The sources describe game version {patch}. Mention that version when you
   give numbers or mechanics that may change between leagues.
5. The wiki explains mechanics, not complete builds. When asked for a build,
   explain which options the sources support and why, instead of presenting
   it as a complete, tested build.
6. Answer in the language of the question. Be concise: short paragraphs or a
   short list, no filler."""

TOOLS_PROMPT = """

Path of Building tools:
You can also call tools that run Path of Building, the community's build
calculator, on a real build. Use them when the user attached a build, asks for
numbers (DPS, life, EHP, resistances, max hit), wants support gems or passives
ranked for a build, asks "what if I change X", or asks you to create a build.
For general questions about mechanics the wiki sources are enough.
- Everything you learned from a tool (numbers, notable and gem descriptions,
  item mods) comes from Path of Building: say so, and never put a [n] citation
  on it. [n] is only for facts that are in that numbered wiki source.
  Never invent or estimate numbers.
- A new build starts with new_build, then apply_changes; use search_gems,
  search_uniques and list_ascendancy_notables to look things up instead of
  guessing names. Check get_warnings before you finish.
- When you create or change a build, call export_build last. The app shows the
  share code to the user, so don't paste it into your answer.
- Be efficient: plan your calls and stop as soon as you can answer. You have
  at most {rounds} rounds of tool calls."""

ATTACHED_BUILD = """

The user attached a Path of Building build. It is already loaded, so don't
call load_build for it. Summary:
{summary}"""

NO_SOURCES_ANSWER = (
    "I couldn't find any wiki pages about this, so I can't answer it without guessing."
)


def format_sources(hits: list[SearchHit]) -> str:
    blocks = []
    for number, hit in enumerate(hits, start=1):
        chunk = hit.chunk
        heading = hit.title + (f" > {chunk.section}" if chunk.section else "")
        body = chunk.text.split("\n\n", 1)[-1]
        blocks.append(f"[{number}] {heading} (patch {chunk.patch})\n{body}")
    return "\n\n---\n\n".join(blocks)


def build_messages(
    question: str,
    hits: list[SearchHit],
    tool_rounds: int = 0,
    build_summary: dict[str, Any] | None = None,
) -> list[Message]:
    patches = sorted({hit.chunk.patch for hit in hits})
    system = SYSTEM_PROMPT.format(patch=", ".join(patches) or "unknown")
    if tool_rounds:
        system += TOOLS_PROMPT.format(rounds=tool_rounds)
    if build_summary is not None:
        system += ATTACHED_BUILD.format(summary=json.dumps(build_summary, indent=1)[:4000])
    sources = format_sources(hits) if hits else "(no wiki pages matched)"
    user = f"Sources:\n\n{sources}\n\n===\n\nQuestion: {question}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]

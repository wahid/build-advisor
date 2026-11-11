"""Prompt construction: the model may only answer from numbered sources."""

from __future__ import annotations

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


def build_messages(question: str, hits: list[SearchHit]) -> list[Message]:
    patches = sorted({hit.chunk.patch for hit in hits})
    system = SYSTEM_PROMPT.format(patch=", ".join(patches) or "unknown")
    user = f"Sources:\n\n{format_sources(hits)}\n\n===\n\nQuestion: {question}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]

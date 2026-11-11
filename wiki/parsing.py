"""Convert MediaWiki-rendered HTML into structured plain text.

The output keeps section headings as Markdown-style `##` lines so that
phase 2 can chunk per section instead of by fixed character length.
"""

import re

from bs4 import BeautifulSoup, NavigableString, Tag

# Elements that carry no useful content for answering build questions.
_REMOVE_SELECTORS = [
    "script",
    "style",
    "noscript",
    "sup.reference",
    ".mw-references-wrap",
    "ol.references",
    ".navbox",
    ".navbox-styles",
    ".toc",
    "#toc",
    ".mw-editsection",
    ".noprint",
    ".mw-empty-elt",
    "figure",
    "img",
    ".thumb",
    ".hatnote",
    ".c-item-hoverbox__display",
]

_BLOCK_TAGS = {"p", "div", "ul", "ol", "dl", "dd", "dt", "table", "blockquote", "pre"}


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".mw-parser-output") or soup

    for selector in _REMOVE_SELECTORS:
        for element in root.select(selector):
            element.decompose()

    for br in root.find_all("br"):
        br.replace_with("\n")

    for heading in root.find_all(re.compile(r"^h[2-6]$")):
        level = int(heading.name[1])
        title = heading.get_text(" ", strip=True)
        heading.replace_with(f"\n\n{'#' * level} {title}\n\n")

    for row in root.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
        row.replace_with(" | ".join(c for c in cells if c) + "\n")

    for item in root.find_all("li"):
        item.insert(0, NavigableString("- "))
        item.append(NavigableString("\n"))

    # Infobox stat groups render as spans; give each its own paragraph.
    for group in root.select("span.group, span.header"):
        group.append(NavigableString("\n\n"))

    for block in root.find_all(_BLOCK_TAGS):
        if isinstance(block, Tag):
            block.append(NavigableString("\n"))

    return _normalise_whitespace(root.get_text())


def _normalise_whitespace(text: str) -> str:
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    joined = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", joined).strip()

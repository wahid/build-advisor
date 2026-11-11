import type { ReactNode } from "react";

import type { Source } from "./types";

/**
 * Renders the small Markdown subset the model uses (paragraphs, bullet and
 * numbered lists, headings, **bold**) and turns [n] into source links.
 * Builds React elements directly, so model output is never injected as HTML.
 */

export type Block =
  | { kind: "paragraph"; text: string }
  | { kind: "heading"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] };

const BULLET = /^\s*[-*]\s+/;
const NUMBERED = /^\s*\d+[.)]\s+/;
const HEADING = /^#{1,6}\s+/;

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flush = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", text: paragraph.join(" ") });
    if (list) blocks.push({ kind: "list", ...list });
    paragraph = [];
    list = null;
  };

  for (const line of text.split("\n")) {
    if (!line.trim()) {
      flush();
    } else if (HEADING.test(line)) {
      flush();
      blocks.push({ kind: "heading", text: line.replace(HEADING, "") });
    } else if (BULLET.test(line) || NUMBERED.test(line)) {
      const ordered = NUMBERED.test(line);
      if (paragraph.length || (list && list.ordered !== ordered)) flush();
      list ??= { ordered, items: [] };
      list.items.push(line.replace(ordered ? NUMBERED : BULLET, ""));
    } else if (list && /^\s{2,}/.test(line)) {
      list.items[list.items.length - 1] += ` ${line.trim()}`;
    } else {
      if (list) flush();
      paragraph.push(line.trim());
    }
  }
  flush();
  return blocks;
}

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "cite"; number: number };

export function parseInline(text: string): Inline[] {
  const parts: Inline[] = [];
  // A citation may come as a Markdown link, "[2](https://...)"; the link part is dropped.
  const pattern = /\*\*(.+?)\*\*|\[(\d+)\](?:\(https?:\/\/[^)\s]*\))?/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) parts.push({ kind: "text", text: text.slice(last, match.index) });
    if (match[1] !== undefined) parts.push({ kind: "bold", text: match[1] });
    else parts.push({ kind: "cite", number: Number(match[2]) });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", text: text.slice(last) });
  return parts;
}

interface Props {
  text: string;
  sources: Source[];
  onCiteHover: (number: number | null) => void;
}

export function AnswerText({ text, sources, onCiteHover }: Props) {
  const byNumber = new Map(sources.map((s) => [s.number, s]));

  const inline = (value: string): ReactNode[] =>
    parseInline(value).map((part, i) => {
      if (part.kind === "text") return part.text;
      if (part.kind === "bold") return <strong key={i}>{inline(part.text)}</strong>;
      const source = byNumber.get(part.number);
      if (!source) return `[${part.number}]`;
      const label = source.section ? `${source.title}, ${source.section}` : source.title;
      return (
        <a
          key={i}
          className="cite"
          data-type={source.doc_type}
          href={source.url}
          target="_blank"
          rel="noreferrer"
          aria-label={`Source ${part.number}: ${label}`}
          title={label}
          onMouseEnter={() => onCiteHover(part.number)}
          onMouseLeave={() => onCiteHover(null)}
          onFocus={() => onCiteHover(part.number)}
          onBlur={() => onCiteHover(null)}
        >
          {part.number}
        </a>
      );
    });

  return (
    <>
      {parseBlocks(text).map((block, i) => {
        if (block.kind === "heading") return <h3 key={i}>{inline(block.text)}</h3>;
        if (block.kind === "paragraph") return <p key={i}>{inline(block.text)}</p>;
        const items = block.items.map((item, j) => <li key={j}>{inline(item)}</li>);
        return block.ordered ? <ol key={i}>{items}</ol> : <ul key={i}>{items}</ul>;
      })}
    </>
  );
}

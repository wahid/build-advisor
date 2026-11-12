import { useMemo, type ReactNode } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { EntityName } from "./EntityName";
import type { Entity, Source } from "./types";

/**
 * Renders the model's Markdown (GitHub flavour: tables, lists, links) safely:
 * raw HTML in the text is never rendered. [n] becomes a link to source n,
 * "(general game knowledge)" a badge, and known game names get hover cards.
 */

const CITATION = /\[(\d+)\](?:\(https?:\/\/[^)\s]*\))?/g; // the model sometimes adds the URL
const GENERAL_KNOWLEDGE = /\(general game knowledge\)/gi;
export const CITE_PREFIX = "#cite-";
export const KNOWLEDGE_HREF = "#general-knowledge";

/** Turn citations and the knowledge label into links the renderer recognises. */
export function prepareMarkdown(text: string): string {
  return text
    .replace(GENERAL_KNOWLEDGE, `[general game knowledge](${KNOWLEDGE_HREF})`)
    .replace(CITATION, (_match, n: string) => `[${n}](${CITE_PREFIX}${n})`);
}

interface HastNode {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** A rehype plugin: wrap the first mention of each entity name in a marked span. */
export function markEntities(names: string[]) {
  const sorted = [...new Set(names)].filter((n) => n.length >= 4).sort((a, b) => b.length - a.length);
  return () => (tree: HastNode) => {
    if (!sorted.length) return;
    const pattern = new RegExp(`(?<![\\w'])(${sorted.map(escapeRegExp).join("|")})(?![\\w'])`, "g");
    const seen = new Set<string>();
    const walk = (node: HastNode) => {
      if (!node.children || node.tagName === "a" || node.tagName === "code" || node.tagName === "pre") return;
      const next: HastNode[] = [];
      for (const child of node.children) {
        if (child.type !== "text" || !child.value) {
          walk(child);
          next.push(child);
          continue;
        }
        let last = 0;
        for (const match of child.value.matchAll(pattern)) {
          const name = match[1];
          if (seen.has(name)) continue;
          seen.add(name);
          if (match.index > last) next.push({ type: "text", value: child.value.slice(last, match.index) });
          next.push({
            type: "element",
            tagName: "span",
            properties: { dataEntity: name },
            children: [{ type: "text", value: name }],
          });
          last = match.index + name.length;
        }
        if (last < child.value.length) next.push({ type: "text", value: child.value.slice(last) });
      }
      node.children = next;
    };
    walk(tree);
  };
}

/** A rehype plugin that marks numbers found in no source or tool result. */
export function markNumbers(texts: string[]) {
  const sorted = [...new Set(texts)].filter(Boolean).sort((a, b) => b.length - a.length);
  return () => (tree: HastNode) => {
    if (!sorted.length) return;
    const pattern = new RegExp(`(?<![\\w.,])(${sorted.map(escapeRegExp).join("|")})(?![\\w%]|[.,]\\d)`, "g");
    const walk = (node: HastNode) => {
      if (!node.children || node.tagName === "a" || node.tagName === "code" || node.tagName === "pre") return;
      const next: HastNode[] = [];
      for (const child of node.children) {
        if (child.type !== "text" || !child.value) {
          walk(child);
          next.push(child);
          continue;
        }
        let last = 0;
        for (const match of child.value.matchAll(pattern)) {
          if (match.index > last) next.push({ type: "text", value: child.value.slice(last, match.index) });
          next.push({
            type: "element",
            tagName: "span",
            properties: { dataUnchecked: "true" },
            children: [{ type: "text", value: match[1] }],
          });
          last = match.index + match[1].length;
        }
        if (last < child.value.length) next.push({ type: "text", value: child.value.slice(last) });
      }
      node.children = next;
    };
    walk(tree);
  };
}

interface Props {
  text: string;
  sources: Source[];
  entities?: Entity[];
  /** Numbers to mark as not found in the sources (as written in the answer). */
  unchecked?: string[];
  onCiteHover: (number: number | null) => void;
}

export function AnswerText({ text, sources, entities = [], unchecked = [], onCiteHover }: Props) {
  const byNumber = useMemo(() => new Map(sources.map((s) => [s.number, s])), [sources]);
  const byName = useMemo(() => new Map(entities.map((e) => [e.name, e])), [entities]);
  const rehypePlugins = useMemo(
    () => [markEntities(entities.map((e) => e.name)), markNumbers(unchecked)],
    [entities, unchecked],
  );

  const components: Components = useMemo(
    () => ({
      a({ href, children }): ReactNode {
        if (href?.startsWith(CITE_PREFIX)) {
          const number = Number(href.slice(CITE_PREFIX.length));
          const source = byNumber.get(number);
          if (!source) return `[${number}]`;
          const label = source.section ? `${source.title}, ${source.section}` : source.title;
          return (
            <a
              className="cite"
              data-type={source.doc_type}
              href={source.url}
              target="_blank"
              rel="noreferrer"
              aria-label={`Source ${number}: ${label}`}
              title={label}
              onMouseEnter={() => onCiteHover(number)}
              onMouseLeave={() => onCiteHover(null)}
              onFocus={() => onCiteHover(number)}
              onBlur={() => onCiteHover(null)}
            >
              {number}
            </a>
          );
        }
        if (href === KNOWLEDGE_HREF) {
          return (
            <span className="knowledge" title="Not from the cited wiki pages: the model's own knowledge of the game">
              general game knowledge
            </span>
          );
        }
        return (
          <a href={href} target="_blank" rel="noreferrer">
            {children}
          </a>
        );
      },
      span({ node, children, ...rest }): ReactNode {
        if (node?.properties?.dataUnchecked) {
          return (
            <mark className="unchecked" title="Not found in the sources or Path of Building's results">
              {children}
            </mark>
          );
        }
        const name = node?.properties?.dataEntity;
        const entity = typeof name === "string" ? byName.get(name) : undefined;
        if (entity) return <EntityName entity={entity}>{children}</EntityName>;
        return <span {...rest}>{children}</span>;
      },
      h1: ({ children }) => <h3>{children}</h3>,
      h2: ({ children }) => <h3>{children}</h3>,
      table: ({ children }) => (
        <div className="table-scroll">
          <table>{children}</table>
        </div>
      ),
    }),
    [byNumber, byName, onCiteHover],
  );

  return (
    <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={rehypePlugins} components={components}>
      {prepareMarkdown(text)}
    </Markdown>
  );
}

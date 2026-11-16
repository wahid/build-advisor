import { DOC_TYPES, type Source } from "./types";

const KIND: Record<string, string> = Object.fromEntries(DOC_TYPES.map((t) => [t.value, t.singular]));

export interface SourceGroup {
  url: string;
  title: string;
  doc_type: Source["doc_type"];
  patch: string;
  entries: Source[];
}

/** One group per wiki page, in order of the page's first source number. */
export function groupSources(sources: Source[]): SourceGroup[] {
  const groups = new Map<string, SourceGroup>();
  for (const source of sources) {
    const group = groups.get(source.url);
    if (group) group.entries.push(source);
    else groups.set(source.url, { ...source, entries: [source] });
  }
  return [...groups.values()];
}

/** "Source: Maxroll · by Helm Breaker · updated 13 Nov 2026" (Maxroll's attribution terms). */
export function guideByline(source: Pick<Source, "author" | "updated">): string {
  const parts = ["Source: Maxroll"];
  if (source.author) parts.push(`by ${source.author}`);
  if (source.updated) {
    const date = new Date(`${source.updated}T00:00:00Z`);
    const shown = Number.isNaN(date.getTime())
      ? source.updated
      : date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
    parts.push(`updated ${shown}`);
  }
  return parts.join(" · ");
}

interface Props {
  group: SourceGroup;
  cited: number[];
  hovered: number | null;
  answered: boolean;
}

/** A wiki page drawn like a Path of Exile item tooltip, coloured by page type. */
export function SourceCard({ group, cited, hovered, answered }: Props) {
  const isCited = (n: number) => cited.includes(n);
  const unused = answered && !group.entries.some((e) => isCited(e.number));
  const highlighted = group.entries.some((e) => e.number === hovered);

  return (
    <li
      className="tooltip"
      data-type={group.doc_type}
      data-unused={unused || undefined}
      data-highlighted={highlighted || undefined}
    >
      <a href={group.url} target="_blank" rel="noreferrer" className="tooltip-link">
        <span className="tooltip-header">
          <span className="tooltip-title">{group.title}</span>
          <span className="tooltip-meta">
            {group.doc_type === "web" ? "Web page" : `${KIND[group.doc_type]}, patch ${group.patch}`}
          </span>
          {group.doc_type === "guide" && (
            <span className="tooltip-meta tooltip-byline">{guideByline(group.entries[0])}</span>
          )}
        </span>
        <span className="tooltip-body">
          {group.entries.map((entry) => (
            <span
              key={entry.number}
              className="tooltip-entry"
              data-unused={(answered && !isCited(entry.number)) || undefined}
              data-highlighted={entry.number === hovered || undefined}
            >
              <span className="tooltip-number">{entry.number}</span>
              <span>{entry.section || (entry.doc_type === "web" ? new URL(entry.url).hostname : "Introduction")}</span>
            </span>
          ))}
          {unused && <span className="tooltip-unused">Found, but not used in the answer</span>}
        </span>
      </a>
    </li>
  );
}

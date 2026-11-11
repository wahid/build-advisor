export type DocType = "gem" | "unique" | "ascendancy" | "mechanic";

export interface Source {
  number: number;
  title: string;
  section: string;
  url: string;
  patch: string;
  /** "web": a page found by web search; `section` then names the site and date. */
  doc_type: DocType | "web";
}

export type AskEvent =
  | { type: "rewrite"; terms: string; tools?: boolean }
  | { type: "sources"; sources: Source[] }
  | { type: "delta"; text: string }
  | { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; ok: boolean; error: string }
  | { type: "pob_export"; code: string }
  | { type: "done"; cited: number[]; patch: string }
  | { type: "error"; message: string };

export const DOC_TYPES: { value: DocType; label: string; singular: string }[] = [
  { value: "gem", label: "Gems", singular: "Skill gem" },
  { value: "unique", label: "Uniques", singular: "Unique item" },
  { value: "ascendancy", label: "Ascendancies", singular: "Ascendancy" },
  { value: "mechanic", label: "Mechanics", singular: "Game mechanic" },
];

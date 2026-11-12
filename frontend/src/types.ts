export type DocType = "gem" | "unique" | "ascendancy" | "mechanic" | "patch";

export interface Source {
  number: number;
  title: string;
  section: string;
  url: string;
  patch: string;
  /** "web": a page found by web search; `section` then names the site and date. */
  doc_type: DocType | "web";
}

export interface ComparisonRow {
  stat: string;
  label: string;
  a: number;
  b: number;
  change_pct: number | null;
  higher_is_better: boolean;
}

export interface BuildSummary {
  className?: string | null;
  ascendancy?: string | null;
  level?: number | null;
  mainSkill?: string | null;
}

export interface Comparison {
  a: BuildSummary;
  b: BuildSummary;
  rows: ComparisonRow[];
}

export type AskEvent =
  | { type: "rewrite"; terms: string; tools?: boolean }
  | { type: "sources"; sources: Source[] }
  | { type: "delta"; text: string }
  | { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; ok: boolean; error: string }
  | { type: "pob_export"; code: string }
  | ({ type: "comparison" } & Comparison)
  | { type: "done"; cited: number[]; patch: string; log_id?: string }
  | { type: "error"; message: string };

export const DOC_TYPES: { value: DocType; label: string; singular: string }[] = [
  { value: "gem", label: "Gems", singular: "Skill gem" },
  { value: "unique", label: "Uniques", singular: "Unique item" },
  { value: "ascendancy", label: "Ascendancies", singular: "Ascendancy" },
  { value: "mechanic", label: "Mechanics", singular: "Game mechanic" },
  { value: "patch", label: "Patch notes", singular: "Patch notes" },
];

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

/** One piece of tooltip text and how the game colours it (value, mod, gemdesc, ...). */
export interface CardSegment {
  t: string;
  s: string;
}

/** An in-game style tooltip, from the wiki's item box. */
export interface Card {
  frame: string; // gem, unique, currency, normal, ascendancy, ...
  header: string[];
  groups: { style: string; lines: CardSegment[][] }[];
}

/** A gem, unique or ascendancy named in an answer, for its hover card. */
export interface Entity {
  /** As written in the answer. */
  name: string;
  /** The wiki page title, when it differs ("Point Blank Support"). */
  title?: string;
  doc_type: DocType;
  url: string;
  summary: string;
  card?: Card | null;
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

/** An item the user pasted from the game (Ctrl+C), as the server read it. */
export interface PastedItem {
  name: string;
  base: string;
  item_class: string;
  rarity: string;
  card: Card;
}

/** The pasted item tried on the attached build: stats before (a) and after (b). */
export interface ItemCheck {
  item: PastedItem;
  slot: string;
  /** What was in that slot ("" when it was empty). */
  replaces: string;
  rows: ComparisonRow[];
  tried: string[];
}

export type AskEvent =
  | { type: "rewrite"; terms: string; tools?: boolean }
  | { type: "sources"; sources: Source[] }
  | { type: "delta"; text: string }
  | { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; ok: boolean; error: string }
  | { type: "pob_export"; code: string }
  | ({ type: "comparison" } & Comparison)
  | { type: "item"; item: PastedItem }
  | ({ type: "item_check" } & ItemCheck)
  | { type: "done"; cited: number[]; patch: string; log_id?: string; entities?: Entity[] }
  | { type: "error"; message: string };

export const DOC_TYPES: { value: DocType; label: string; singular: string }[] = [
  { value: "gem", label: "Gems", singular: "Skill gem" },
  { value: "unique", label: "Uniques", singular: "Unique item" },
  { value: "ascendancy", label: "Ascendancies", singular: "Ascendancy" },
  { value: "mechanic", label: "Mechanics", singular: "Game mechanic" },
  { value: "patch", label: "Patch notes", singular: "Patch notes" },
];

export type DocType = "gem" | "unique" | "ascendancy" | "mechanic" | "patch" | "guide";

export interface Source {
  number: number;
  title: string;
  section: string;
  url: string;
  patch: string;
  /** "web": a page found by web search; `section` then names the site and date. */
  doc_type: DocType | "web";
  /** Guides: the author's byline and the page's last-updated date (YYYY-MM-DD). */
  author?: string;
  updated?: string;
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

/** Passive notables ranked in Path of Building for damage and toughness. */
export interface PassiveRanking {
  /** take: what to allocate next; respec: allocated picks that give the least. */
  mode: "take" | "respec";
  focus: "balanced" | "damage" | "defence";
  points_remaining: number;
  max_path_cost: number;
  rows: {
    name: string;
    type: string;
    points: number;
    dps_pct: number;
    ehp_pct: number;
    score: number;
    stats: string[];
  }[];
  note: string;
}

/** When a gem becomes available while leveling, from the wiki's quest tables. */
export interface LevelingGem {
  gem: string;
  known: boolean;
  required_level: number | null;
  quest_reward: { act: number | null; quest: string } | null;
  vendors: { act: number | null; npc: string; after_quest: string }[];
}

export interface Leveling {
  class_name: string;
  gems: LevelingGem[];
  note: string;
}

/** The numbers in an answer, looked up in what the model was given. */
export interface NumberCheck {
  checked: number;
  unsupported: { text: string; context: string }[];
  /** Numbers in sentences labelled general game knowledge (not checked). */
  knowledge: number;
}

/** A search on pathofexile.com/trade for a better rare item in one slot. */
export interface TradeSearch {
  slot: string;
  league: string;
  /** What the build wears there now ("" = nothing). */
  item: string;
  max_price: number | null;
  currency: "chaos" | "divine" | null;
  /** The mods an item must have, with their minimum rolls, most valuable for the build first. */
  stats: string[];
  url: string;
  /** With budget upgrades: the single mod that would gain the most. */
  best_mod?: string;
}

/** Affordable unique items tried on the build, best first. */
export interface Upgrades {
  budget: number;
  currency: "chaos" | "divine";
  budget_chaos: number;
  league: string;
  focus: "balanced" | "damage" | "defence";
  tried: number;
  not_tried_time_limit: number;
  rows: {
    name: string;
    slot: string;
    replaces: string;
    chaos: number;
    divine: number | null;
    dps_pct: number;
    ehp_pct: number;
    resists: Record<string, number>;
    score: number;
  }[];
  /** Trade searches for rare items, capped at the budget. */
  rare_searches?: TradeSearch[];
  note: string;
}

/** The build health check: the usual problems as a checklist, worst first. */
export interface Health {
  checks: { id: string; label: string; status: "bad" | "warn" | "ok"; detail: string }[];
  bad: number;
  warn: number;
  ok: number;
  note: string;
}

/** Lines from the patch notes that name the build's gems, items or ascendancy. */
export interface PatchChanges {
  versions: string[];
  changes: { version: string; name: string; section: string; line: string; url: string }[];
  more: number;
  not_mentioned: string[];
  note: string;
}

/** A notable inside a timeless jewel's radius, and what the seed turns it into. */
export interface TimelessNotable {
  node: string;
  becomes: string | null;
  allocated: boolean;
  points_to_reach: number | null;
  value_pct: number | null;
}

/** One timeless jewel seed in one socket. */
export interface TimelessSeed {
  seed: number;
  socket_near: string;
  socket_allocated: boolean;
  socket_path_cost: number;
  extra_points: number;
  score_gain_pct: number;
  change_pct: { dps?: number | null; ehp?: number | null; life?: number | null };
  notables: TimelessNotable[];
  pick_up: string[];
  trade_url: string;
  trade_any_url: string;
  /** How many seeds give this socket the same result (any of them will do). */
  seeds_tied?: number;
  /** In the socket of the build's current timeless jewel: a straight swap. */
  replaces_current?: boolean;
  breaks?: { stat: string; value: number; needs: number }[];
  note?: string;
}

/** The best timeless jewel seeds and sockets for the build (pob-mcp find_timeless_jewel). */
export interface Timeless {
  jewel: string;
  conqueror: string;
  mode: string;
  verdict: string;
  /** The timeless jewel the build has socketed, if any. */
  current: { jewel: string; seed: number | null; conqueror: string | null; socket: number | null } | null;
  best: TimelessSeed | null;
  alternatives: TimelessSeed[];
  applied: { seed: number; socket: number } | null;
  sockets_scanned: number;
  seeds_per_socket: number;
  top_seeds_url: string;
  note: string;
}

/** One atlas mechanic's points, or a group of nodes the plan drops. */
export interface AtlasMechanic {
  mechanic: string;
  points: number;
  notables: string[];
}

/** A node the atlas plan takes: a notable with its path cost, or a mechanic's small nodes. */
export interface AtlasAddition {
  name: string;
  kind?: string;
  mechanic?: string;
  stats?: string;
  cost?: number;
  small_nodes?: number;
}

/** An atlas passive tree read from a link, and a plan for a farm. */
export interface AtlasTree {
  tree_version: string;
  points_total: number;
  points_used: number;
  points_unspent: number;
  mechanics?: AtlasMechanic[];
  focus?: string[];
  keystones?: { name: string; stats: string }[];
  plan?: {
    farm: string[];
    kept_mechanics: string[];
    remove: AtlasMechanic[];
    points_freed: number;
    add: AtlasAddition[];
    points_after: number;
    points_left: number;
    keystones_in_reach: { name: string; stats: string; cost: number }[];
  };
  link?: string;
  notes?: string[];
}

/** Statements in an answer that contradict Path of Building's data. */
export interface FactCheck {
  wrong: { text: string; context: string; fact: string }[];
}

export type AskEvent =
  | { type: "rewrite"; terms: string; tools?: boolean }
  | { type: "sources"; sources: Source[] }
  | { type: "delta"; text: string }
  | { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; ok: boolean; error: string }
  | { type: "tool_progress"; id: string; name: string; done: number; total: number; label: string }
  | { type: "pob_export"; code: string }
  | ({ type: "comparison" } & Comparison)
  | { type: "item"; item: PastedItem }
  | ({ type: "item_check" } & ItemCheck)
  | ({ type: "passive_ranking" } & PassiveRanking)
  | ({ type: "leveling" } & Leveling)
  | ({ type: "upgrades" } & Upgrades)
  | ({ type: "trade_search" } & TradeSearch)
  | ({ type: "health" } & Health)
  | ({ type: "patch_changes" } & PatchChanges)
  | ({ type: "atlas_tree" } & AtlasTree)
  | ({ type: "timeless" } & Timeless)
  | { type: "done"; cited: number[]; patch: string; log_id?: string; entities?: Entity[]; numbers?: NumberCheck; facts?: FactCheck }
  | { type: "error"; message: string };

export const DOC_TYPES: { value: DocType; label: string; singular: string }[] = [
  { value: "gem", label: "Gems", singular: "Skill gem" },
  { value: "unique", label: "Uniques", singular: "Unique item" },
  { value: "ascendancy", label: "Ascendancies", singular: "Ascendancy" },
  { value: "mechanic", label: "Mechanics", singular: "Game mechanic" },
  { value: "patch", label: "Patch notes", singular: "Patch notes" },
  { value: "guide", label: "Maxroll guides", singular: "Maxroll build guide" },
];

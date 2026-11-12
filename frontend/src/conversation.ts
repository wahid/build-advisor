import type { ToolStep } from "./PobPanel";
import { itemName } from "./items";
import type {
  AskEvent,
  Comparison,
  Entity,
  ItemCheck,
  Leveling,
  LevelingGem,
  NumberCheck,
  PassiveRanking,
  PastedItem,
  Source,
} from "./types";

export type TurnStatus = "searching" | "answering" | "done" | "error";

/** One question in the conversation and everything that came back for it. */
export interface ChatTurn {
  id: string;
  question: string;
  status: TurnStatus;
  answer: string;
  sources: Source[];
  cited: number[];
  steps: ToolStep[];
  exportCode: string;
  searchTerms: string;
  patch: string;
  error: string;
  /** The server's id for this answer, for feedback. */
  logId?: string;
  rating?: 1 | -1;
  comparison?: Comparison;
  /** Game names in the answer, for hover cards. */
  entities?: Entity[];
  /** Item text pasted with the question (kept to ask again). */
  itemText?: string;
  /** The pasted item as the server read it, with its tooltip card. */
  item?: PastedItem;
  /** The pasted item tried on the attached build. */
  itemCheck?: ItemCheck;
  /** Passive notables ranked for the build (the latest ranking of the turn). */
  passives?: PassiveRanking;
  /** When the gems become available while leveling (all lookups of the turn, merged). */
  leveling?: Leveling;
  /** The answer's numbers, checked against the sources and tool results. */
  numbers?: NumberCheck;
}

function firstAct(gem: LevelingGem): number {
  const acts = [gem.quest_reward?.act, ...gem.vendors.map((v) => v.act)].filter((a): a is number => Boolean(a));
  return acts.length ? Math.min(...acts) : 99;
}

/** Add a lookup's gems to the turn's table: one row per gem, in the order they come. */
export function mergeLeveling(earlier: Leveling | undefined, next: Leveling): Leveling {
  const byGem = new Map((earlier?.gems ?? []).map((gem) => [gem.gem, gem]));
  for (const gem of next.gems) byGem.set(gem.gem, gem);
  const gems = [...byGem.values()].sort(
    (a, b) => firstAct(a) - firstAct(b) || (a.required_level ?? 0) - (b.required_level ?? 0),
  );
  return { class_name: next.class_name || earlier?.class_name || "", gems, note: next.note };
}

/** What the server gets for each earlier turn. */
export interface HistoryTurn {
  question: string;
  answer: string;
}

const BUILD_LINKS = /https?:\/\/(?:www\.)?(?:pobb\.in|pastebin\.com)\/[\w\-/]+/gi;

/** pobb.in / pastebin links in the question, in order: the build, then one to compare with. */
export function findBuildLinks(question: string): string[] {
  const links: string[] = [];
  for (const match of question.matchAll(BUILD_LINKS)) {
    const link = match[0].replace(/^http:/i, "https:").replace(/\/+$/, "");
    if (!links.includes(link)) links.push(link);
  }
  return links.slice(0, 2);
}

/** The first build link in the question, or "". */
export function findBuildLink(question: string): string {
  return findBuildLinks(question)[0] ?? "";
}

export const MAX_HISTORY = 6; // the server uses no more than this
const STORAGE_KEY = "build-advisor:conversation";
const BUILD_KEY = "build-advisor:build";

/** The build attached to the conversation, and whether it's the assistant's changed version. */
export interface AttachedBuild {
  build: string;
  changed: boolean;
}

export function newTurn(id: string, question: string, itemText = ""): ChatTurn {
  return {
    id,
    question,
    ...(itemText ? { itemText } : {}),
    status: "searching",
    answer: "",
    sources: [],
    cited: [],
    steps: [],
    exportCode: "",
    searchTerms: "",
    patch: "",
    error: "",
  };
}

/** Apply one streamed event to the turn it belongs to. */
export function applyEvent(turn: ChatTurn, event: AskEvent): ChatTurn {
  switch (event.type) {
    case "rewrite":
      return { ...turn, searchTerms: event.terms };
    case "sources":
      return { ...turn, sources: event.sources, patch: event.sources[0]?.patch ?? turn.patch, status: "answering" };
    case "delta":
      return { ...turn, answer: turn.answer + event.text };
    case "tool_call":
      return {
        ...turn,
        steps: [
          ...turn.steps,
          { id: event.id, name: event.name, arguments: event.arguments, status: "running", startedAt: Date.now() },
        ],
      };
    case "tool_result":
      return {
        ...turn,
        steps: turn.steps.map((step) =>
          step.id === event.id ? { ...step, status: event.ok ? "ok" : "failed", error: event.error } : step,
        ),
      };
    case "tool_progress":
      return {
        ...turn,
        steps: turn.steps.map((step) =>
          step.id === event.id ? { ...step, progress: { done: event.done, total: event.total, label: event.label } } : step,
        ),
      };
    case "pob_export":
      return { ...turn, exportCode: event.code };
    case "comparison":
      return { ...turn, comparison: { a: event.a, b: event.b, rows: event.rows } };
    case "item":
      return { ...turn, item: event.item };
    case "leveling": {
      const { type: _type, ...lookup } = event;
      return { ...turn, leveling: mergeLeveling(turn.leveling, lookup) };
    }
    case "passive_ranking": {
      const { type: _type, ...ranking } = event;
      return { ...turn, passives: ranking };
    }
    case "item_check": {
      const { type: _type, ...check } = event;
      return { ...turn, itemCheck: check };
    }
    case "done":
      return {
        ...turn,
        cited: event.cited,
        patch: event.patch || turn.patch,
        status: "done",
        logId: event.log_id,
        entities: event.entities ?? [],
        ...(event.numbers ? { numbers: event.numbers } : {}),
      };
    case "error":
      return { ...turn, error: event.message, status: "error" };
  }
}

/** Earlier answered turns, oldest first, for a follow-up question. */
export function toHistory(turns: ChatTurn[]): HistoryTurn[] {
  return turns
    .filter((turn) => turn.status === "done" && turn.answer.trim())
    .slice(-MAX_HISTORY)
    .map((turn) => ({ question: questionFor(turn), answer: turn.answer }));
}

/** The question as the model saw it: a pasted item is named, since its text isn't sent again. */
export function questionFor(turn: ChatTurn): string {
  if (!turn.itemText) return turn.question;
  const item = `(pasted item: ${turn.item ? `${turn.item.name}, ${turn.item.base}` : itemName(turn.itemText)})`;
  return `${item} ${turn.question}`.trim().slice(0, 500);
}

/** The single conversation an older version kept (migrated into the chat list). */
export function loadConversation(): ChatTurn[] {
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "[]") as ChatTurn[];
    return Array.isArray(saved) ? saved.filter((turn) => turn.status === "done" || turn.status === "error") : [];
  } catch {
    return [];
  }
}


export function loadAttachedBuild(): AttachedBuild {
  try {
    const saved = JSON.parse(window.localStorage.getItem(BUILD_KEY) ?? "null") as AttachedBuild | null;
    if (saved && typeof saved.build === "string") return { build: saved.build, changed: Boolean(saved.changed) };
  } catch {
    // fall through: nothing attached
  }
  return { build: "", changed: false };
}


/** One chat in the sidebar: its turns and the build attached to it. */
export interface Conversation {
  id: string;
  title: string;
  updatedAt: number;
  turns: ChatTurn[];
  build: string;
  buildChanged: boolean;
  /** A second build to compare with (optional). */
  compareBuild?: string;
}

const CHATS_KEY = "build-advisor:chats";
export const MAX_CONVERSATIONS = 50; // the oldest beyond this are dropped
const TITLE_CHARS = 60;

export function newConversation(id: string, now = Date.now()): Conversation {
  return { id, title: "New chat", updatedAt: now, turns: [], build: "", buildChanged: false };
}

/** A chat is named after its first question. */
export function titleFor(turns: ChatTurn[]): string {
  const turn = turns[0];
  const first = (turn?.question || (turn?.itemText ? itemName(turn.itemText) : "")).replace(/\s+/g, " ").trim();
  if (!first) return "New chat";
  return first.length > TITLE_CHARS ? `${first.slice(0, TITLE_CHARS - 1)}…` : first;
}

function finished(turns: ChatTurn[]): ChatTurn[] {
  return turns.filter((turn) => turn.status === "done" || turn.status === "error");
}

/** Saved chats, newest first. The single conversation an older version kept becomes the first chat. */
export function loadConversations(): Conversation[] {
  try {
    const saved = JSON.parse(window.localStorage.getItem(CHATS_KEY) ?? "null") as Conversation[] | null;
    if (Array.isArray(saved)) {
      return saved
        .filter((c) => c && typeof c.id === "string" && Array.isArray(c.turns))
        .map((c) => ({ ...c, turns: finished(c.turns) }))
        .sort((a, b) => b.updatedAt - a.updatedAt);
    }
    const turns = loadConversation();
    if (turns.length) {
      const attached = loadAttachedBuild();
      const migrated = newConversation("chat-migrated");
      return [{ ...migrated, title: titleFor(turns), turns, build: attached.build, buildChanged: attached.changed }];
    }
  } catch {
    // fall through: start without saved chats
  }
  return [];
}

/** Keeps chats that have at least one finished turn; unfinished turns are left out. */
export function saveConversations(conversations: Conversation[]): void {
  try {
    const kept = conversations
      .map((c) => ({ ...c, turns: finished(c.turns) }))
      .filter((c) => c.turns.length > 0)
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, MAX_CONVERSATIONS);
    window.localStorage.setItem(CHATS_KEY, JSON.stringify(kept));
    window.localStorage.removeItem(STORAGE_KEY); // the single-conversation format is migrated
    window.localStorage.removeItem(BUILD_KEY);
  } catch {
    // Storage can be full or blocked; the chats just aren't kept.
  }
}

const ACTIVE_KEY = "build-advisor:active-chat";

export function loadActiveId(): string {
  try {
    return window.localStorage.getItem(ACTIVE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveActiveId(id: string): void {
  try {
    window.localStorage.setItem(ACTIVE_KEY, id);
  } catch {
    // not kept; the newest chat opens instead
  }
}

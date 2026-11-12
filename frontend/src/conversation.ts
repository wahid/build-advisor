import type { ToolStep } from "./PobPanel";
import type { AskEvent, Source } from "./types";

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
}

/** What the server gets for each earlier turn. */
export interface HistoryTurn {
  question: string;
  answer: string;
}

const BUILD_LINK = /https?:\/\/(?:www\.)?(?:pobb\.in|pastebin\.com)\/[\w\-/]+/i;

/** A pobb.in or pastebin link in the question, which the server loads as the build. */
export function findBuildLink(question: string): string {
  const match = BUILD_LINK.exec(question);
  return match ? match[0].replace(/^http:/i, "https:").replace(/\/+$/, "") : "";
}

export const MAX_HISTORY = 6; // the server uses no more than this
const STORAGE_KEY = "build-advisor:conversation";
const BUILD_KEY = "build-advisor:build";

/** The build attached to the conversation, and whether it's the assistant's changed version. */
export interface AttachedBuild {
  build: string;
  changed: boolean;
}

export function newTurn(id: string, question: string): ChatTurn {
  return {
    id,
    question,
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
        steps: [...turn.steps, { id: event.id, name: event.name, arguments: event.arguments, status: "running" }],
      };
    case "tool_result":
      return {
        ...turn,
        steps: turn.steps.map((step) =>
          step.id === event.id ? { ...step, status: event.ok ? "ok" : "failed", error: event.error } : step,
        ),
      };
    case "pob_export":
      return { ...turn, exportCode: event.code };
    case "done":
      return { ...turn, cited: event.cited, patch: event.patch || turn.patch, status: "done" };
    case "error":
      return { ...turn, error: event.message, status: "error" };
  }
}

/** Earlier answered turns, oldest first, for a follow-up question. */
export function toHistory(turns: ChatTurn[]): HistoryTurn[] {
  return turns
    .filter((turn) => turn.status === "done" && turn.answer.trim())
    .slice(-MAX_HISTORY)
    .map((turn) => ({ question: turn.question, answer: turn.answer }));
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
}

const CHATS_KEY = "build-advisor:chats";
export const MAX_CONVERSATIONS = 50; // the oldest beyond this are dropped
const TITLE_CHARS = 60;

export function newConversation(id: string, now = Date.now()): Conversation {
  return { id, title: "New chat", updatedAt: now, turns: [], build: "", buildChanged: false };
}

/** A chat is named after its first question. */
export function titleFor(turns: ChatTurn[]): string {
  const first = turns[0]?.question.replace(/\s+/g, " ").trim();
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

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

export const MAX_HISTORY = 6; // the server uses no more than this
const STORAGE_KEY = "build-advisor:conversation";

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

/** The finished turns of the last conversation in this browser, if any. */
export function loadConversation(): ChatTurn[] {
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "[]") as ChatTurn[];
    return Array.isArray(saved) ? saved.filter((turn) => turn.status === "done" || turn.status === "error") : [];
  } catch {
    return [];
  }
}

export function saveConversation(turns: ChatTurn[]): void {
  try {
    const finished = turns.filter((turn) => turn.status === "done" || turn.status === "error");
    if (finished.length) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(finished));
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage can be full or blocked; the conversation just isn't kept.
  }
}

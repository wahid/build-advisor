import { SSEParser } from "./sse";
import type { HistoryTurn } from "./conversation";
import type { AskEvent, DocType, Entity, Source } from "./types";

export class AskError extends Error {
  constructor(
    message: string,
    /** "daily_limit" when the site's questions for today are used up. */
    readonly code = "",
    /** When the daily limit resets (ISO time), for a countdown. */
    readonly resetsAt = "",
  ) {
    super(message);
  }
}

async function askError(response: Response): Promise<AskError> {
  if (response.status === 429) {
    try {
      const body = (await response.json()) as { code?: string; detail?: string; resets_at?: string };
      if (body.code === "daily_limit") {
        return new AskError(body.detail || "The demo's questions for today are used up.", "daily_limit", body.resets_at ?? "");
      }
    } catch {
      // fall through to the per-visitor message
    }
  }
  return new AskError(await errorMessage(response));
}

async function errorMessage(response: Response): Promise<string> {
  if (response.status === 429) {
    return "You've asked a lot of questions in a short time. Wait a few minutes and try again.";
  }
  if (response.status === 400) {
    try {
      const body = (await response.json()) as Record<string, string[]>;
      if (body.question) return `Question: ${body.question.join(" ")}`;
      if (body.build) return `Build: ${body.build.join(" ")}`;
      if (body.item) return `Item: ${body.item.join(" ")}`;
    } catch {
      // fall through to the generic message
    }
    return "The question couldn't be sent. Check it and try again.";
  }
  return `The server returned an error (${response.status}). Try again later.`;
}

export interface AskOptions {
  docTypes?: DocType[];
  build?: string;
  /** A second build to compare the first with. */
  compareBuild?: string;
  /** An item copied from the game, to try on the build. */
  item?: string;
  /** Earlier turns of the conversation, oldest first. */
  history?: HistoryTurn[];
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

/** Ask a question and yield events as the answer streams in. */
export async function* ask(question: string, options: AskOptions = {}): AsyncGenerator<AskEvent> {
  const { docTypes = [], build = "", compareBuild = "", item = "", history = [], signal, fetchImpl = fetch } = options;
  const response = await fetchImpl("/api/ask/", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question, doc_types: docTypes, build, compare_build: compareBuild, history, ...(item ? { item } : {}) }),
    signal,
  });
  if (!response.ok || !response.body) throw await askError(response);

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SSEParser();
  while (true) {
    const { value, done } = await reader.read();
    if (done) return;
    yield* parser.push(value);
  }
}

/** Rate an answer (1 helpful, -1 not), with an optional note. */
export async function sendFeedback(
  logId: string,
  rating: 1 | -1,
  feedback = "",
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  const response = await fetchImpl("/api/feedback/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ log_id: logId, rating, feedback }),
  });
  if (!response.ok) throw new AskError("Your feedback couldn't be sent. Try again later.");
}

/** A chat published as a read-only page. */
export interface ShareLink {
  slug: string;
  url: string;
  /** Lets this browser take the page down again. */
  deleteKey: string;
  /** How many answers the page shows (to tell when the chat has grown since). */
  turns: number;
}

/** Publish the answers with these log ids as a read-only page. */
export async function shareChat(logIds: string[], fetchImpl: typeof fetch = fetch): Promise<ShareLink> {
  const response = await fetchImpl("/api/share/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ log_ids: logIds }),
  });
  if (!response.ok) {
    const message =
      response.status === 429 ? "You've shared a lot of chats in a short time. Try again later." : "The chat couldn't be shared. Try again later.";
    throw new AskError(message);
  }
  const body = (await response.json()) as { slug: string; url: string; delete_key: string };
  return { slug: body.slug, url: body.url, deleteKey: body.delete_key, turns: logIds.length };
}

/** Take a shared page down. */
export async function unshareChat(link: ShareLink, fetchImpl: typeof fetch = fetch): Promise<void> {
  const response = await fetchImpl(`/api/share/${link.slug}/`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ delete_key: link.deleteKey }),
  });
  // 404/403: it's already gone (e.g. removed by the site's owner).
  if (!response.ok && response.status !== 403 && response.status !== 404) {
    throw new AskError("The link couldn't be removed. Try again later.");
  }
}

export interface SharedTurn {
  question: string;
  answer: string;
  sources: Source[];
  cited: number[];
  patch: string;
  entities: Entity[];
}

export interface SharedChat {
  slug: string;
  title: string;
  created_at: string;
  turns: SharedTurn[];
}

/** A shared chat, or null when it doesn't exist (any more). */
export async function fetchSharedChat(slug: string, fetchImpl: typeof fetch = fetch): Promise<SharedChat | null> {
  const response = await fetchImpl(`/api/share/${encodeURIComponent(slug)}/`);
  if (response.status === 404) return null;
  if (!response.ok) throw new AskError("The shared chat couldn't be loaded. Try again later.");
  return (await response.json()) as SharedChat;
}

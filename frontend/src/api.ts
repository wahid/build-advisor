import { SSEParser } from "./sse";
import type { HistoryTurn } from "./conversation";
import type { AskEvent, DocType } from "./types";

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
  /** Earlier turns of the conversation, oldest first. */
  history?: HistoryTurn[];
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

/** Ask a question and yield events as the answer streams in. */
export async function* ask(question: string, options: AskOptions = {}): AsyncGenerator<AskEvent> {
  const { docTypes = [], build = "", compareBuild = "", history = [], signal, fetchImpl = fetch } = options;
  const response = await fetchImpl("/api/ask/", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question, doc_types: docTypes, build, compare_build: compareBuild, history }),
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

import { SSEParser } from "./sse";
import type { HistoryTurn } from "./conversation";
import type { AskEvent, DocType } from "./types";

export class AskError extends Error {}

async function errorMessage(response: Response): Promise<string> {
  if (response.status === 429) {
    try {
      const body = (await response.json()) as { code?: string; detail?: string };
      if (body.code === "daily_limit" && body.detail) return body.detail;
    } catch {
      // fall through to the per-visitor message
    }
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
  /** Earlier turns of the conversation, oldest first. */
  history?: HistoryTurn[];
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

/** Ask a question and yield events as the answer streams in. */
export async function* ask(question: string, options: AskOptions = {}): AsyncGenerator<AskEvent> {
  const { docTypes = [], build = "", history = [], signal, fetchImpl = fetch } = options;
  const response = await fetchImpl("/api/ask/", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question, doc_types: docTypes, build, history }),
    signal,
  });
  if (!response.ok || !response.body) throw new AskError(await errorMessage(response));

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

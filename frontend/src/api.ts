import { SSEParser } from "./sse";
import type { AskEvent, DocType } from "./types";

export class AskError extends Error {}

async function errorMessage(response: Response): Promise<string> {
  if (response.status === 429) {
    return "You've asked a lot of questions in a short time. Wait a few minutes and try again.";
  }
  if (response.status === 400) {
    try {
      const body = (await response.json()) as Record<string, string[]>;
      if (body.question) return `Question: ${body.question.join(" ")}`;
    } catch {
      // fall through to the generic message
    }
    return "The question couldn't be sent. Check it and try again.";
  }
  return `The server returned an error (${response.status}). Try again later.`;
}

/** Ask a question and yield events as the answer streams in. */
export async function* ask(
  question: string,
  docTypes: DocType[],
  signal?: AbortSignal,
  fetchImpl: typeof fetch = fetch,
): AsyncGenerator<AskEvent> {
  const response = await fetchImpl("/api/ask/", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question, doc_types: docTypes }),
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

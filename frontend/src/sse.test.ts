import { describe, expect, it } from "vitest";

import { ask, AskError } from "./api";
import { SSEParser } from "./sse";
import type { AskEvent } from "./types";

const frame = (event: AskEvent) =>
  `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;

describe("SSEParser", () => {
  it("handles events split across chunks", () => {
    const parser = new SSEParser();
    const whole = frame({ type: "delta", text: "Hello" }) + frame({ type: "done", cited: [1], patch: "3.29.3c" });

    const first = parser.push(whole.slice(0, 20));
    const rest = parser.push(whole.slice(20));

    expect(first).toEqual([]);
    expect(rest).toEqual([
      { type: "delta", text: "Hello" },
      { type: "done", cited: [1], patch: "3.29.3c" },
    ]);
  });

  it("accepts CRLF line endings", () => {
    const parser = new SSEParser();
    expect(parser.push('event: delta\r\ndata: {"type":"delta","text":"x"}\r\n\r\n')).toEqual([
      { type: "delta", text: "x" },
    ]);
  });
});

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      chunks.forEach((c) => controller.enqueue(encoder.encode(c)));
      controller.close();
    },
  });
}

describe("ask", () => {
  it("posts the question and yields streamed events", async () => {
    let body: unknown;
    const fakeFetch = (async (_url: string, init: RequestInit) => {
      body = JSON.parse(init.body as string);
      return new Response(streamOf(frame({ type: "delta", text: "Hi" })), { status: 200 });
    }) as typeof fetch;

    const events = [];
    const history = [{ question: "What is RF?", answer: "A fire spell [1]." }];
    const options = { docTypes: ["gem" as const], build: "eNrCODE", history, fetchImpl: fakeFetch };
    for await (const event of ask("RF?", options)) events.push(event);

    expect(body).toEqual({ question: "RF?", doc_types: ["gem"], build: "eNrCODE", history });
    expect(events).toEqual([{ type: "delta", text: "Hi" }]);
  });

  it("shows the site-wide daily limit message", async () => {
    const body = JSON.stringify({ code: "daily_limit", detail: "The demo has reached today's limit." });
    const fakeFetch = (async () => new Response(body, { status: 429 })) as typeof fetch;

    await expect(ask("q", { fetchImpl: fakeFetch }).next()).rejects.toThrow("today's limit");
  });

  it("explains rate limiting", async () => {
    const fakeFetch = (async () => new Response("{}", { status: 429 })) as typeof fetch;

    await expect(ask("q", { fetchImpl: fakeFetch }).next()).rejects.toThrow(AskError);
    await expect(ask("q", { fetchImpl: fakeFetch }).next()).rejects.toThrow(/Wait a few minutes/);
  });
});

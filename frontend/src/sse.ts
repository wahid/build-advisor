import type { AskEvent } from "./types";

/**
 * Incremental parser for the Server-Sent Events sent by POST /api/ask/.
 * (EventSource only supports GET, so the stream is read with fetch.)
 */
export class SSEParser {
  private buffer = "";

  push(chunk: string): AskEvent[] {
    this.buffer += chunk.replace(/\r\n/g, "\n");
    const events: AskEvent[] = [];
    let end: number;
    while ((end = this.buffer.indexOf("\n\n")) !== -1) {
      const block = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).replace(/^ /, ""))
        .join("\n");
      if (data) events.push(JSON.parse(data) as AskEvent);
    }
    return events;
  }
}

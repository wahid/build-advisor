import { afterEach, describe, expect, it } from "vitest";

import {
  applyEvent,
  findBuildLink,
  loadConversations,
  MAX_HISTORY,
  newConversation,
  newTurn,
  saveConversations,
  titleFor,
  toHistory,
  type ChatTurn,
  type Conversation,
} from "./conversation";

const source = {
  number: 1,
  title: "Poison",
  section: "Mechanics",
  url: "https://www.poewiki.net/wiki/Poison",
  patch: "3.29.3c",
  doc_type: "mechanic" as const,
};

function answered(question: string, answer: string): ChatTurn {
  return { ...newTurn(question, question), answer, status: "done" };
}

describe("applyEvent", () => {
  it("builds a turn from the stream", () => {
    let turn = newTurn("t1", "How does poison stack?");
    turn = applyEvent(turn, { type: "sources", sources: [source] });
    expect(turn.status).toBe("answering");
    expect(turn.patch).toBe("3.29.3c");
    turn = applyEvent(turn, { type: "delta", text: "Every poison " });
    turn = applyEvent(turn, { type: "delta", text: "counts [1]." });
    turn = applyEvent(turn, { type: "done", cited: [1], patch: "3.29.3c" });
    expect(turn.answer).toBe("Every poison counts [1].");
    expect(turn.cited).toEqual([1]);
    expect(turn.status).toBe("done");
  });

  it("tracks Path of Building steps", () => {
    let turn = newTurn("t1", "q");
    turn = applyEvent(turn, { type: "tool_call", id: "a", name: "load_build", arguments: {} });
    turn = applyEvent(turn, { type: "tool_result", id: "a", name: "load_build", ok: false, error: "bad code" });
    expect(turn.steps).toEqual([{ id: "a", name: "load_build", arguments: {}, status: "failed", error: "bad code" }]);
  });
});

describe("toHistory", () => {
  it("keeps answered turns only, oldest first", () => {
    const failed = { ...newTurn("x", "broken"), status: "error" as const, error: "down" };
    const running = newTurn("y", "still going");
    const history = toHistory([answered("q1", "a1"), failed, answered("q2", "a2"), running]);
    expect(history).toEqual([
      { question: "q1", answer: "a1" },
      { question: "q2", answer: "a2" },
    ]);
  });

  it("sends at most the last few turns", () => {
    const turns = Array.from({ length: MAX_HISTORY + 2 }, (_, i) => answered(`q${i}`, `a${i}`));
    const history = toHistory(turns);
    expect(history).toHaveLength(MAX_HISTORY);
    expect(history[0].question).toBe("q2");
  });
});

describe("findBuildLink", () => {
  it("finds pobb.in and pastebin links in a question", () => {
    expect(findBuildLink("Is this tanky? https://pobb.in/uGQdbD7BJnVS")).toBe("https://pobb.in/uGQdbD7BJnVS");
    expect(findBuildLink("see http://pastebin.com/abc123/ please")).toBe("https://pastebin.com/abc123");
    expect(findBuildLink("How does poison work?")).toBe("");
    expect(findBuildLink("https://evil.example/pobb.in/x")).toBe("");
  });
});

describe("saved chats", () => {
  afterEach(() => {
    delete (globalThis as { window?: unknown }).window;
  });

  function fakeStorage(initial: Record<string, string> = {}) {
    const items = new Map<string, string>(Object.entries(initial));
    (globalThis as { window?: unknown }).window = {
      localStorage: {
        getItem: (key: string) => items.get(key) ?? null,
        setItem: (key: string, value: string) => items.set(key, value),
        removeItem: (key: string) => items.delete(key),
      },
    };
    return items;
  }

  const chat = (id: string, updatedAt: number, turns: ChatTurn[]): Conversation => ({
    ...newConversation(id, updatedAt),
    title: titleFor(turns),
    turns,
  });

  it("keeps chats with finished turns, newest first", () => {
    fakeStorage();
    const running = newTurn("r", "still going");
    saveConversations([
      chat("old", 1, [answered("first question", "a")]),
      chat("empty", 3, []),
      chat("new", 2, [answered("second question", "b"), running]),
    ]);

    const loaded = loadConversations();

    expect(loaded.map((c) => c.id)).toEqual(["new", "old"]);
    expect(loaded[0].turns.map((t) => t.question)).toEqual(["second question"]);
    expect(loaded[1].title).toBe("first question");
  });

  it("moves the conversation an older version kept into the chat list", () => {
    const old = [answered("How does poison work?", "It stacks.")];
    const items = fakeStorage({
      "build-advisor:conversation": JSON.stringify(old),
      "build-advisor:build": JSON.stringify({ build: "eNrCODE", changed: true }),
    });

    const loaded = loadConversations();

    expect(loaded).toHaveLength(1);
    expect(loaded[0]).toMatchObject({ title: "How does poison work?", build: "eNrCODE", buildChanged: true });
    saveConversations(loaded);
    expect(items.has("build-advisor:conversation")).toBe(false);
    expect(loadConversations()[0].turns[0].answer).toBe("It stacks.");
  });

  it("names a chat after its first question", () => {
    expect(titleFor([])).toBe("New chat");
    expect(titleFor([answered("  What   scales ignite? ", "a")])).toBe("What scales ignite?");
    expect(titleFor([answered("x".repeat(80), "a")])).toHaveLength(60);
  });

  it("works without storage", () => {
    expect(loadConversations()).toEqual([]);
    expect(() => saveConversations([])).not.toThrow();
  });
});

import { describe, expect, it } from "vitest";

import { applyEvent, MAX_HISTORY, newTurn, toHistory, type ChatTurn } from "./conversation";

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

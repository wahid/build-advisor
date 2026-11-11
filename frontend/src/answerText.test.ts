import { describe, expect, it } from "vitest";

import { parseBlocks, parseInline } from "./answerText";

describe("parseBlocks", () => {
  it("splits paragraphs, headings and lists", () => {
    const text = "**Supports**\n\n- One [1]\n- Two\n  continued\n\n### Chieftain\nPlain text.\n\n1. First\n2. Second";

    expect(parseBlocks(text)).toEqual([
      { kind: "paragraph", text: "**Supports**" },
      { kind: "list", ordered: false, items: ["One [1]", "Two continued"] },
      { kind: "heading", text: "Chieftain" },
      { kind: "paragraph", text: "Plain text." },
      { kind: "list", ordered: true, items: ["First", "Second"] },
    ]);
  });

  it("joins wrapped paragraph lines", () => {
    expect(parseBlocks("a\nb")).toEqual([{ kind: "paragraph", text: "a b" }]);
  });
});

describe("parseInline", () => {
  it("finds bold text and citations", () => {
    expect(parseInline("Use **Inspiration** for more damage [1][7].")).toEqual([
      { kind: "text", text: "Use " },
      { kind: "bold", text: "Inspiration" },
      { kind: "text", text: " for more damage " },
      { kind: "cite", number: 1 },
      { kind: "cite", number: 7 },
      { kind: "text", text: "." },
    ]);
  });

  it("drops links that models attach to citations", () => {
    expect(parseInline("Attacks [1](https://www.poewiki.net/wiki/Slayer).")).toEqual([
      { kind: "text", text: "Attacks " },
      { kind: "cite", number: 1 },
      { kind: "text", text: "." },
    ]);
  });

  it("leaves unfinished bold markers alone while streaming", () => {
    expect(parseInline("**Insp")).toEqual([{ kind: "text", text: "**Insp" }]);
  });
});

describe("groupSources", () => {
  it("merges sources from the same page and keeps first-seen order", async () => {
    const { groupSources } = await import("./SourceCard");
    const source = (number: number, title: string, section: string) => ({
      number,
      title,
      section,
      url: `https://wiki/${title}`,
      patch: "3.29.3c",
      doc_type: "gem" as const,
    });

    const groups = groupSources([source(1, "RF", "A"), source(2, "Chieftain", ""), source(3, "RF", "B")]);

    expect(groups.map((g) => [g.title, g.entries.map((e) => e.number)])).toEqual([
      ["RF", [1, 3]],
      ["Chieftain", [2]],
    ]);
  });
});

describe("stepLabel", () => {
  it("uses past tense for finished steps and says what failed", async () => {
    const { stepLabel } = await import("./PobPanel");

    expect(stepLabel("rank_support_gems")).toBe("Ranked support gems");
    expect(stepLabel("fix_gaps", true)).toBe("Couldn't fix resistance and attribute gaps");
    expect(stepLabel("brand_new_tool")).toBe("brand new tool");
  });
});

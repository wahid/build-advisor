import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AnswerText, prepareMarkdown } from "./answerText";
import type { Entity, Source } from "./types";

const sources: Source[] = [
  { number: 1, title: "Poison", section: "Mechanics", url: "https://w/Poison", patch: "3.29", doc_type: "mechanic" },
  { number: 2, title: "Volatility Support", section: "", url: "https://w/Volatility", patch: "3.29", doc_type: "gem" },
];

function render(text: string, entities: Entity[] = []): string {
  return renderToStaticMarkup(createElement(AnswerText, { text, sources, entities, onCiteHover: () => {} }));
}

describe("prepareMarkdown", () => {
  it("turns citations and the knowledge label into links", () => {
    expect(prepareMarkdown("Poisons stack [1][2]. Bleeds don't (general game knowledge).")).toBe(
      "Poisons stack [1](#cite-1)[2](#cite-2). Bleeds don't [general game knowledge](#general-knowledge).",
    );
    expect(prepareMarkdown("See [3](https://www.poewiki.net/wiki/X).")).toBe("See [3](#cite-3).");
  });
});

describe("AnswerText", () => {
  it("renders tables, lists and headings", () => {
    const html = render("### Supports\n\n| Gem | More |\n|---|---|\n| Brutality | 39% |\n\n- one\n- two");
    expect(html).toContain("<h3>Supports</h3>");
    expect(html).toContain('<div class="table-scroll"><table>');
    expect(html).toContain("<td>Brutality</td>");
    expect(html).toContain("<li>one</li>");
  });

  it("links citations to their sources and leaves unknown numbers as text", () => {
    const html = render("Poison stacks [1], see also [9].");
    expect(html).toContain('class="cite" data-type="mechanic" href="https://w/Poison"');
    expect(html).toContain("see also [9].");
  });

  it("shows general game knowledge as a badge", () => {
    expect(render("Only the strongest bleed counts (general game knowledge).")).toContain(
      '<span class="knowledge"',
    );
  });

  it("never renders raw HTML from the model", () => {
    const html = render('Hi <img src=x onerror="alert(1)"> <script>alert(1)</script>');
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<script");
  });

  it("marks the first mention of a known game name", () => {
    const entity: Entity = { name: "Volatility Support", doc_type: "gem", url: "https://w/V", summary: "More max damage." };
    const html = render("Use Volatility Support. Volatility Support again. `Volatility Support`", [entity]);
    expect(html.match(/class="entity"/g)).toHaveLength(1);
    expect(html).toContain('<code>Volatility Support</code>');
  });
});

describe("stepLabel", () => {
  it("uses past tense for finished steps and says what failed", async () => {
    const { stepLabel } = await import("./PobPanel");

    expect(stepLabel("rank_support_gems")).toBe("Ranked support gems");
    expect(stepLabel("fix_gaps", true)).toBe("Couldn't fix resistance and attribute gaps");
    expect(stepLabel("brand_new_tool")).toBe("brand new tool");
  });

  it("says what the web search looked for", async () => {
    const { stepLabel } = await import("./PobPanel");

    expect(stepLabel("web_search", false, { query: "3.29 patch notes" })).toBe("Searched the web for “3.29 patch notes”");
    expect(stepLabel("web_search", true, { query: "x" })).toBe("Couldn't search the web for “x”");
  });
});

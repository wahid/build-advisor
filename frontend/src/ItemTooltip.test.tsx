import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ItemTooltip } from "./ItemTooltip";
import type { Card } from "./types";

const card: Card = {
  frame: "unique",
  header: ["Darkray Vectors", "Dragonscale Boots"],
  groups: [
    { style: "default", lines: [[{ t: "Armour: ", s: "default" }, { t: "71", s: "value" }]] },
    { style: "mod", lines: [[{ t: "+40% to ", s: "mod" }, { t: "Lightning", s: "lightning" }], []] },
  ],
};

describe("ItemTooltip", () => {
  it("draws the frame, both header lines and coloured segments", () => {
    const html = renderToStaticMarkup(<ItemTooltip card={card} />);

    expect(html).toContain('data-frame="unique"');
    expect(html).toContain('data-lines="double"');
    expect(html).toContain("Dragonscale Boots");
    expect(html).toContain('<span data-style="value">71</span>');
    expect(html).toContain('<span data-style="lightning">Lightning</span>');
    expect(html.match(/class="poe-group"/g)).toHaveLength(2);
  });
});

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AtlasTable } from "./AtlasTable";
import type { AtlasTree } from "./types";

const base: AtlasTree = {
  tree_version: "3.30.0c",
  points_total: 150,
  points_used: 142,
  points_unspent: 8,
  mechanics: [
    { mechanic: "Essence", points: 35, notables: ["Prolific Essence"] },
    { mechanic: "travel", points: 55, notables: [] },
  ],
  focus: ["Essence"],
  keystones: [],
};

describe("AtlasTable", () => {
  it("shows the points per mechanic for a tree without a plan", () => {
    const html = renderToStaticMarkup(<AtlasTable atlas={base} />);

    expect(html).toContain("Your atlas tree");
    expect(html).toContain("142 of 150 points spent (8 unspent)");
    expect(html).toContain("Prolific Essence");
    expect(html).toContain("travel and small nodes");
  });

  it("shows what to drop, what to take and the planned tree's link", () => {
    const atlas: AtlasTree = {
      ...base,
      plan: {
        farm: ["Essence", "Delirium"],
        kept_mechanics: ["Delirium", "Essence", "Maps"],
        remove: [{ mechanic: "Shrines", points: 18, notables: ["Supplication"] }],
        points_freed: 18,
        add: [
          { name: "Crystal Resonance", kind: "notable", mechanic: "Essence", stats: "Calcified Maps", cost: 1 },
          { name: "Essence small nodes", small_nodes: 3 },
        ],
        points_after: 150,
        points_left: 0,
        keystones_in_reach: [{ name: "Wandering Path", stats: "", cost: 2 }],
      },
      link: "https://poeplanner.com/atlas-tree/abc",
    };
    const html = renderToStaticMarkup(<AtlasTable atlas={atlas} />);

    expect(html).toContain("Atlas tree for Essence + Delirium");
    expect(html).toContain("Drop (18 points back)");
    expect(html).toContain("Crystal Resonance");
    expect(html).toContain("Wandering Path (2)");
    expect(html).toContain('href="https://poeplanner.com/atlas-tree/abc"');
    expect(html).not.toContain("points left");
  });
});

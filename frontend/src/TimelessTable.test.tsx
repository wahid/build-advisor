import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TimelessTable } from "./TimelessTable";
import type { Timeless } from "./types";

const timeless: Timeless = {
  jewel: "Lethal Pride",
  conqueror: "Akoya",
  mode: "balanced",
  verdict: "Seed 12345 in the socket near Ironwood: +4.2% score on the current tree (not rebuilt).",
  current: null,
  best: {
    seed: 12345,
    socket_near: "Ironwood",
    socket_allocated: true,
    socket_path_cost: 0,
    extra_points: 2,
    score_gain_pct: 4.2,
    change_pct: { dps: 6.1, ehp: -1.5, life: 0 },
    notables: [
      { node: "Juggernaut", becomes: "Chainbreaker", allocated: true, points_to_reach: 0, value_pct: 2.1 },
      { node: "Iron Grip", becomes: null, allocated: false, points_to_reach: 2, value_pct: 0 },
    ],
    pick_up: [],
    trade_url: "https://www.pathofexile.com/trade/search/Mirage?q=%7B%7D",
    trade_any_url: "https://www.pathofexile.com/trade/search/Mirage?q=%7B%22a%22%7D",
  },
  alternatives: [],
  applied: null,
  sockets_scanned: 5,
  seeds_per_socket: 8001,
  top_seeds_url: "",
  note: "",
};

describe("TimelessTable", () => {
  it("shows the best seed, what it creates and its trade searches", () => {
    const html = renderToStaticMarkup(<TimelessTable timeless={timeless} />);

    expect(html).toContain("Lethal Pride (Akoya)");
    expect(html).toContain("Seed 12345");
    expect(html).toContain("Juggernaut → Chainbreaker");
    expect(html).not.toContain("Iron Grip");
    expect(html).toContain("+4.2%");
    expect(html).toContain("-1.5%");
    expect(html).toContain('href="https://www.pathofexile.com/trade/search/Mirage?q=%7B%7D"');
    expect(html).toContain("any conqueror");
    expect(html).not.toContain("now in your build");
  });
});

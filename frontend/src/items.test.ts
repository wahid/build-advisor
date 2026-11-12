import { describe, expect, it } from "vitest";

import { applyEvent, mergeLeveling, newTurn, questionFor, titleFor, toHistory } from "./conversation";
import { isItemText, itemName } from "./items";

const RING = `Item Class: Rings
Rarity: Rare
Storm Loop
Two-Stone Ring
--------
+52 to maximum Life`;

describe("items pasted from the game", () => {
  it("recognises the game's item text and names it", () => {
    expect(isItemText(RING)).toBe(true);
    expect(isItemText("Rarity: Unique\nHeadhunter\nLeather Belt\n--------\n+40 to Str")).toBe(true);
    expect(isItemText("What does Rarity: do?")).toBe(false);
    expect(itemName(RING)).toBe("Storm Loop, Two-Stone Ring");
    expect(itemName("Rarity: Currency\nChaos Orb\n--------\nStack Size: 1/20")).toBe("Chaos Orb");
  });

  it("keeps the item on the turn and names it in the history", () => {
    let turn = newTurn("t1", "", RING);
    const item = { name: "Storm Loop", base: "Two-Stone Ring", item_class: "Rings", rarity: "rare", card: { frame: "rare", header: [], groups: [] } };
    turn = applyEvent(turn, { type: "item", item });
    turn = applyEvent(turn, { type: "item_check", item, slot: "Ring 2", replaces: "", rows: [], tried: ["Ring 1", "Ring 2"] });
    turn = applyEvent(turn, { type: "delta", text: "An upgrade." });
    turn = applyEvent(turn, { type: "done", cited: [], patch: "" });

    expect(turn.itemCheck?.slot).toBe("Ring 2");
    expect("type" in (turn.itemCheck ?? {})).toBe(false);
    expect(questionFor(turn)).toBe("(pasted item: Storm Loop, Two-Stone Ring)");
    expect(toHistory([turn])[0].question).toBe("(pasted item: Storm Loop, Two-Stone Ring)");
    expect(titleFor([turn])).toBe("Storm Loop, Two-Stone Ring");
  });
});

describe("leveling lookups", () => {
  it("merge into one table ordered by when the gems come", () => {
    const gem = (name: string, act: number, level: number) => ({
      gem: name,
      known: true,
      required_level: level,
      quest_reward: { act, quest: "Q" },
      vendors: [],
    });
    const first = mergeLeveling(undefined, { class_name: "Duelist", gems: [gem("Cyclone", 3, 28)], note: "" });
    const both = mergeLeveling(first, { class_name: "", gems: [gem("Dash", 1, 4), gem("Cyclone", 3, 28)], note: "n" });

    expect(both.gems.map((g) => g.gem)).toEqual(["Dash", "Cyclone"]);
    expect(both.class_name).toBe("Duelist");
  });
});

import { describe, expect, it } from "vitest";

import { guideByline } from "./SourceCard";

describe("Maxroll guide attribution", () => {
  it("names Maxroll, the author and the last-updated date", () => {
    expect(guideByline({ author: "Helm Breaker", updated: "2026-11-13" })).toBe(
      "Source: Maxroll · by Helm Breaker · updated 13 Nov 2026",
    );
  });

  it("still names Maxroll without a byline or date", () => {
    expect(guideByline({})).toBe("Source: Maxroll");
  });
});

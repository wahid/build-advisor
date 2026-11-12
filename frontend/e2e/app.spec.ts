import { expect, test, type Page } from "@playwright/test";

async function ask(page: Page, question: string) {
  await page.getByLabel("Your question").fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.locator("[aria-busy=true]")).toHaveCount(0);
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => window.localStorage.clear());
  await page.reload();
});

test("an answer renders with citations, a table, a badge and sources", async ({ page }) => {
  await ask(page, "How does poison stack compared to bleed?");

  const answer = page.locator(".answer-text").last();
  await expect(answer.locator("table td").first()).toHaveText("Poison");
  await expect(answer.locator("a.cite")).toHaveCount(3);
  await expect(answer.locator(".knowledge")).toHaveText("general game knowledge");

  // Sources are folded until opened.
  const sources = page.locator("details.sources");
  await expect(sources).not.toHaveAttribute("open");
  await sources.locator("summary").click();
  await expect(sources.locator(".tooltip")).toHaveCount(3);

  // A known gem name has a hover card.
  await answer.locator(".entity-name").hover();
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toContainText("Inflicts additional poisons");
  await expect(tooltip.locator(".poe-tooltip")).toHaveAttribute("data-frame", "gem");
});

test("feedback can say what was wrong", async ({ page }) => {
  await ask(page, "How does poison stack?");

  await page.getByRole("button", { name: "No", exact: true }).click();
  await page.getByLabel("What was wrong or missing? (optional)").fill("Missed Crimson Dance");
  await page.getByRole("button", { name: "Send feedback" }).click();
  await expect(page.locator(".feedback-thanks")).toContainText("Thanks");
});

test("a follow-up sends the earlier turn", async ({ page, request }) => {
  await ask(page, "How does poison stack?");
  await ask(page, "And bleed?");

  const sent = await (await request.get("/api/__last__")).json();
  expect(sent.question).toBe("And bleed?");
  expect(sent.history).toHaveLength(1);
  expect(sent.history[0].question).toBe("How does poison stack?");
});

test("two build links compare the builds", async ({ page }) => {
  await ask(page, "Which deals more damage, https://pobb.in/aaa or https://pobb.in/bbb?");

  await expect(page.locator(".comparison-table")).toContainText("13.08M");
  await expect(page.locator(".build-chip-label")).toHaveText(["Build attached", "Comparing with build B"]);
});

test("an item pasted from the game is tried on the build", async ({ page, request }) => {
  await page.goto("/");
  const ring = "Item Class: Rings\nRarity: Rare\nStorm Loop\nTwo-Stone Ring\n--------\n+52 to maximum Life";
  await page.locator("#question").focus();
  await page.evaluate((text) => {
    const data = new DataTransfer();
    data.setData("text/plain", text);
    document.querySelector("#question")!.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }));
  }, ring);
  await expect(page.locator(".item-chip")).toContainText("Storm Loop, Two-Stone Ring");
  await expect(page.locator("#question")).toHaveValue("");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  await expect(page.locator(".pasted-item .poe-tooltip")).toHaveAttribute("data-frame", "rare");
  await expect(page.getByRole("region", { name: "Item tried on your build" })).toContainText("Ring 2 (empty)");
  const sent = await (await request.get("/api/__last__")).json();
  expect(sent.item).toBe(ring);
  expect(sent.question).toBe("");
});

test("a slow tool shows how far it is", async ({ page }) => {
  await page.goto("/");
  await page.locator("#question").fill("What is the strongest slam for a Slayer?");
  await page.keyboard.press("Enter");

  const step = page.locator(".pob-step[data-status=running]");
  await expect(step.locator(".pob-count")).toHaveText(/^\d of 3: \w+/);
  await expect(page.locator(".pob-step[data-status=ok]")).toContainText("Ranked skill gems");
});

test("the last question can be edited and asked again in place", async ({ page }) => {
  await ask(page, "How does poison stak?");

  await page.locator(".bubble-row").hover();
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Edit your question").fill("How does poison stack?");
  await page.getByRole("button", { name: "Ask again" }).click();
  await expect(page.locator("[aria-busy=true]")).toHaveCount(0);

  await expect(page.locator(".bubble")).toHaveText(["How does poison stack?"]);
});

test("chats stay in the sidebar after a reload", async ({ page }) => {
  await ask(page, "How does poison stack?");
  await page.locator(".sidebar").getByRole("button", { name: "New chat" }).click();
  await ask(page, "What does Crimson Dance do?");

  await page.reload();
  await expect(page.locator(".chat-open")).toHaveText(["What does Crimson Dance do?", "How does poison stack?"]);
  await page.getByRole("button", { name: "How does poison stack?", exact: true }).click();
  await expect(page.locator(".bubble")).toHaveText(["How does poison stack?"]);
});

test("the daily limit shows when it opens again and stops asking", async ({ page }) => {
  await ask(page, "LIMIT please");

  await expect(page.getByRole("status")).toContainText("opens again in");
  await page.getByLabel("Your question").fill("Another question");
  await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeDisabled();
});

test("the How it works page shows live numbers", async ({ page }) => {
  await page.goto("/how-it-works");

  await expect(page.getByRole("heading", { name: "How Build Advisor works" })).toBeVisible();
  await expect(page.locator(".item-card-mods").first()).toContainText("96% of 60 evaluation cases pass");
});

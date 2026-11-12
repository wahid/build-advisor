import { expect, test } from "@playwright/test";

test("on a phone the chats slide in and nothing scrolls sideways", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Show chats" }).click();
  await expect(page.locator(".sidebar")).toHaveAttribute("data-open", "true");
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(page.viewportSize()!.width);
});

/** Items copied from the game with Ctrl+C: "Item Class: …", "Rarity: …", name, base, then "--------" sections. */

const ITEM_START = /^(Item Class|Rarity):/m;
export const MAX_ITEM_TEXT = 6000;

/** Whether pasted text is an item copied from the game. */
export function isItemText(text: string): boolean {
  const start = text.search(ITEM_START);
  return start >= 0 && start < 200 && text.includes("--------", start) && text.length <= MAX_ITEM_TEXT;
}

/** The item's name (and base, when it has a separate one), for the chip before it's sent. */
export function itemName(text: string): string {
  const head = text.replace(/\r\n/g, "\n").split("--------")[0];
  const names = head
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !/^(Item Class|Rarity):/.test(line));
  if (!names.length) return "Item";
  return names.length > 1 && names[1] !== names[0] ? `${names[0]}, ${names[1]}` : names[0];
}

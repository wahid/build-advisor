import type { Leveling, LevelingGem } from "./types";

function where(act: number | null, text: string): string {
  return act ? `Act ${act}: ${text}` : text;
}

function vendors(gem: LevelingGem): string {
  const seen = new Set<string>();
  const parts: string[] = [];
  for (const vendor of gem.vendors) {
    if (seen.has(vendor.npc)) continue;
    seen.add(vendor.npc);
    parts.push(where(vendor.act, vendor.npc));
  }
  return parts.slice(0, 2).join(", ");
}

/** When each gem becomes available while leveling: its level, quest reward and vendors. */
export function LevelingTable({ leveling }: { leveling: Leveling }) {
  if (!leveling.gems.length) return null;
  return (
    <section className="comparison leveling" aria-label="When you get the gems">
      <h3 className="pob-heading">When you get the gems{leveling.class_name && ` as a ${leveling.class_name}`}</h3>
      <table className="comparison-table">
        <thead>
          <tr>
            <th scope="col">Gem</th>
            <th scope="col">Level</th>
            <th scope="col">Quest reward</th>
            <th scope="col">Or buy from</th>
          </tr>
        </thead>
        <tbody>
          {leveling.gems.map((gem) => (
            <tr key={gem.gem}>
              <th scope="row">{gem.gem}</th>
              <td>{gem.required_level ?? "–"}</td>
              <td title={gem.quest_reward?.quest}>
                {gem.quest_reward ? where(gem.quest_reward.act, gem.quest_reward.quest) : "–"}
              </td>
              <td title={gem.vendors.map((v) => `${v.npc}, after ${v.after_quest}`).join("\n")}>
                {gem.known ? vendors(gem) || "–" : "Not in the wiki's quest tables"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="comparison-note">From the wiki's quest reward and vendor tables.</p>
    </section>
  );
}

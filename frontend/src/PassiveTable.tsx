import type { PassiveRanking } from "./types";

const FOCUS = { balanced: "damage and toughness", damage: "damage first", defence: "toughness first" };

function percent(value: number): string {
  if (value === 0) return "–";
  return `${value > 0 ? "+" : ""}${value}%`;
}

/** Passive notables ranked in Path of Building: what to take next, or what gives the least. */
export function PassiveTable({ ranking }: { ranking: PassiveRanking }) {
  if (!ranking.rows.length) return null;
  const take = ranking.mode === "take";
  return (
    <section className="comparison passives" aria-label={take ? "Passives to take next" : "Passives that give the least"}>
      <h3 className="pob-heading">{take ? "Best passives to take next" : "Passives that give the least"}</h3>
      <p className="comparison-note">
        {take
          ? `Ranked for ${FOCUS[ranking.focus]} per point, within ${ranking.max_path_cost} points of your tree (${ranking.points_remaining} unspent).`
          : `No points left: these allocated picks give the least for ${FOCUS[ranking.focus]}, per point refunded.`}
      </p>
      <table className="comparison-table">
        <thead>
          <tr>
            <th scope="col">{take ? "Notable" : "Allocated"}</th>
            <th scope="col">Points</th>
            <th scope="col">Damage</th>
            <th scope="col">Toughness</th>
          </tr>
        </thead>
        <tbody>
          {ranking.rows.map((row) => (
            <tr key={row.name}>
              <th scope="row">
                <span className="passive-name">
                  {row.name}
                  {row.type === "Keystone" && <span className="passive-keystone">keystone</span>}
                </span>
                {row.stats.length > 0 && <span className="passive-stats">{row.stats.join("; ")}</span>}
              </th>
              <td>{row.points}</td>
              <td data-better={take && row.dps_pct > 0 ? "true" : undefined}>{percent(row.dps_pct)}</td>
              <td data-better={take && row.ehp_pct > 0 ? "true" : undefined}>{percent(row.ehp_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

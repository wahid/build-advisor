import { TradeLinks } from "./TradeLinks";
import type { Upgrades } from "./types";

function percent(value: number): string {
  if (value === 0) return "–";
  return `${value > 0 ? "+" : ""}${value}%`;
}

function price(chaos: number, divine: number | null): string {
  if (divine != null && divine >= 1) return `${divine.toFixed(1)} div`;
  return `${chaos >= 10 ? Math.round(chaos) : chaos} c`;
}

function resists(changes: Record<string, number>): string {
  return Object.entries(changes)
    .map(([name, change]) => `${change > 0 ? "+" : ""}${change} ${name}`)
    .join(", ");
}

/** Unique items within the budget, tried on the build in Path of Building. */
export function UpgradesTable({ upgrades }: { upgrades: Upgrades }) {
  const budget = `${upgrades.budget} ${upgrades.currency}`;
  const rares = <TradeLinks searches={upgrades.rare_searches ?? []} heading={`Rare items to look for, up to ${budget}`} />;
  if (!upgrades.rows.length) {
    return (
      <>
        <p className="comparison-note">
          None of the {upgrades.tried} unique items under {budget} improve this build.
        </p>
        {rares}
      </>
    );
  }
  return (
    <>
    <section className="comparison upgrades" aria-label="Upgrades within your budget">
      <h3 className="pob-heading">Best unique items for {budget}</h3>
      <p className="comparison-note">
        {upgrades.tried} items tried on your build in Path of Building. Prices from poe.ninja
        {upgrades.league && `, ${upgrades.league} league`}.
        {upgrades.not_tried_time_limit > 0 && ` ${upgrades.not_tried_time_limit} cheaper ones weren't tried in time.`}
      </p>
      <table className="comparison-table">
        <thead>
          <tr>
            <th scope="col">Item</th>
            <th scope="col">Price</th>
            <th scope="col">Damage</th>
            <th scope="col">Toughness</th>
          </tr>
        </thead>
        <tbody>
          {upgrades.rows.map((row) => (
            <tr key={`${row.name}-${row.slot}`}>
              <th scope="row">
                <span className="passive-name" data-type="unique">
                  {row.name}
                </span>
                <span className="passive-stats">
                  {row.slot}
                  {row.replaces ? `, replaces ${row.replaces}` : " (empty)"}
                  {Object.keys(row.resists).length > 0 && `; resistances: ${resists(row.resists)}`}
                </span>
              </th>
              <td>{price(row.chaos, row.divine)}</td>
              <td data-better={row.dps_pct > 0 ? "true" : row.dps_pct < 0 ? "false" : undefined}>{percent(row.dps_pct)}</td>
              <td data-better={row.ehp_pct > 0 ? "true" : row.ehp_pct < 0 ? "false" : undefined}>{percent(row.ehp_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
    {rares}
    </>
  );
}

import type { AtlasAddition, AtlasMechanic, AtlasTree } from "./types";

function notables(row: AtlasMechanic): string {
  return row.notables.length ? row.notables.join(", ") : "travel and small nodes";
}

function addition(row: AtlasAddition): string {
  if (row.small_nodes !== undefined) return `${row.small_nodes}`;
  return `${row.cost ?? ""}`;
}

/** An atlas tree read from a link: points per mechanic, and the plan for a farm. */
export function AtlasTable({ atlas }: { atlas: AtlasTree }) {
  const plan = atlas.plan;
  return (
    <section className="comparison atlas" aria-label="Atlas tree">
      <h3 className="pob-heading">{plan ? `Atlas tree for ${plan.farm.join(" + ")}` : "Your atlas tree"}</h3>
      <p className="comparison-note">
        {atlas.mechanics
          ? `${atlas.points_used} of ${atlas.points_total} points spent (${atlas.points_unspent} unspent), atlas tree ${atlas.tree_version}.`
          : `Planned from scratch on atlas tree ${atlas.tree_version}.`}
        {plan && ` Points are counted exactly; map sustain is always kept.`}
      </p>

      {atlas.mechanics && !plan && (
        <table className="comparison-table">
          <thead>
            <tr>
              <th scope="col">Mechanic</th>
              <th scope="col">Points</th>
            </tr>
          </thead>
          <tbody>
            {atlas.mechanics.map((row) => (
              <tr key={row.mechanic}>
                <th scope="row">
                  <span className="passive-name">{row.mechanic}</span>
                  <span className="passive-stats">{notables(row)}</span>
                </th>
                <td>{row.points}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {plan && plan.remove.length > 0 && (
        <table className="comparison-table">
          <thead>
            <tr>
              <th scope="col">Drop ({plan.points_freed} points back)</th>
              <th scope="col">Points</th>
            </tr>
          </thead>
          <tbody>
            {plan.remove.map((row) => (
              <tr key={row.mechanic}>
                <th scope="row">
                  <span className="passive-name">{row.mechanic}</span>
                  <span className="passive-stats">{notables(row)}</span>
                </th>
                <td>{row.points}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {plan && plan.add.length > 0 && (
        <table className="comparison-table">
          <thead>
            <tr>
              <th scope="col">Take, cheapest first</th>
              <th scope="col">Points</th>
            </tr>
          </thead>
          <tbody>
            {plan.add.map((row, index) => (
              <tr key={`${row.name}-${index}`}>
                <th scope="row">
                  <span className="passive-name">
                    {row.name}
                    {row.mechanic && <span className="passive-keystone">{row.mechanic}</span>}
                  </span>
                  {row.stats && <span className="passive-stats">{row.stats}</span>}
                </th>
                <td data-better="true">{addition(row)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {plan && plan.keystones_in_reach.length > 0 && (
        <p className="comparison-note">
          Keystones in reach (not added, they have drawbacks):{" "}
          {plan.keystones_in_reach.map((k) => `${k.name} (${k.cost})`).join(", ")}.
        </p>
      )}
      {plan && plan.points_left > 0 && (
        <p className="comparison-note">
          {plan.points_left} points left: nothing more of this farm or map sustain is in reach.
        </p>
      )}
      {atlas.notes?.map((note) => (
        <p className="comparison-note" key={note}>
          {note}
        </p>
      ))}
      {atlas.link && (
        <p>
          <a href={atlas.link} target="_blank" rel="noreferrer" className="trade-link">
            Open the planned tree on poeplanner
          </a>
        </p>
      )}
    </section>
  );
}

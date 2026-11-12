import type { BuildSummary, Comparison } from "./types";

function describe(build: BuildSummary): string {
  const parts = [build.mainSkill, build.ascendancy ?? build.className, build.level ? `level ${build.level}` : ""];
  return parts.filter(Boolean).join(", ");
}

function format(value: number): string {
  const size = Math.abs(value);
  if (size >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (size >= 10_000) return `${(value / 1000).toFixed(1)}k`;
  return Number.isInteger(value) ? value.toLocaleString("en-US") : value.toFixed(2);
}

/** Path of Building's numbers for two builds, side by side. */
export function ComparisonTable({ comparison }: { comparison: Comparison }) {
  if (!comparison.rows.length) return null;
  return (
    <section className="comparison" aria-label="Build comparison">
      <h3 className="pob-heading">Compared in Path of Building</h3>
      <table className="comparison-table">
        <thead>
          <tr>
            <th scope="col">Stat</th>
            <th scope="col">
              Build A<span className="comparison-build">{describe(comparison.a)}</span>
            </th>
            <th scope="col">
              Build B<span className="comparison-build">{describe(comparison.b)}</span>
            </th>
            <th scope="col">B vs A</th>
          </tr>
        </thead>
        <tbody>
          {comparison.rows.map((row) => {
            const better = row.change_pct === null || row.change_pct === 0
              ? undefined
              : (row.change_pct > 0) === row.higher_is_better;
            return (
              <tr key={row.stat}>
                <th scope="row">{row.label}</th>
                <td>{format(row.a)}</td>
                <td>{format(row.b)}</td>
                <td data-better={better === undefined ? undefined : String(better)}>
                  {row.change_pct === null ? "–" : `${row.change_pct > 0 ? "+" : ""}${row.change_pct}%`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

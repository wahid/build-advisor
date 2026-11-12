import type { ReactNode } from "react";

import type { BuildSummary, Comparison, ComparisonRow, ItemCheck } from "./types";

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

interface StatTableProps {
  label: string;
  heading: string;
  columns: [ReactNode, ReactNode, string];
  rows: ComparisonRow[];
  note?: ReactNode;
}

/** Path of Building's numbers before (a) and after (b), with the change. */
function StatTable({ label, heading, columns, rows, note }: StatTableProps) {
  return (
    <section className="comparison" aria-label={label}>
      <h3 className="pob-heading">{heading}</h3>
      {note && <p className="comparison-note">{note}</p>}
      <table className="comparison-table">
        <thead>
          <tr>
            <th scope="col">Stat</th>
            <th scope="col">{columns[0]}</th>
            <th scope="col">{columns[1]}</th>
            <th scope="col">{columns[2]}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
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

/** Path of Building's numbers for two builds, side by side. */
export function ComparisonTable({ comparison }: { comparison: Comparison }) {
  if (!comparison.rows.length) return null;
  return (
    <StatTable
      label="Build comparison"
      heading="Compared in Path of Building"
      rows={comparison.rows}
      columns={[
        <>
          Build A<span className="comparison-build">{describe(comparison.a)}</span>
        </>,
        <>
          Build B<span className="comparison-build">{describe(comparison.b)}</span>
        </>,
        "B vs A",
      ]}
    />
  );
}

/** A pasted item tried on the build: the stats that change. */
export function ItemCheckTable({ check }: { check: ItemCheck }) {
  const where = check.replaces ? `in ${check.slot}, replacing ${check.replaces}` : `in ${check.slot} (empty)`;
  const others = check.tried.filter((slot) => slot !== check.slot);
  if (!check.rows.length) {
    return <p className="comparison-note">Tried on your build {where}: none of the main stats change.</p>;
  }
  return (
    <StatTable
      label="Item tried on your build"
      heading="Tried on your build in Path of Building"
      note={`Equipped ${where}${others.length ? `; better than ${others.join(", ")}` : ""}.`}
      rows={check.rows}
      columns={["Now", "With this item", "Change"]}
    />
  );
}

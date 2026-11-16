import type { Health } from "./types";

const STATUS = { bad: "Fix", warn: "Check", ok: "OK" } as const;

/** The build health check: each usual problem with its verdict, worst first. */
export function HealthCard({ health }: { health: Health }) {
  const problems = health.bad + health.warn;
  return (
    <section className="comparison health" aria-label="Build health check">
      <h3 className="pob-heading">Build health check</h3>
      <p className="comparison-note">
        {problems === 0
          ? `All ${health.ok} checks pass.`
          : `${health.bad} to fix, ${health.warn} to check, ${health.ok} fine.`}{" "}
        From Path of Building.
      </p>
      <ul className="health-list">
        {health.checks.map((check) => (
          <li key={check.id} className="health-item" data-status={check.status}>
            <span className="health-status">{STATUS[check.status]}</span>
            <span className="health-label">{check.label}</span>
            <span className="health-detail">{check.detail}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

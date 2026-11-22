import type { Timeless, TimelessSeed } from "./types";

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return `${value > 0 ? "+" : ""}${value}%`;
}

function created(seed: TimelessSeed): string {
  const changed = seed.notables.filter((n) => n.becomes);
  if (!changed.length) return "";
  return changed
    .slice(0, 4)
    .map((n) => `${n.node} → ${n.becomes}${n.allocated ? "" : ` (${n.points_to_reach ?? "?"} pts)`}`)
    .join("; ");
}

function Row({ seed, timeless }: { seed: TimelessSeed; timeless: Timeless }) {
  return (
    <tr>
      <th scope="row">
        <span className="passive-name">
          Seed {seed.seed}
          <span className="passive-keystone">
            {seed.replaces_current ? "your jewel's socket" : `near ${seed.socket_near}`}
          </span>
        </span>
        <span className="passive-stats">
          {created(seed)}
          {seed.extra_points > 0 && ` · ${seed.extra_points} extra points`}
          {seed.breaks?.length ? ` · breaks ${seed.breaks.map((b) => b.stat).join(", ")}` : ""}
        </span>
        <span className="passive-stats">
          {seed.trade_url && (
            <a href={seed.trade_url} target="_blank" rel="noreferrer" className="trade-link">
              Trade: {timeless.conqueror}
            </a>
          )}
          {seed.trade_any_url && (
            <>
              {" · "}
              <a href={seed.trade_any_url} target="_blank" rel="noreferrer" className="trade-link">
                any conqueror
              </a>
            </>
          )}
        </span>
      </th>
      <td data-better={seed.score_gain_pct > 0 ? "true" : undefined}>{percent(seed.score_gain_pct)}</td>
      <td>{percent(seed.change_pct.dps)}</td>
      <td>{percent(seed.change_pct.ehp)}</td>
    </tr>
  );
}

/** The best timeless jewel seeds and sockets for the build, with trade searches. */
export function TimelessTable({ timeless }: { timeless: Timeless }) {
  const seeds = [timeless.best, ...timeless.alternatives].filter((s): s is TimelessSeed => s !== null);
  return (
    <section className="comparison timeless" aria-label="Timeless jewel">
      <h3 className="pob-heading">
        {timeless.jewel} ({timeless.conqueror})
      </h3>
      <p className="comparison-note">
        {timeless.verdict} Every seed tried in {timeless.sockets_scanned} sockets, scored for {timeless.mode} on your
        current tree (an estimate: the tree isn't rebuilt around the jewel).
        {timeless.applied && " The best one is now in your build."}
      </p>
      {timeless.current && (
        <p className="comparison-note">
          You have {timeless.current.jewel}
          {timeless.current.seed !== null && ` seed ${timeless.current.seed}`}
          {timeless.current.conqueror && ` (${timeless.current.conqueror})`} socketed: the gains below are on top of it.
        </p>
      )}
      {seeds.length > 0 && (
        <table className="comparison-table">
          <thead>
            <tr>
              <th scope="col">Seed and socket</th>
              <th scope="col">Score</th>
              <th scope="col">Damage</th>
              <th scope="col">eHP</th>
            </tr>
          </thead>
          <tbody>
            {seeds.map((seed) => (
              <Row key={`${seed.seed}-${seed.socket_near}`} seed={seed} timeless={timeless} />
            ))}
          </tbody>
        </table>
      )}
      {timeless.top_seeds_url && (
        <p>
          <a href={timeless.top_seeds_url} target="_blank" rel="noreferrer" className="trade-link">
            Trade search for all these seeds
          </a>
        </p>
      )}
    </section>
  );
}

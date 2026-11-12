import { useEffect, useState } from "react";

export interface ToolStep {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  status: "running" | "ok" | "failed";
  error?: string;
  /** When the step started (ms since the epoch), for the seconds counter. */
  startedAt?: number;
  /** How far a slow tool is: done of total, and what it's on. */
  progress?: { done: number; total: number; label: string };
}

/** Seconds since `since`, updated every second while mounted. */
function useElapsed(since: number | undefined): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return since ? Math.max(0, Math.floor((now - since) / 1000)) : 0;
}

/** "14 of 40: Cyclone", and the seconds so far, for a step that's still running. */
function RunningNote({ step }: { step: ToolStep }) {
  const seconds = useElapsed(step.startedAt);
  const progress = step.progress;
  return (
    <span className="pob-progress">
      {progress && progress.total > 1 && (
        <>
          {" "}
          <span className="pob-count">
            {Math.min(progress.done + 1, progress.total)} of {progress.total}
            {progress.label && `: ${progress.label}`}
          </span>
        </>
      )}
      {seconds >= 2 && <span className="pob-seconds"> {seconds} s</span>}
      {progress && progress.total > 1 && (
        <span className="pob-bar" aria-hidden="true">
          <span style={{ width: `${Math.round((progress.done / progress.total) * 100)}%` }} />
        </span>
      )}
    </span>
  );
}

const LOOKUPS = new Set(["web_search", "quest_rewards"]); // not Path of Building

// Past tense once a step worked; the infinitive for "Couldn't ..." when it failed.
const LABELS: Record<string, [done: string, failed: string]> = {
  load_build: ["Loaded your build", "load your build"],
  reuse_build: ["Used your build, still loaded", "use your loaded build"],
  compare_builds: ["Loaded the other build and compared them", "compare the builds"],
  check_item: ["Tried your item on the build", "try your item on the build"],
  rank_anoints: ["Ranked anoints", "rank anoints"],
  rank_gear_upgrades: ["Found the best gear upgrades", "find gear upgrades"],
  plan_leveling: ["Planned the leveling trees", "plan the leveling trees"],
  list_item_slots: ["Looked up item slots", "look up item slots"],
  quest_rewards: ["Looked up quest rewards and vendors", "look up quest rewards"],
  new_build: ["Started a new build", "start a new build"],
  get_build_summary: ["Read the build summary", "read the build summary"],
  get_stats: ["Read stats", "read stats"],
  get_skills: ["Read the gem setup", "read the gem setup"],
  get_items: ["Read the gear", "read the gear"],
  get_passive_tree: ["Read the passive tree", "read the passive tree"],
  get_config: ["Read the configuration", "read the configuration"],
  get_warnings: ["Checked for problems", "check for problems"],
  explain_stat: ["Broke down a stat", "break down a stat"],
  evaluate_scenarios: ["Compared mapping and bossing", "compare mapping and bossing"],
  rank_support_gems: ["Ranked support gems", "rank support gems"],
  rank_skill_gems: ["Ranked skill gems by damage", "rank skill gems"],
  rank_passives: ["Ranked passive notables", "rank passive notables"],
  compare_changes: ["Tested a change", "test a change"],
  apply_changes: ["Changed the build", "change the build"],
  undo_last_change: ["Undid the last change", "undo the last change"],
  auto_allocate_passives: ["Allocated passive points", "allocate passive points"],
  search_gems: ["Looked up gems", "look up gems"],
  search_uniques: ["Looked up unique items", "look up unique items"],
  list_classes: ["Looked up classes", "look up classes"],
  list_ascendancy_notables: ["Looked up ascendancy notables", "look up ascendancy notables"],
  list_keystones: ["Looked up keystones", "look up keystones"],
  find_passive_nodes: ["Searched the passive tree", "search the passive tree"],
  fix_gaps: ["Fixed resistance and attribute gaps", "fix resistance and attribute gaps"],
  export_build: ["Exported the build", "export the build"],
  price_check: ["Checked prices on poe.ninja", "check prices on poe.ninja"],
  web_search: ["Searched the web", "search the web"],
  suggest_passives: ["Ranked passives for damage and toughness", "rank passives"],
};

// While they run, the slow steps say what they're doing.
const RUNNING: Record<string, string> = {
  load_build: "Loading your build",
  compare_builds: "Comparing the builds",
  check_item: "Trying your item on the build",
  rank_skill_gems: "Ranking skill gems by damage",
  rank_support_gems: "Ranking support gems",
  rank_passives: "Ranking passive notables",
  suggest_passives: "Ranking passives for damage and toughness",
  rank_gear_upgrades: "Looking for gear upgrades",
  rank_anoints: "Ranking anoints",
  auto_allocate_passives: "Allocating passive points",
  plan_leveling: "Planning the leveling trees",
  evaluate_scenarios: "Comparing mapping and bossing",
  quest_rewards: "Looking up quest rewards and vendors",
  web_search: "Searching the web",
};

export function stepLabel(
  name: string,
  failed = false,
  args: Record<string, unknown> = {},
  running = false,
): string {
  if (running && RUNNING[name]) {
    return name === "web_search" && typeof args.query === "string" && args.query
      ? `Searching the web for “${args.query}”`
      : RUNNING[name];
  }
  if (name === "web_search" && typeof args.query === "string" && args.query) {
    return failed ? `Couldn't search the web for “${args.query}”` : `Searched the web for “${args.query}”`;
  }
  const label = LABELS[name];
  if (!label) return `${failed ? "Couldn't run " : ""}${name.replace(/_/g, " ")}`;
  return failed ? `Couldn't ${label[1]}` : label[0];
}

/** What the tools (Path of Building, web search) did for this answer, step by step. */
export function PobSteps({ steps }: { steps: ToolStep[] }) {
  if (!steps.length) return null;
  const pob = steps.some((step) => !LOOKUPS.has(step.name));
  const web = steps.some((step) => step.name === "web_search");
  const heading =
    pob && web
      ? "Path of Building and the web"
      : pob
        ? "Calculated with Path of Building"
        : web
          ? "Searched the web"
          : "Looked it up";
  return (
    <section className="pob" aria-label={heading}>
      <h3 className="pob-heading">{heading}</h3>
      <ol className="pob-steps">
        {steps.map((step) => (
          <li key={step.id} className="pob-step" data-status={step.status}>
            <span className="pob-marker" aria-hidden="true" />
            <span>
              {stepLabel(step.name, step.status === "failed", step.arguments, step.status === "running")}
              {step.status === "running" && (
                <>
                  <span className="visually-hidden"> (running)</span>
                  <RunningNote step={step} />
                </>
              )}
              {step.status === "failed" && <span className="pob-error">: {step.error || "failed"}</span>}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** The share code of a build the model created or changed, ready to import into PoB. */
export function PobExport({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className="pob-export" aria-label="Path of Building code">
      <div className="pob-export-head">
        <h3 className="pob-heading">Path of Building code</h3>
        <button type="button" className="pob-copy" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy code"}
        </button>
      </div>
      <p className="pob-export-hint">In Path of Building: Import/Export Build, paste this code, then Import.</p>
      <textarea className="pob-code" readOnly rows={3} value={code} onFocus={(e) => e.currentTarget.select()} />
    </section>
  );
}

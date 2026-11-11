import { useState } from "react";

export interface ToolStep {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  status: "running" | "ok" | "failed";
  error?: string;
}

// Past tense once a step worked; the infinitive for "Couldn't ..." when it failed.
const LABELS: Record<string, [done: string, failed: string]> = {
  load_build: ["Loaded your build", "load your build"],
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
};

export function stepLabel(name: string, failed = false): string {
  const label = LABELS[name];
  if (!label) return `${failed ? "Couldn't run " : ""}${name.replace(/_/g, " ")}`;
  return failed ? `Couldn't ${label[1]}` : label[0];
}

/** What Path of Building did for this answer, step by step. */
export function PobSteps({ steps }: { steps: ToolStep[] }) {
  if (!steps.length) return null;
  return (
    <section className="pob" aria-label="Path of Building steps">
      <h3 className="pob-heading">Calculated with Path of Building</h3>
      <ol className="pob-steps">
        {steps.map((step) => (
          <li key={step.id} className="pob-step" data-status={step.status}>
            <span className="pob-marker" aria-hidden="true" />
            <span>
              {stepLabel(step.name, step.status === "failed")}
              {step.status === "running" && <span className="visually-hidden"> (running)</span>}
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

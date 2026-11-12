import { useEffect, useState } from "react";

const GITHUB = "https://github.com/wahid/build-advisor";

interface Stats {
  evals: {
    meta: string;
    cases: number | null;
    "hit@8": number | null;
    mrr: number | null;
    pass_rate: number | null;
    grounded: number | null;
    relevant: number | null;
    admits_gap: number | null;
  } | null;
  usage: {
    days: number;
    answers: number;
    median_first_word_ms: number | null;
    median_answer_ms: number | null;
    average_cost_usd: number | null;
    helpful_share: number | null;
    rated: number;
    numbers_grounded_share?: number | null;
  };
  corpus: { pages: number; chunks: number; patch: string; by_type: Record<string, number> };
  model: string;
  web_search: boolean;
  eval_history?: EvalRun[];
}

/** One run of the evaluation set (evals/history.jsonl). */
interface EvalRun {
  date: string;
  commit: string;
  label: string;
  config: string;
  experiment: boolean;
  cases: number | null;
  "hit@8": number | null;
  mrr: number | null;
  pass_rate: number | null;
  grounded: number | null;
}

/** Every eval run, newest first: what changed and what it did to the scores. */
function EvalHistory({ runs }: { runs: EvalRun[] }) {
  if (!runs.length) return null;
  return (
    <section className="about-section eval-history">
      <h2 className="about-heading">Evaluation history</h2>
      <p>
        Every change to search or prompts is measured on the evaluation set before it stays. Runs marked as not kept
        were tried and switched off again.
      </p>
      <div className="table-scroll">
        <table className="comparison-table">
          <thead>
            <tr>
              <th scope="col">Run</th>
              <th scope="col">Right page in top 8</th>
              <th scope="col">Mean reciprocal rank</th>
              <th scope="col">Cases passing</th>
              <th scope="col">Groundedness</th>
            </tr>
          </thead>
          <tbody>
            {[...runs].reverse().map((run, i) => (
              <tr key={`${run.date}-${i}`} data-experiment={run.experiment || undefined}>
                <th scope="row">
                  <span className="eval-run-label">
                    {run.label}
                    {run.experiment && <span className="eval-run-tag">not kept</span>}
                  </span>
                  <span className="eval-run-meta">
                    {run.date}
                    {run.commit && (
                      <>
                        {", "}
                        <a href={`${GITHUB}/commit/${run.commit}`}>{run.commit}</a>
                      </>
                    )}
                    {run.config && `, ${run.config}`}
                    {run.cases != null && `, ${run.cases} cases`}
                  </span>
                </th>
                <td>{percent(run["hit@8"])}</td>
                <td>{run.mrr == null ? "–" : run.mrr.toFixed(2)}</td>
                <td>{percent(run.pass_rate)}</td>
                <td>{run.grounded == null ? "–" : `${run.grounded.toFixed(2)} / 5`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const percent = (value: number | null | undefined) => (value == null ? "–" : `${Math.round(value * 100)}%`);
const seconds = (ms: number | null) => (ms == null ? "–" : `${(ms / 1000).toFixed(1)} s`);
const thousands = (n: number) => n.toLocaleString("en-US");

interface Step {
  title: string;
  text: string;
  kind: "mechanic" | "gem" | "web" | "unique";
}

const STEPS: Step[] = [
  {
    title: "Rewrite the question",
    text: "A quick LLM call turns the question into wiki terms (\"can something cast my spells for me?\" becomes Spell Totem Support) and decides whether it needs Path of Building. Follow-ups are rewritten to stand on their own.",
    kind: "mechanic",
  },
  {
    title: "Search the wiki",
    text: "Hybrid search over the community wiki: vector similarity (bge-m3 embeddings in PostgreSQL with pgvector), full-text keywords and page titles, merged with reciprocal rank fusion. The best eight sections become numbered sources.",
    kind: "mechanic",
  },
  {
    title: "Calculate with Path of Building",
    text: "For builds, the model drives Path of Building's own calculation engine through 26 tools: load your build, rank support or skill gems, test changes, compare two builds, or create one and hand over the share code.",
    kind: "gem",
  },
  {
    title: "Search the web, when needed",
    text: "For what the wiki can't know, like what's popular this league, it can search a short list of Path of Exile sites, at most twice per question.",
    kind: "web",
  },
  {
    title: "Answer with citations",
    text: "The answer streams in with every wiki fact cited, numbers credited to Path of Building, and the model's own game knowledge labelled as such.",
    kind: "unique",
  },
  {
    title: "Measure it",
    text: "Every answer is logged with its timings, tokens and cost, and can be rated. Bad answers become test cases in an evaluation set that runs in CI.",
    kind: "mechanic",
  },
];

export function HowItWorks() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    document.title = "How it works · Build Advisor";
    fetch("/api/stats/")
      .then((r) => (r.ok ? (r.json() as Promise<Stats>) : Promise.reject(new Error(String(r.status)))))
      .then(setStats)
      .catch(() => setFailed(true));
  }, []);

  const evals = stats?.evals;
  const usage = stats?.usage;

  return (
    <div className="about">
      <header className="about-head">
        <a href="/" className="about-back">
          Back to the advisor
        </a>
        <h1 className="wordmark">How Build Advisor works</h1>
        <p className="tagline">
          A question-answering app for Path of Exile builds: retrieval-augmented generation over the community wiki,
          with Path of Building as a calculator the model can use. Built with Django, React and PostgreSQL, deployed on
          a single small server.
        </p>
      </header>

      <section className="about-grid">
        <ol className="pipeline" aria-label="What happens when you ask a question">
          {STEPS.map((step) => (
            <li key={step.title} className="pipeline-step" data-type={step.kind}>
              <h2 className="pipeline-title">{step.title}</h2>
              <p className="pipeline-text">{step.text}</p>
            </li>
          ))}
        </ol>

        <aside className="item-card" aria-label="Live numbers" data-type="unique">
          <div className="item-card-head">
            <span className="item-card-name">Build Advisor</span>
            <span className="item-card-base">Retrieval-Augmented Advisor</span>
          </div>
          <div className="item-card-body">
            {failed && <p className="item-card-note">The live numbers couldn't be loaded.</p>}
            {!stats && !failed && <p className="item-card-note">Loading live numbers…</p>}
            {stats && (
              <>
                <p className="item-card-props">
                  Wiki pages: <b>{thousands(stats.corpus.pages)}</b>
                  <br />
                  Searchable sections: <b>{thousands(stats.corpus.chunks)}</b>
                  <br />
                  Patch: <b>{stats.corpus.patch || "–"}</b>
                  <br />
                  Model: <b>{stats.model || "–"}</b>
                </p>
                <hr className="item-card-rule" />
                {evals ? (
                  <ul className="item-card-mods" aria-label="Evaluation">
                    <li>
                      {percent(evals["hit@8"])} of questions find the right wiki page in the top 8
                    </li>
                    <li>{percent(evals.pass_rate)} of {evals.cases} evaluation cases pass</li>
                    <li>{evals.grounded?.toFixed(2) ?? "–"} / 5 groundedness, judged by an LLM</li>
                    <li>{percent(evals.admits_gap)} say so when the wiki can't answer</li>
                  </ul>
                ) : (
                  <p className="item-card-note">No evaluation results yet.</p>
                )}
                <hr className="item-card-rule" />
                {usage && usage.answers > 0 ? (
                  <ul className="item-card-mods" aria-label={`The last ${usage.days} days`}>
                    <li>{thousands(usage.answers)} answers in the last {usage.days} days</li>
                    <li>First words after {seconds(usage.median_first_word_ms)} (median)</li>
                    <li>
                      {usage.average_cost_usd == null ? "–" : `$${usage.average_cost_usd.toFixed(4)}`} per answer on
                      average
                    </li>
                    {usage.helpful_share != null && (
                      <li>
                        {percent(usage.helpful_share)} rated helpful ({usage.rated} ratings)
                      </li>
                    )}
                    {usage.numbers_grounded_share != null && (
                      <li>{percent(usage.numbers_grounded_share)} of answers with numbers have every number in a source</li>
                    )}
                  </ul>
                ) : (
                  <p className="item-card-note">No answers logged in the last 30 days yet.</p>
                )}
                <p className="item-card-flavour">
                  "Every number on this card comes from the running app or its last evaluation run."
                </p>
              </>
            )}
          </div>
        </aside>
      </section>

      {stats?.eval_history && <EvalHistory runs={stats.eval_history} />}

      <section className="about-section">
        <h2 className="about-heading">Made with</h2>
        <p>
          Django and Django REST Framework, PostgreSQL with pgvector, bge-m3 embeddings run locally, an OpenAI-compatible
          LLM interface (DeepSeek by default), Path of Building over the Model Context Protocol, React with TypeScript
          and Vite, Docker, Caddy, and GitHub Actions for tests, evaluations and deploys.
        </p>
        <h2 className="about-heading">Limits</h2>
        <p>
          Answers are only as current as the wiki, which is refreshed weekly. Calculated rankings use a reference
          character, not a finished build. The free demo answers a limited number of questions per day.
        </p>
        <p>
          The code, the evaluation set and the deployment setup are on <a href={GITHUB}>GitHub</a>.
        </p>
      </section>

      <footer className="colophon">
        Content from <a href="https://www.poewiki.net">poewiki.net</a>, licensed{" "}
        <a href="https://creativecommons.org/licenses/by-nc-sa/3.0/">CC BY-NC-SA 3.0</a>. Not affiliated with Grinding
        Gear Games.
      </footer>
    </div>
  );
}

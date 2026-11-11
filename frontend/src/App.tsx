import { useRef, useState, type FormEvent } from "react";

import { AnswerText } from "./answerText";
import { ask, AskError } from "./api";
import { groupSources, SourceCard } from "./SourceCard";
import { DOC_TYPES, type DocType, type Source } from "./types";

type Status = "idle" | "searching" | "answering" | "done" | "error";

const EXAMPLES = [
  "Which support gems work with Righteous Fire on a Chieftain?",
  "How does Cast when Damage Taken trigger spells?",
  "What scales the damage of ignite?",
];

export default function App() {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState("");
  const [docTypes, setDocTypes] = useState<DocType[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [cited, setCited] = useState<number[]>([]);
  const [patch, setPatch] = useState("");
  const [error, setError] = useState("");
  const [hovered, setHovered] = useState<number | null>(null);
  const controller = useRef<AbortController | null>(null);

  const busy = status === "searching" || status === "answering";

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;

    setQuestion(trimmed);
    setAsked(trimmed);
    setStatus("searching");
    setAnswer("");
    setSources([]);
    setCited([]);
    setError("");

    try {
      for await (const event of ask(trimmed, docTypes, current.signal)) {
        switch (event.type) {
          case "sources":
            setSources(event.sources);
            if (event.sources[0]) setPatch(event.sources[0].patch);
            setStatus("answering");
            break;
          case "delta":
            setAnswer((prev) => prev + event.text);
            break;
          case "done":
            setCited(event.cited);
            if (event.patch) setPatch(event.patch);
            setStatus("done");
            break;
          case "error":
            setError(event.message);
            setStatus("error");
            break;
        }
      }
    } catch (err) {
      if (current.signal.aborted) return;
      setError(
        err instanceof AskError ? err.message : "The server can't be reached. Check your connection and try again.",
      );
      setStatus("error");
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void submit(question);
  }

  function toggleType(type: DocType) {
    setDocTypes((prev) => (prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]));
  }

  const showResult = status !== "idle";

  return (
    <div className="page">
      <header className="masthead">
        <h1 className="wordmark">Build Advisor</h1>
        <p className="tagline">
          Answers about Path of Exile builds, taken from the community wiki{patch && ` for patch ${patch}`}.
        </p>
      </header>

      <form className="ask" onSubmit={onSubmit} role="search">
        <label htmlFor="question" className="visually-hidden">
          Your question
        </label>
        <textarea
          id="question"
          className="ask-input"
          rows={2}
          maxLength={500}
          placeholder="Ask about a skill, item, ascendancy or mechanic"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit(question);
            }
          }}
        />
        <button className="ask-button" type="submit" disabled={busy || !question.trim()}>
          {busy ? "Answering" : "Ask"}
        </button>

        <fieldset className="filters">
          <legend>Search only</legend>
          {DOC_TYPES.map((type) => (
            <label key={type.value} className="filter" data-type={type.value}>
              <input
                type="checkbox"
                checked={docTypes.includes(type.value)}
                onChange={() => toggleType(type.value)}
              />
              <span>{type.label}</span>
            </label>
          ))}
          {docTypes.length === 0 && <span className="filters-hint">Nothing ticked searches everything.</span>}
        </fieldset>
      </form>

      {!showResult && (
        <section className="examples" aria-label="Example questions">
          <p>Not sure where to start? Try one of these:</p>
          <ul>
            {EXAMPLES.map((example) => (
              <li key={example}>
                <button type="button" onClick={() => void submit(example)}>
                  {example}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {showResult && (
        <main className="result">
          <article className="answer" aria-live="polite" aria-busy={busy}>
            <h2 className="answer-question">{asked}</h2>
            {status === "searching" && <p className="status">Searching the wiki…</p>}
            {status === "answering" && !answer && (
              <p className="status">Found {sources.length} pages. Writing the answer…</p>
            )}
            <div className="answer-text" data-streaming={status === "answering" || undefined}>
              <AnswerText text={answer} sources={sources} onCiteHover={setHovered} />
            </div>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
          </article>

          {sources.length > 0 && (
            <aside className="sources" aria-label="Sources">
              <h2 className="sources-heading">Sources</h2>
              <ul className="tooltips">
                {groupSources(sources).map((group) => (
                  <SourceCard
                    key={group.url}
                    group={group}
                    cited={cited}
                    hovered={hovered}
                    answered={status === "done"}
                  />
                ))}
              </ul>
            </aside>
          )}
        </main>
      )}

      <footer className="colophon">
        Content from <a href="https://www.poewiki.net">poewiki.net</a>, licensed{" "}
        <a href="https://creativecommons.org/licenses/by-nc-sa/3.0/">CC BY-NC-SA 3.0</a>. Not affiliated with
        Grinding Gear Games.
      </footer>
    </div>
  );
}

import { useState } from "react";

import { AnswerText } from "./answerText";
import type { ChatTurn } from "./conversation";
import { PobExport, PobSteps } from "./PobPanel";
import { groupSources, SourceCard } from "./SourceCard";

interface Props {
  turn: ChatTurn;
  /** Only the latest turn announces its streaming text to screen readers. */
  isLatest: boolean;
}

/** One exchange: the question as a bubble, then the answer; its sources fold out once it's done. */
export function TurnView({ turn, isLatest }: Props) {
  const [hovered, setHovered] = useState<number | null>(null);
  const busy = turn.status === "searching" || turn.status === "answering";
  const groups = groupSources(turn.sources);
  const running = turn.steps.some((step) => step.status === "running");

  return (
    <section className="turn" aria-label={turn.question}>
      <p className="bubble">{turn.question}</p>

      <article className="reply" aria-live={isLatest ? "polite" : undefined} aria-busy={busy}>
        {turn.searchTerms && <p className="search-terms">Searched the wiki for {turn.searchTerms}</p>}
        {turn.status === "searching" && (
          <p className="status">{turn.searchTerms ? "Searching the wiki…" : "Working out what to search for…"}</p>
        )}
        <PobSteps steps={turn.steps} />
        {turn.status === "answering" && !turn.answer && !running && (
          <p className="status">Found {turn.sources.length} pages. Writing the answer…</p>
        )}
        <div className="answer-text" data-streaming={turn.status === "answering" || undefined}>
          <AnswerText text={turn.answer} sources={turn.sources} onCiteHover={setHovered} />
        </div>
        {turn.exportCode && <PobExport code={turn.exportCode} />}
        {turn.error && (
          <p className="error" role="alert">
            {turn.error}
          </p>
        )}

        {groups.length > 0 && !busy && (
          <details className="sources">
            <summary className="sources-summary">
              Sources: {groups.length} wiki {groups.length === 1 ? "page" : "pages"}
              {turn.patch && `, patch ${turn.patch}`}
            </summary>
            <ul className="tooltips">
              {groups.map((group) => (
                <SourceCard
                  key={group.url}
                  group={group}
                  cited={turn.cited}
                  hovered={hovered}
                  answered={turn.status === "done"}
                />
              ))}
            </ul>
          </details>
        )}
      </article>
    </section>
  );
}

import { useState, type FormEvent } from "react";

import { AnswerText } from "./answerText";
import type { ChatTurn } from "./conversation";
import { ComparisonTable, ItemCheckTable } from "./ComparisonTable";
import { Feedback } from "./Feedback";
import { LevelingTable } from "./LevelingTable";
import { PassiveTable } from "./PassiveTable";
import { PobExport, PobSteps } from "./PobPanel";
import { ItemTooltip } from "./ItemTooltip";
import { itemName } from "./items";
import { groupSources, SourceCard } from "./SourceCard";
import { TurnActions } from "./TurnActions";

interface Props {
  turn: ChatTurn;
  onRated: (rating: 1 | -1) => void;
  /** Ask this question again (latest or failed turns only). */
  onRetry?: () => void;
  /** Change the question and ask again (latest turn only). */
  onEdit?: (question: string) => void;
  /** Today's limit is used up: retrying would fail too. */
  limitReached?: boolean;
  /** Only the latest turn announces its streaming text to screen readers. */
  isLatest: boolean;
}

/** One exchange: the question as a bubble, then the answer; its sources fold out once it's done. */
export function TurnView({ turn, isLatest, onRated, onRetry, onEdit, limitReached }: Props) {
  const [hovered, setHovered] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(turn.question);

  function saveEdit(event: FormEvent) {
    event.preventDefault();
    const question = draft.trim();
    if (!question || !onEdit) return;
    setEditing(false);
    onEdit(question);
  }
  const busy = turn.status === "searching" || turn.status === "answering";
  const groups = groupSources(turn.sources);
  const running = turn.steps.some((step) => step.status === "running");

  return (
    <section className="turn" aria-label={turn.question || (turn.itemText ? itemName(turn.itemText) : "Question")}>
      {editing ? (
        <form className="bubble bubble-editing" onSubmit={saveEdit}>
          <label htmlFor={`edit-${turn.id}`} className="visually-hidden">
            Edit your question
          </label>
          <textarea
            id={`edit-${turn.id}`}
            className="bubble-input"
            rows={2}
            maxLength={500}
            value={draft}
            autoFocus
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) saveEdit(e);
              if (e.key === "Escape") setEditing(false);
            }}
          />
          <div className="bubble-actions">
            <button type="button" className="turn-action" onClick={() => setEditing(false)}>
              Cancel
            </button>
            <button type="submit" className="turn-action turn-action-primary" disabled={!draft.trim()}>
              Ask again
            </button>
          </div>
        </form>
      ) : (
        turn.question && (
        <div className="bubble-row">
          {onEdit && !busy && !limitReached && (
            <button
              type="button"
              className="bubble-edit"
              onClick={() => {
                setDraft(turn.question);
                setEditing(true);
              }}
            >
              Edit
            </button>
          )}
          <p className="bubble">{turn.question}</p>
        </div>
        )
      )}
      {turn.item ? (
        <div className="pasted-item">
          <ItemTooltip card={turn.item.card} />
        </div>
      ) : (
        turn.itemText && <p className="bubble bubble-item">Item: {itemName(turn.itemText)}</p>
      )}

      <article className="reply" aria-live={isLatest ? "polite" : undefined} aria-busy={busy}>
        {turn.searchTerms && <p className="search-terms">Searched the wiki for {turn.searchTerms}</p>}
        {turn.status === "searching" && (
          <p className="status">{turn.searchTerms ? "Searching the wiki…" : "Working out what to search for…"}</p>
        )}
        <PobSteps steps={turn.steps} />
        {turn.comparison && <ComparisonTable comparison={turn.comparison} />}
        {turn.itemCheck && <ItemCheckTable check={turn.itemCheck} />}
        {turn.passives && <PassiveTable ranking={turn.passives} />}
        {turn.leveling && <LevelingTable leveling={turn.leveling} />}
        {turn.status === "answering" && !turn.answer && !running && (
          <p className="status">Found {turn.sources.length} pages. Writing the answer…</p>
        )}
        <div className="answer-text" data-streaming={turn.status === "answering" || undefined}>
          <AnswerText text={turn.answer} sources={turn.sources} entities={turn.entities} onCiteHover={setHovered} />
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
        {!busy && (
          <div className="turn-footer">
            <TurnActions turn={turn} canRetry={Boolean(onRetry) && !limitReached} onRetry={() => onRetry?.()} />
            {turn.status === "done" && turn.logId && (
              <Feedback logId={turn.logId} rating={turn.rating} onRated={onRated} />
            )}
          </div>
        )}
      </article>
    </section>
  );
}

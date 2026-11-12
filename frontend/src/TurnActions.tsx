import { useState } from "react";

import type { ChatTurn } from "./conversation";

/** The answer as plain text with its sources listed, for the clipboard. */
export function plainAnswer(turn: ChatTurn): string {
  const cited = turn.sources.filter((s) => turn.cited.includes(s.number));
  const list = cited.map((s) => `[${s.number}] ${s.title}${s.section ? `, ${s.section}` : ""}: ${s.url}`);
  return list.length ? `${turn.answer.trim()}\n\nSources:\n${list.join("\n")}` : turn.answer.trim();
}

interface Props {
  turn: ChatTurn;
  canRetry: boolean;
  onRetry: () => void;
}

/** Copy and Retry under an answer. */
export function TurnActions({ turn, canRetry, onRetry }: Props) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(plainAnswer(turn));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="turn-actions">
      {turn.answer.trim() && (
        <button type="button" className="turn-action" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy answer"}
        </button>
      )}
      {canRetry && (
        <button type="button" className="turn-action" onClick={onRetry}>
          {turn.status === "error" ? "Try again" : "Retry"}
        </button>
      )}
    </div>
  );
}

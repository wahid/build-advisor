import { useEffect, useState } from "react";

import { fetchSharedChat, type SharedChat } from "./api";
import type { ChatTurn } from "./conversation";
import { TurnView } from "./TurnView";

type State = { status: "loading" } | { status: "missing" } | { status: "failed" } | { status: "ready"; chat: SharedChat };

function toTurns(chat: SharedChat): ChatTurn[] {
  return chat.turns.map((turn, i) => ({
    id: `shared-${i}`,
    question: turn.question,
    status: "done",
    answer: turn.answer,
    sources: turn.sources,
    cited: turn.cited,
    steps: [],
    exportCode: "",
    searchTerms: "",
    patch: turn.patch,
    error: "",
    entities: turn.entities,
  }));
}

/** A chat someone shared, read-only: /c/<slug>. */
export function SharedChatPage({ slug }: { slug: string }) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let current = true;
    fetchSharedChat(slug)
      .then((chat) => current && setState(chat ? { status: "ready", chat } : { status: "missing" }))
      .catch(() => current && setState({ status: "failed" }));
    return () => {
      current = false;
    };
  }, [slug]);

  useEffect(() => {
    if (state.status === "ready") document.title = `${state.chat.title} | Build Advisor`;
  }, [state]);

  return (
    <div className="app shared">
      <header className="shared-head">
        <a className="shared-name" href="/">
          Build Advisor
        </a>
        <a className="turn-action turn-action-primary" href="/">
          Ask your own question
        </a>
      </header>
      <main className="thread">
        {state.status === "loading" && <p className="status">Loading the shared chat…</p>}
        {state.status === "missing" && (
          <p className="status">This shared chat doesn't exist, or its owner stopped sharing it.</p>
        )}
        {state.status === "failed" && (
          <p className="error" role="alert">
            The shared chat couldn't be loaded. Try again later.
          </p>
        )}
        {state.status === "ready" && (
          <>
            <p className="shared-note">
              A shared conversation from {new Date(state.chat.created_at).toLocaleDateString("en-GB", { dateStyle: "long" })}.
              Answers come from the Path of Exile community wiki and Path of Building.
            </p>
            {toTurns(state.chat).map((turn) => (
              <TurnView key={turn.id} turn={turn} isLatest={false} onRated={() => {}} />
            ))}
          </>
        )}
      </main>
      <footer className="colophon">
        Content from <a href="https://www.poewiki.net">poewiki.net</a>, licensed{" "}
        <a href="https://creativecommons.org/licenses/by-nc-sa/3.0/">CC BY-NC-SA 3.0</a>. Not affiliated with Grinding
        Gear Games.
      </footer>
    </div>
  );
}

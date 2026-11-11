import { useEffect, useRef, useState } from "react";

import { ask, AskError } from "./api";
import { Composer } from "./Composer";
import {
  applyEvent,
  loadConversation,
  newTurn,
  saveConversation,
  toHistory,
  type ChatTurn,
} from "./conversation";
import { TurnView } from "./TurnView";
import type { AskEvent, DocType } from "./types";

const EXAMPLES = [
  "Which support gems work with Righteous Fire on a Chieftain?",
  "How does Cast when Damage Taken trigger spells?",
  "What scales the damage of ignite?",
  "Create a level 90 Righteous Fire Chieftain build",
];

const UNREACHABLE = "The server can't be reached. Check your connection and try again.";

export default function App() {
  const [turns, setTurns] = useState<ChatTurn[]>(loadConversation);
  const [docTypes, setDocTypes] = useState<DocType[]>([]);
  const [build, setBuild] = useState("");
  const controller = useRef<AbortController | null>(null);
  const nextId = useRef(0);
  // Keep following the newest text unless the reader scrolled up to read.
  const following = useRef(true);

  const latest = turns.at(-1);
  const busy = latest?.status === "searching" || latest?.status === "answering";

  useEffect(() => saveConversation(turns), [turns]);

  useEffect(() => {
    const onScroll = () => {
      const bottom = document.documentElement.scrollHeight - window.innerHeight - window.scrollY;
      following.current = bottom < 120;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (following.current) window.scrollTo({ top: document.documentElement.scrollHeight });
  }, [turns]);

  function update(id: string, change: (turn: ChatTurn) => ChatTurn) {
    setTurns((prev) => prev.map((turn) => (turn.id === id ? change(turn) : turn)));
  }

  async function submit(question: string) {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    const id = `turn-${Date.now()}-${nextId.current++}`;
    const history = toHistory(turns);
    following.current = true;
    setTurns((prev) => [...prev, newTurn(id, question)]);

    try {
      const events = ask(question, { docTypes, build: build.trim(), history, signal: current.signal });
      for await (const event of events) update(id, (turn) => applyEvent(turn, event as AskEvent));
    } catch (err) {
      if (current.signal.aborted) return;
      const message = err instanceof AskError ? err.message : UNREACHABLE;
      update(id, (turn) => ({ ...turn, status: "error", error: message }));
    }
  }

  function stop() {
    controller.current?.abort();
    if (latest && busy) {
      update(latest.id, (turn) => ({ ...turn, status: turn.answer ? "done" : "error", error: turn.answer ? "" : "Stopped." }));
    }
  }

  function newChat() {
    controller.current?.abort();
    setTurns([]);
  }

  const composer = (
    <Composer
      busy={busy}
      followUp={turns.length > 0}
      docTypes={docTypes}
      onDocTypesChange={setDocTypes}
      build={build}
      onBuildChange={setBuild}
      onSubmit={(q) => void submit(q)}
      onStop={stop}
    />
  );

  if (turns.length === 0) {
    return (
      <div className="app app-empty">
        <main className="welcome">
          <h1 className="wordmark">Build Advisor</h1>
          <p className="tagline">
            Ask about Path of Exile builds. Answers come from the community wiki, and Path of Building runs the numbers
            on your own build.
          </p>
          {composer}
          <ul className="examples" aria-label="Example questions">
            {EXAMPLES.map((example) => (
              <li key={example}>
                <button type="button" onClick={() => void submit(example)}>
                  {example}
                </button>
              </li>
            ))}
          </ul>
        </main>
        <Colophon />
      </div>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <span className="topbar-name">Build Advisor</span>
        <button type="button" className="new-chat" onClick={newChat}>
          New chat
        </button>
      </header>
      <main className="thread">
        {turns.map((turn) => (
          <TurnView key={turn.id} turn={turn} isLatest={turn.id === latest?.id} />
        ))}
      </main>
      <div className="dock">
        {composer}
        <Colophon />
      </div>
    </div>
  );
}

function Colophon() {
  return (
    <footer className="colophon">
      Content from <a href="https://www.poewiki.net">poewiki.net</a>, licensed{" "}
      <a href="https://creativecommons.org/licenses/by-nc-sa/3.0/">CC BY-NC-SA 3.0</a>. Not affiliated with Grinding
      Gear Games.
    </footer>
  );
}

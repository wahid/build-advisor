import { useEffect, useRef, useState } from "react";

import { ask, AskError } from "./api";
import { Composer } from "./Composer";
import {
  applyEvent,
  findBuildLink,
  loadActiveId,
  loadConversations,
  newConversation,
  newTurn,
  saveActiveId,
  saveConversations,
  titleFor,
  toHistory,
  type ChatTurn,
  type Conversation,
} from "./conversation";
import { Sidebar } from "./Sidebar";
import { TurnView } from "./TurnView";
import type { AskEvent, DocType } from "./types";

const EXAMPLES = [
  "Which support gems work with Righteous Fire on a Chieftain?",
  "How does Cast when Damage Taken trigger spells?",
  "What scales the damage of ignite?",
  "Create a level 90 Righteous Fire Chieftain build",
];

const UNREACHABLE = "The server can't be reached. Check your connection and try again.";
const SAVE_DELAY = 400; // ms; streaming changes the chats many times a second

function makeId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Saved chats, and the one to open: the last one used, or a fresh chat. */
function initialState(): { chats: Conversation[]; activeId: string } {
  const saved = loadConversations();
  const active = loadActiveId();
  if (active && saved.some((chat) => chat.id === active)) return { chats: saved, activeId: active };
  const fresh = newConversation(makeId("chat"));
  return { chats: [fresh, ...saved], activeId: fresh.id };
}

interface Streaming {
  chatId: string;
  turnId: string;
  controller: AbortController;
}

export default function App() {
  const [initial] = useState(initialState);
  const [chats, setChats] = useState<Conversation[]>(initial.chats);
  const [activeId, setActiveId] = useState(initial.activeId);
  const [docTypes, setDocTypes] = useState<DocType[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const streaming = useRef<Streaming | null>(null);
  // Keep following the newest text unless the reader scrolled up to read.
  const following = useRef(true);

  const active = chats.find((chat) => chat.id === activeId) ?? chats[0];
  const turns = active?.turns ?? [];
  const latest = turns.at(-1);
  const busy = latest?.status === "searching" || latest?.status === "answering";

  useEffect(() => {
    const timer = window.setTimeout(() => saveConversations(chats), SAVE_DELAY);
    return () => window.clearTimeout(timer);
  }, [chats]);
  useEffect(() => saveActiveId(activeId), [activeId]);

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
  }, [turns, activeId]);

  function updateChat(id: string, change: (chat: Conversation) => Conversation) {
    setChats((prev) => prev.map((chat) => (chat.id === id ? change(chat) : chat)));
  }

  function updateTurn(chatId: string, turnId: string, change: (turn: ChatTurn) => ChatTurn) {
    updateChat(chatId, (chat) => ({
      ...chat,
      turns: chat.turns.map((turn) => (turn.id === turnId ? change(turn) : turn)),
    }));
  }

  /** Stop the answer being streamed (in whichever chat), keeping what arrived. */
  function stopStreaming() {
    const current = streaming.current;
    if (!current) return;
    streaming.current = null;
    current.controller.abort();
    updateTurn(current.chatId, current.turnId, (turn) =>
      turn.status === "searching" || turn.status === "answering"
        ? { ...turn, status: turn.answer ? "done" : "error", error: turn.answer ? "" : "Stopped." }
        : turn,
    );
  }

  async function submit(question: string) {
    if (!active) return;
    stopStreaming();
    const chatId = active.id;
    const turnId = makeId("turn");
    const controller = new AbortController();
    streaming.current = { chatId, turnId, controller };
    const history = toHistory(active.turns);
    // A build link in the question becomes the chat's build, so follow-ups use it too.
    const link = findBuildLink(question);
    const build = link || active.build.trim();
    following.current = true;
    updateChat(chatId, (chat) => {
      const nextTurns = [...chat.turns, newTurn(turnId, question)];
      return {
        ...chat,
        turns: nextTurns,
        title: chat.turns.length ? chat.title : titleFor(nextTurns),
        updatedAt: Date.now(),
        ...(link ? { build: link, buildChanged: false } : {}),
      };
    });

    try {
      for await (const event of ask(question, { docTypes, build, history, signal: controller.signal })) {
        updateTurn(chatId, turnId, (turn) => applyEvent(turn, event as AskEvent));
        if (event.type === "pob_export") {
          // Follow-ups continue from the changed build, not the original one.
          updateChat(chatId, (chat) => ({ ...chat, build: event.code, buildChanged: true }));
        }
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      const message = err instanceof AskError ? err.message : UNREACHABLE;
      updateTurn(chatId, turnId, (turn) => ({ ...turn, status: "error", error: message }));
    } finally {
      if (streaming.current?.turnId === turnId) streaming.current = null;
    }
  }

  function openChat(id: string) {
    setActiveId(id);
    setSidebarOpen(false);
    following.current = true;
  }

  function newChat() {
    setSidebarOpen(false);
    if (active && active.turns.length === 0) return; // already on a fresh chat
    const fresh = newConversation(makeId("chat"));
    setChats((prev) => [fresh, ...prev]);
    setActiveId(fresh.id);
  }

  function deleteChat(id: string) {
    const chat = chats.find((c) => c.id === id);
    if (!chat || !window.confirm(`Delete "${chat.title}"? This can't be undone.`)) return;
    if (streaming.current?.chatId === id) stopStreaming();
    const rest = chats.filter((c) => c.id !== id);
    if (id !== activeId) {
      setChats(rest);
      return;
    }
    const fresh = newConversation(makeId("chat"));
    setChats([fresh, ...rest]);
    setActiveId(fresh.id);
  }

  const composer = active && (
    <Composer
      key={active.id}
      busy={busy}
      followUp={turns.length > 0}
      docTypes={docTypes}
      onDocTypesChange={setDocTypes}
      build={active.build}
      buildChanged={active.buildChanged}
      onBuildChange={(value) => updateChat(active.id, (chat) => ({ ...chat, build: value, buildChanged: false }))}
      onSubmit={(q) => void submit(q)}
      onStop={stopStreaming}
    />
  );

  return (
    <div className="shell">
      <Sidebar
        chats={chats}
        activeId={active?.id ?? ""}
        open={sidebarOpen}
        onSelect={openChat}
        onNew={newChat}
        onDelete={deleteChat}
        onClose={() => setSidebarOpen(false)}
      />
      <div className={turns.length ? "app" : "app app-empty"}>
        <header className="topbar">
          <button
            type="button"
            className="menu-button"
            aria-label="Show chats"
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen(true)}
          >
            Chats
          </button>
          <span className="topbar-name">Build Advisor</span>
          <button type="button" className="new-chat" onClick={newChat}>
            New chat
          </button>
        </header>

        {turns.length === 0 ? (
          <>
            <main className="welcome">
              <h1 className="wordmark">Build Advisor</h1>
              <p className="tagline">
                Ask about Path of Exile builds. Answers come from the community wiki, and Path of Building runs the
                numbers on your own build.
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
          </>
        ) : (
          <>
            <main className="thread">
              {turns.map((turn) => (
                <TurnView key={turn.id} turn={turn} isLatest={turn.id === latest?.id} />
              ))}
            </main>
            <div className="dock">
              {composer}
              <Colophon />
            </div>
          </>
        )}
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

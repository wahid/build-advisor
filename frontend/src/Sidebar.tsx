import type { Conversation } from "./conversation";

interface Props {
  chats: Conversation[];
  activeId: string;
  open: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

/** Earlier chats, newest first; they live in this browser. */
export function Sidebar({ chats, activeId, open, onSelect, onNew, onDelete, onClose }: Props) {
  const listed = chats.filter((chat) => chat.turns.length > 0);
  return (
    <>
      <nav className="sidebar" data-open={open || undefined} aria-label="Chats">
        <div className="sidebar-head">
          <span className="sidebar-name">Build Advisor</span>
          <button type="button" className="new-chat" onClick={onNew}>
            New chat
          </button>
        </div>
        {listed.length > 0 ? (
          <ul className="chat-list">
            {listed.map((chat) => (
              <li key={chat.id} className="chat-item" data-active={chat.id === activeId || undefined}>
                <button
                  type="button"
                  className="chat-open"
                  aria-current={chat.id === activeId ? "page" : undefined}
                  onClick={() => onSelect(chat.id)}
                >
                  {chat.title}
                </button>
                <button
                  type="button"
                  className="chat-delete"
                  aria-label={`Delete chat: ${chat.title}`}
                  title="Delete chat"
                  onClick={() => onDelete(chat.id)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="chat-empty">Your chats show up here. They're kept in this browser.</p>
        )}
      </nav>
      {open && <button type="button" className="sidebar-backdrop" aria-label="Close chats" onClick={onClose} />}
    </>
  );
}

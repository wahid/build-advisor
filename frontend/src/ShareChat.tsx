import { useState } from "react";

import { AskError, shareChat, unshareChat, type ShareLink } from "./api";

interface Props {
  /** Log ids of the chat's finished answers, in order. */
  logIds: string[];
  link?: ShareLink;
  onChange: (link: ShareLink | undefined) => void;
}

/** Publish the chat as a read-only page, copy its link, or take it down again. */
export function ShareChat({ logIds, link, onChange }: Props) {
  const [working, setWorking] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  async function run(action: () => Promise<void>) {
    setWorking(true);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(err instanceof AskError ? err.message : "That didn't work. Try again later.");
    } finally {
      setWorking(false);
    }
  }

  const create = () =>
    run(async () => {
      // A new page each time: the old link keeps showing the chat as it was.
      if (link) await unshareChat(link);
      onChange(await shareChat(logIds));
    });

  const remove = () =>
    run(async () => {
      if (link) await unshareChat(link);
      onChange(undefined);
    });

  async function copy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link.url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  if (!logIds.length) return null;
  const outdated = link !== undefined && link.turns !== logIds.length;
  return (
    <section className="share" aria-label="Share this chat">
      {link ? (
        <>
          <p className="share-text">
            Anyone with this link can read {outdated ? "the first part of this chat" : "this chat"}:
          </p>
          <div className="share-row">
            <input className="share-link" readOnly value={link.url} aria-label="Link to the shared chat" onFocus={(e) => e.target.select()} />
            <button type="button" className="turn-action turn-action-primary" onClick={() => void copy()}>
              {copied ? "Copied" : "Copy link"}
            </button>
            {outdated && (
              <button type="button" className="turn-action" disabled={working} onClick={() => void create()}>
                Update link
              </button>
            )}
            <button type="button" className="turn-action" disabled={working} onClick={() => void remove()}>
              Stop sharing
            </button>
          </div>
        </>
      ) : (
        <button type="button" className="turn-action" disabled={working} onClick={() => void create()}>
          {working ? "Creating link…" : "Share this chat"}
        </button>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

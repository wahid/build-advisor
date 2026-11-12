import { useState } from "react";

import { sendFeedback } from "./api";

interface Props {
  logId: string;
  rating?: 1 | -1;
  onRated: (rating: 1 | -1) => void;
}

/** "Was this helpful?" under an answer. A "no" can say what was wrong. */
export function Feedback({ logId, rating, onRated }: Props) {
  const [writing, setWriting] = useState(false);
  const [note, setNote] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "failed">(rating ? "sent" : "idle");

  async function send(value: 1 | -1, text = "") {
    setState("sending");
    try {
      await sendFeedback(logId, value, text);
      onRated(value);
      setState("sent");
      setWriting(false);
    } catch {
      setState("failed");
    }
  }

  if (state === "sent" && !writing) {
    return (
      <p className="feedback-thanks">
        {rating === -1 || note ? "Thanks, that helps improve the answers." : "Thanks for the feedback."}
      </p>
    );
  }

  return (
    <div className="feedback">
      {writing ? (
        <form
          className="feedback-form"
          onSubmit={(e) => {
            e.preventDefault();
            void send(-1, note.trim());
          }}
        >
          <label htmlFor={`feedback-${logId}`} className="feedback-label">
            What was wrong or missing? (optional)
          </label>
          <textarea
            id={`feedback-${logId}`}
            className="feedback-note"
            rows={2}
            maxLength={2000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <div className="feedback-actions">
            <button type="submit" className="feedback-send" disabled={state === "sending"}>
              Send feedback
            </button>
            <button type="button" className="feedback-cancel" onClick={() => setWriting(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <>
          <span className="feedback-question">Was this helpful?</span>
          <button type="button" className="feedback-button" disabled={state === "sending"} onClick={() => void send(1)}>
            Yes
          </button>
          <button type="button" className="feedback-button" onClick={() => setWriting(true)}>
            No
          </button>
        </>
      )}
      {state === "failed" && (
        <span className="feedback-error" role="alert">
          Couldn't send it. Try again later.
        </span>
      )}
    </div>
  );
}

import { useEffect, useRef, useState, type FormEvent } from "react";

import { DOC_TYPES, type DocType } from "./types";

interface Props {
  busy: boolean;
  followUp: boolean;
  docTypes: DocType[];
  onDocTypesChange: (types: DocType[]) => void;
  build: string;
  onBuildChange: (build: string) => void;
  onSubmit: (question: string) => void;
  onStop: () => void;
}

const MAX_HEIGHT = 220; // px; the box grows with the question up to this

/** The message box: question, an optional Path of Building build, and search filters. */
export function Composer({ busy, followUp, docTypes, onDocTypesChange, build, onBuildChange, onSubmit, onStop }: Props) {
  const [question, setQuestion] = useState("");
  const [editingBuild, setEditingBuild] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const box = input.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, MAX_HEIGHT)}px`;
  }, [question]);

  function send(event?: FormEvent) {
    event?.preventDefault();
    if (busy || !question.trim()) return;
    onSubmit(question.trim());
    setQuestion("");
    setEditingBuild(false);
  }

  function toggleType(type: DocType) {
    onDocTypesChange(docTypes.includes(type) ? docTypes.filter((t) => t !== type) : [...docTypes, type]);
  }

  const hasBuild = build.trim().length > 0;

  return (
    <form className="composer" onSubmit={send}>
      {editingBuild && (
        <div className="build-editor">
          <label htmlFor="build" className="build-label">
            Path of Building code or pobb.in link
          </label>
          <textarea
            id="build"
            className="build-input"
            rows={2}
            placeholder="Paste it here. It stays attached for the whole conversation."
            value={build}
            onChange={(e) => onBuildChange(e.target.value)}
          />
        </div>
      )}

      <label htmlFor="question" className="visually-hidden">
        Your question
      </label>
      <textarea
        id="question"
        ref={input}
        className="composer-input"
        rows={1}
        maxLength={500}
        autoFocus
        placeholder={followUp ? "Ask a follow-up" : "Ask about a skill, item or mechanic, or paste a pobb.in link"}
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) send(e);
        }}
      />

      <div className="composer-bar">
        <div className="composer-tools">
          {hasBuild && !editingBuild ? (
            <span className="build-chip">
              <button type="button" className="build-chip-label" onClick={() => setEditingBuild(true)}>
                Build attached
              </button>
              <button type="button" className="build-chip-remove" aria-label="Remove the build" onClick={() => onBuildChange("")}>
                ×
              </button>
            </span>
          ) : (
            <button type="button" className="tool-button" aria-expanded={editingBuild} onClick={() => setEditingBuild(!editingBuild)}>
              {editingBuild ? "Done" : "Attach build"}
            </button>
          )}
          <fieldset className="filters">
            <legend className="visually-hidden">Search only these page types</legend>
            {DOC_TYPES.map((type) => (
              <label key={type.value} className="filter" data-type={type.value} data-on={docTypes.includes(type.value) || undefined}>
                <input type="checkbox" checked={docTypes.includes(type.value)} onChange={() => toggleType(type.value)} />
                <span>{type.label}</span>
              </label>
            ))}
          </fieldset>
        </div>
        {busy ? (
          <button type="button" className="send-button" onClick={onStop}>
            Stop
          </button>
        ) : (
          <button type="submit" className="send-button" disabled={!question.trim()}>
            Ask
          </button>
        )}
      </div>
    </form>
  );
}

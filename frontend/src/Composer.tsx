import { useEffect, useRef, useState, type FormEvent } from "react";

import { DOC_TYPES, type DocType } from "./types";

interface Props {
  busy: boolean;
  /** Asking is closed for now (the daily limit). */
  disabled?: boolean;
  followUp: boolean;
  docTypes: DocType[];
  onDocTypesChange: (types: DocType[]) => void;
  build: string;
  /** The attached build is the assistant's changed version of it. */
  buildChanged: boolean;
  onBuildChange: (build: string) => void;
  /** A second build to compare with; only offered once a build is attached. */
  compareBuild: string;
  onCompareBuildChange: (build: string) => void;
  onSubmit: (question: string) => void;
  onStop: () => void;
}

const MAX_HEIGHT = 220; // px; the box grows with the question up to this

/** The message box: question, an optional Path of Building build, and search filters. */
export function Composer({
  busy,
  disabled = false,
  followUp,
  docTypes,
  onDocTypesChange,
  build,
  buildChanged,
  onBuildChange,
  compareBuild,
  onCompareBuildChange,
  onSubmit,
  onStop,
}: Props) {
  const [question, setQuestion] = useState("");
  const [editingBuild, setEditingBuild] = useState(false);
  const [editingCompare, setEditingCompare] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const box = input.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, MAX_HEIGHT)}px`;
  }, [question]);

  function send(event?: FormEvent) {
    event?.preventDefault();
    if (busy || disabled || !question.trim()) return;
    onSubmit(question.trim());
    setQuestion("");
    setEditingBuild(false);
    setEditingCompare(false);
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

      {editingCompare && (
        <div className="build-editor">
          <label htmlFor="compare-build" className="build-label">
            Build to compare with (pobb.in link or share code)
          </label>
          <textarea
            id="compare-build"
            className="build-input"
            rows={2}
            placeholder="Your build is A, this one is B. Ask e.g. which one is tankier."
            value={compareBuild}
            onChange={(e) => onCompareBuildChange(e.target.value)}
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
              <button
                type="button"
                className="build-chip-label"
                title={buildChanged ? "Follow-ups use the build as it was changed in this chat" : undefined}
                onClick={() => setEditingBuild(true)}
              >
                {buildChanged ? "Changed build attached" : "Build attached"}
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
          {hasBuild &&
            (compareBuild.trim() && !editingCompare ? (
              <span className="build-chip">
                <button type="button" className="build-chip-label" onClick={() => setEditingCompare(true)}>
                  Comparing with build B
                </button>
                <button
                  type="button"
                  className="build-chip-remove"
                  aria-label="Stop comparing"
                  onClick={() => onCompareBuildChange("")}
                >
                  ×
                </button>
              </span>
            ) : (
              <button
                type="button"
                className="tool-button"
                aria-expanded={editingCompare}
                onClick={() => setEditingCompare(!editingCompare)}
              >
                {editingCompare ? "Done" : "Compare with another build"}
              </button>
            ))}
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
          <button type="submit" className="send-button" disabled={disabled || !question.trim()}>
            Ask
          </button>
        )}
      </div>
    </form>
  );
}

import { useId, useState, type ReactNode } from "react";

import { DOC_TYPES, type Entity } from "./types";

const KIND: Record<string, string> = Object.fromEntries(DOC_TYPES.map((t) => [t.value, t.singular]));

/** A gem, unique or ascendancy name with a small item-tooltip card on hover or focus. */
export function EntityName({ entity, children }: { entity: Entity; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span
      className="entity"
      data-type={entity.doc_type}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <a
        href={entity.url}
        target="_blank"
        rel="noreferrer"
        className="entity-name"
        aria-describedby={open ? id : undefined}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        {children}
      </a>
      {open && (
        <span role="tooltip" id={id} className="entity-card">
          <span className="entity-card-head">
            <span className="entity-card-title">{entity.title ?? entity.name}</span>
            <span className="entity-card-kind">{KIND[entity.doc_type] ?? "Wiki page"}</span>
          </span>
          {entity.summary && <span className="entity-card-body">{entity.summary}</span>}
        </span>
      )}
    </span>
  );
}

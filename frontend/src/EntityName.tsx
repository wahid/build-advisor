import { useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { ItemTooltip } from "./ItemTooltip";
import { DOC_TYPES, type Card, type Entity } from "./types";

const KIND: Record<string, string> = Object.fromEntries(DOC_TYPES.map((t) => [t.value, t.singular]));
const MARGIN = 8; // px from the window's edge

/** A card for pages without an item box (ascendancies): name, kind, the intro. */
function fallbackCard(entity: Entity): Card {
  return {
    frame: entity.doc_type === "ascendancy" ? "ascendancy" : "normal",
    header: [entity.title ?? entity.name],
    groups: [
      { style: "default", lines: [[{ t: KIND[entity.doc_type] ?? "Wiki page", s: "default" }]] },
      ...(entity.summary ? [{ style: "default", lines: [[{ t: entity.summary, s: "value" }]] }] : []),
    ],
  };
}

/** A gem, unique or ascendancy name with its in-game tooltip on hover or focus. */
export function EntityName({ entity, children }: { entity: Entity; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<CSSProperties>({});
  const card = useRef<HTMLSpanElement>(null);
  const id = useId();

  // Keep the tooltip on screen: shift it left, or show it above the name.
  useLayoutEffect(() => {
    if (!open || !card.current) return;
    const box = card.current.getBoundingClientRect();
    // The layout width: innerWidth grows on phones once the card sticks out.
    const width = document.documentElement.clientWidth;
    const next: CSSProperties = {};
    if (box.right > width - MARGIN) next.left = width - MARGIN - box.right;
    if (box.left < MARGIN) next.left = MARGIN - box.left;
    if (box.bottom > window.innerHeight - MARGIN && box.top - box.height > MARGIN) {
      next.top = "auto";
      next.bottom = "calc(100% + 0.35rem)";
    }
    setPlacement(next);
  }, [open]);

  return (
    <span
      className="entity"
      data-type={entity.doc_type}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => {
        setOpen(false);
        setPlacement({});
      }}
    >
      <a
        href={entity.url}
        target="_blank"
        rel="noreferrer"
        className="entity-name"
        aria-describedby={open ? id : undefined}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          setOpen(false);
          setPlacement({});
        }}
      >
        {children}
      </a>
      {open && (
        <span role="tooltip" id={id} ref={card} className="entity-card" style={placement}>
          <ItemTooltip card={entity.card ?? fallbackCard(entity)} />
        </span>
      )}
    </span>
  );
}

import type { Card } from "./types";

/** A tooltip drawn like the game's: framed header, centred lines, separators. */
export function ItemTooltip({ card }: { card: Card }) {
  return (
    <span className="poe-tooltip" data-frame={card.frame}>
      <span className="poe-header" data-lines={card.header.length > 1 ? "double" : "single"}>
        {card.header.map((line) => (
          <span key={line} className="poe-header-line">
            {line}
          </span>
        ))}
      </span>
      <span className="poe-body">
        {card.groups.map((group, g) => (
          <span key={g} className="poe-group" data-style={group.style}>
            {group.lines.map((line, l) => (
              <span key={l} className="poe-line">
                {line.length === 0
                  ? " "
                  : line.map((segment, s) => (
                      <span key={s} data-style={segment.s}>
                        {segment.t}
                      </span>
                    ))}
              </span>
            ))}
          </span>
        ))}
      </span>
    </span>
  );
}

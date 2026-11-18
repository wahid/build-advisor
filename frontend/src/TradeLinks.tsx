import type { TradeSearch } from "./types";

function label(search: TradeSearch): string {
  const cap = search.max_price ? `, up to ${search.max_price} ${search.currency ?? "chaos"}` : "";
  return `${search.slot}${cap}`;
}

/** Links to pathofexile.com/trade: rare items for a slot, ranked by what they add to the build. */
export function TradeLinks({ searches, heading = "Trade searches" }: { searches: TradeSearch[]; heading?: string }) {
  if (!searches.length) return null;
  const league = searches[0].league;
  return (
    <section className="comparison trade-links" aria-label={heading}>
      <h3 className="pob-heading">{heading}</h3>
      <p className="comparison-note">
        Rare items on pathofexile.com/trade{league && ` (${league} league)`}, found by the mods Path of Building values
        for your build. The site lists them cheapest first; click a listing's "Sum" to sort by value. Searching needs a
        pathofexile.com login.
      </p>
      <ul className="trade-list">
        {searches.map((search) => (
          <li key={`${search.slot}-${search.max_price ?? ""}`}>
            <a href={search.url} target="_blank" rel="noreferrer" className="trade-link">
              {label(search)}
            </a>
            <span className="passive-stats">
              {search.item && (search.better_than_current ? `Better than your ${search.item}. ` : `You wear ${search.item}. `)}
              {search.best_mod && `Biggest single gain: ${search.best_mod}. `}
              {search.stats.length > 0 && `Valued by: ${search.stats.slice(0, 4).join("; ")}.`}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

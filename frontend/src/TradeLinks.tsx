import type { TradeSearch } from "./types";

function label(search: TradeSearch): string {
  const cap = search.max_price ? `, up to ${search.max_price} ${search.currency ?? "chaos"}` : "";
  return `${search.slot}${cap}`;
}

/** Links to pathofexile.com/trade: rare items for a slot with the mods the build gains most from. */
export function TradeLinks({ searches, heading = "Trade searches" }: { searches: TradeSearch[]; heading?: string }) {
  if (!searches.length) return null;
  const league = searches[0].league;
  return (
    <section className="comparison trade-links" aria-label={heading}>
      <h3 className="pob-heading">{heading}</h3>
      <p className="comparison-note">
        Rare items on pathofexile.com/trade{league && ` (${league} league)`} with the mods Path of Building values most
        for your build, cheapest first. You can change the minimums on the site. Searching needs a pathofexile.com
        login.
      </p>
      <ul className="trade-list">
        {searches.map((search) => (
          <li key={`${search.slot}-${search.max_price ?? ""}`}>
            <a href={search.url} target="_blank" rel="noreferrer" className="trade-link">
              {label(search)}
            </a>
            <span className="passive-stats">
              {search.item && `You wear ${search.item}. `}
              {search.best_mod && `Biggest single gain: ${search.best_mod}. `}
              {search.stats.length > 0 && `At least ${search.need} of: ${search.stats.join("; ")}.`}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

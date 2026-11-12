import { useEffect, useState } from "react";

function remaining(until: number, now: number): string {
  const minutes = Math.max(1, Math.ceil((until - now) / 60_000));
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} h ${minutes % 60} min` : `${minutes} min`;
}

/** Shown while the site's questions for today are used up, with a countdown. */
export function LimitBanner({ until, onOver }: { until: number; onOver: () => void }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (now >= until) onOver();
  }, [now, until, onOver]);
  if (now >= until) return null;
  return (
    <p className="limit-banner" role="status">
      Today's questions for this free demo are used up. It opens again in {remaining(until, now)} (midnight UTC).
      Your chats stay here in the meantime.
    </p>
  );
}

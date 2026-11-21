import Link from "next/link";
import type { Insight, Milestone } from "@/lib/api";

const ICON: Record<string, string> = {
  first_species: "🎉",
  first_this_year: "📅",
  back_after: "👋",
  record_night: "🌙",
  new_species_count: "🏅",
  timing_vs_sun: "🌇",
  usual_time: "🕰️",
  trend: "📈",
  moon: "🌕",
  regular: "🔁",
  together: "🤝",
  quiet: "📉",
  rain: "🌧️",
};

/** Milestones first, then the strongest insights. Every line links to its evidence. */
export default function Highlights({ milestones, insights, limit = 6 }: { milestones: Milestone[]; insights: Insight[]; limit?: number }) {
  const items = [
    ...milestones.map((m) => ({
      key: `m${m.id}`,
      icon: ICON[m.kind] ?? "⭐",
      text: m.text,
      note: m.status === "awaiting_confirmation" ? "Not confirmed yet" : m.night,
      href: m.encounter_id ? `/encounters/${m.encounter_id}` : null,
    })),
    ...insights.map((i) => ({
      key: i.id,
      icon: ICON[i.kind] ?? "💡",
      text: i.text,
      note: `Based on ${i.n} visit${i.n === 1 ? "" : "s"}`,
      href: i.species ? `/species/${encodeURIComponent(i.species)}` : i.encounter_ids[0] ? `/encounters/${i.encounter_ids[0]}` : null,
    })),
  ].slice(0, limit);

  if (!items.length) {
    return <p className="muted">Not enough visits yet to spot patterns. Check back in a couple of weeks.</p>;
  }
  return (
    <ul className="highlights">
      {items.map((it) => {
        const body = (
          <>
            <span className="hl-icon" aria-hidden>
              {it.icon}
            </span>
            <span className="hl-text">
              {it.text}
              <small>{it.note}</small>
            </span>
          </>
        );
        return <li key={it.key}>{it.href ? <Link href={it.href}>{body}</Link> : <div>{body}</div>}</li>;
      })}
    </ul>
  );
}

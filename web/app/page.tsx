import Link from "next/link";
import { Facts, Hero, LastNight, Regulars, RecentGrid } from "@/components/HomeSections";
import Offline from "@/components/Offline";
import { edge, EdgeUnavailable, qs, type Activity, type EncounterSummary, type SpeciesSummary } from "@/lib/api";
import { TZ } from "@/lib/format";
import { lastNightWindow } from "@/lib/night";

export const dynamic = "force-dynamic";

type Search = Promise<{ species?: string; uncertain?: string }>;

function hourLabel(h: number) {
  return `${h % 12 === 0 ? 12 : h % 12} ${h < 12 ? "am" : "pm"}`;
}

export default async function Home({ searchParams }: { searchParams: Search }) {
  const { species, uncertain } = await searchParams;
  const now = new Date();
  const night = lastNightWindow(now, TZ);
  let encounters: EncounterSummary[];
  let summary: SpeciesSummary[];
  let lastNight: EncounterSummary[];
  let act: Activity;
  try {
    [encounters, summary, lastNight, act] = await Promise.all([
      edge<EncounterSummary[]>(`/api/encounters${qs({ species, uncertain, limit: "60" })}`),
      edge<SpeciesSummary[]>("/api/species"),
      edge<EncounterSummary[]>(`/api/encounters${qs({ date_from: night.from, date_to: night.to, limit: "50" })}`),
      edge<Activity>("/api/activity"),
    ]);
  } catch (e) {
    return <Offline message={e instanceof EdgeUnavailable ? e.message : undefined} />;
  }

  const filtered = Boolean(species || uncertain);
  const peak = [...act.by_hour].sort((a, b) => b.count - a.count)[0];

  if (!filtered && encounters.length === 0) {
    return (
      <div className="notice">
        <h2>No visitors yet</h2>
        <p>
          Once the camera uploads a photo with an animal in it, it shows up here within a minute. To try it now, import
          some photos: <code>uv run observatory import &lt;folder&gt;</code>.
        </p>
      </div>
    );
  }

  const [latest, ...rest] = encounters;

  return (
    <>
      {!filtered ? (
        <>
          <LastNight visits={lastNight} fallback={encounters.slice(0, 3)} now={now} />
          <Hero e={latest} />
          <Facts
            species={summary.length}
            visits={act.total}
            busiest={peak && peak.count > 0 ? hourLabel(peak.hour) : "–"}
            lastNight={lastNight.length}
          />
        </>
      ) : null}

      <section className="section" aria-labelledby="regulars-h">
        <div className="section-head">
          <h2 id="regulars-h">The regulars</h2>
          <span className="muted">{filtered ? <Link href="/">Show everyone</Link> : "Tap one to see all its visits"}</span>
        </div>
        <Regulars species={summary} active={species} />
      </section>

      <section className="section" aria-labelledby="recent-h">
        <div className="section-head">
          <h2 id="recent-h">{filtered ? `Every ${species ?? "uncertain"} visit` : "Recent visits"}</h2>
          <span className="muted">
            {filtered ? `${encounters.length} visits` : <Link href="/gallery">All photos</Link>} ·{" "}
            <Link href="/?uncertain=true">Needs a second look</Link>
          </span>
        </div>
        {encounters.length === 0 ? (
          <div className="notice">No visits match this filter.</div>
        ) : (
          <RecentGrid items={(filtered ? encounters : rest).slice(0, 13)} />
        )}
      </section>
    </>
  );
}

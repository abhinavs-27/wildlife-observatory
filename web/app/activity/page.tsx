import Link from "next/link";
import ActivityClock from "@/components/ActivityClock";
import BarChart from "@/components/BarChart";
import Offline from "@/components/Offline";
import { edge, EdgeUnavailable, qs, type ActivityFull, type SpeciesSummary } from "@/lib/api";

export const dynamic = "force-dynamic";

function hourLabel(h: number) {
  return `${h % 12 === 0 ? 12 : h % 12}${h < 12 ? "a" : "p"}`;
}

export default async function ActivityPage({ searchParams }: { searchParams: Promise<{ species?: string }> }) {
  const { species } = await searchParams;
  let act: ActivityFull;
  let summary: SpeciesSummary[];
  try {
    [act, summary] = await Promise.all([
      edge<ActivityFull>(`/api/activity${qs({ species })}`),
      edge<SpeciesSummary[]>("/api/species"),
    ]);
  } catch (e) {
    return <Offline message={e instanceof EdgeUnavailable ? e.message : undefined} />;
  }
  const peak = [...act.by_hour].sort((a, b) => b.count - a.count)[0];

  return (
    <>
      <h1 style={{ marginBottom: 6 }}>{species ? `When ${species} visit` : "When animals visit"}</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        {act.total} sightings, counted once per visit (not per photo). Times are {act.timezone}.
        {peak && peak.count > 0 ? ` Busiest hour: ${hourLabel(peak.hour)}m.` : ""}
      </p>
      <div className="filters" role="group" aria-label="Species">
        <Link className="chip" href="/activity" aria-current={!species}>
          All species
        </Link>
        {summary.map((s) => (
          <Link key={s.species} className="chip" href={`/activity?species=${encodeURIComponent(s.species)}`} aria-current={species === s.species}>
            {s.species}
          </Link>
        ))}
      </div>
      {act.total === 0 ? (
        <div className="notice">No sightings to chart yet.</div>
      ) : (
        <div className="grid-2">
          <div className="clock-row">
            <ActivityClock points={act.points} night={act.night} single={Boolean(species)} title={species ? `When ${species} visit` : "When visits happen"} />
            <BarChart
              title="By hour of day"
              tickEvery={3}
              data={act.by_hour.map((h) => ({ key: String(h.hour), label: hourLabel(h.hour), count: h.count }))}
            />
          </div>
          <BarChart
            title="By day"
            tickEvery={Math.max(1, Math.ceil(act.by_day.length / 10))}
            data={act.by_day.map((d) => ({ key: d.day, label: d.day.slice(5), count: d.count }))}
          />
        </div>
      )}
    </>
  );
}

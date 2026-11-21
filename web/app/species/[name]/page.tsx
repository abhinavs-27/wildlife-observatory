import Link from "next/link";
import { notFound } from "next/navigation";
import ActivityClock from "@/components/ActivityClock";
import CalendarHeatmap from "@/components/CalendarHeatmap";
import Highlights from "@/components/Highlights";
import LitImage from "@/components/LitImage";
import Offline from "@/components/Offline";
import { RecentGrid } from "@/components/HomeSections";
import { edge, EdgeUnavailable, qs, type ActivityFull, type SpeciesDetail } from "@/lib/api";
import { localTime } from "@/lib/format";

export const dynamic = "force-dynamic";

const ACTIVITY: Record<string, string> = {
  nocturnal: "Mostly active at night",
  diurnal: "Mostly active during the day",
  crepuscular: "Most active at dawn and dusk",
  cathemeral: "Active at any time of day or night",
};

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export default async function SpeciesPage({ params }: { params: Promise<{ name: string }> }) {
  const name = decodeURIComponent((await params).name);
  let d: SpeciesDetail;
  let act: ActivityFull;
  try {
    [d, act] = await Promise.all([
      edge<SpeciesDetail>(`/api/species/${encodeURIComponent(name)}`),
      edge<ActivityFull>(`/api/activity${qs({ species: name })}`),
    ]);
  } catch (e) {
    if (e instanceof Error && e.message === "not-found") notFound();
    return <Offline message={e instanceof EdgeUnavailable ? e.message : undefined} />;
  }
  const info = d.info;
  const facts = info.facts;
  const sentences = (info.extract ?? "").split(/(?<=\.)\s+/).slice(0, 3).join(" ");
  const cover = d.gallery[0];

  return (
    <>
      <p>
        <Link href="/">All sightings</Link>
      </p>
      <section className="species-head">
        <div className="species-cover">
          {cover?.best_frame_id != null ? <LitImage src={`/frames/${cover.best_frame_id}/file`} alt={name} loading="eager" /> : <div className="withheld">No photo yet</div>}
          <div className="shade" aria-hidden />
          <div className="cap">
            <h1>{cap(name)}</h1>
            {info.scientific_name ? <p className="sci">{info.scientific_name.charAt(0).toUpperCase() + info.scientific_name.slice(1)}</p> : null}
            <div className="badges">
              {facts?.nj_status ? <span className={`badge ${/endangered|threatened|concern|rare/.test(facts.nj_status) ? "warn" : ""}`}>NJ: {facts.nj_status}</span> : null}
              {d.any_uncertain ? <span className="badge">Some IDs uncertain</span> : null}
            </div>
          </div>
        </div>
      </section>

      {d.rolled_up ? (
        <p className="notice" style={{ marginTop: 16 }}>
          The model couldn&apos;t tell the exact species in these photos, so they&apos;re grouped as &ldquo;{name}&rdquo;. You can
          relabel any visit from its sighting page.
        </p>
      ) : null}

      <section className="section species-grid">
        <div>
          <h2>In your yard</h2>
          <dl className="facts" style={{ marginTop: 0 }}>
            <div><dt>visits</dt><dd>{d.encounters}</dd></div>
            <div><dt>first seen</dt><dd>{localTime(d.first_seen, { hour: undefined, minute: undefined, year: "numeric" })}</dd></div>
            <div><dt>last seen</dt><dd>{localTime(d.last_seen, { hour: undefined, minute: undefined, year: "numeric" })}</dd></div>
            <div><dt>usual time</dt><dd>{d.usual_time ?? "–"}</dd></div>
          </dl>
          <h3 style={{ margin: "22px 0 8px" }}>What we&apos;ve noticed</h3>
          <Highlights milestones={d.milestones} insights={d.insights} limit={8} />
        </div>
        <div className="clock-wrap">
          <ActivityClock points={act.points} night={act.night} size={300} single title={`When ${name} visit`} />
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Visits by day</h2>
          <span className="muted">
            {d.calendar_total_in_range} in the 26 weeks up to {d.calendar.at(-1)?.date}
          </span>
        </div>
        <CalendarHeatmap days={d.calendar} label={`${name} visits by day`} />
      </section>

      <section className="section about">
        <h2>About the {name}</h2>
        <div className="about-grid">
          <div>
            {info.status === "ok" && sentences ? (
              <>
                <p className="about-text">{sentences}</p>
                <p className="muted" style={{ fontSize: "0.85rem" }}>
                  From Wikipedia{info.wiki_title ? ` (“${info.wiki_title}”)` : ""}, CC BY-SA.{" "}
                  {info.page_url ? (
                    <a href={info.page_url} target="_blank" rel="noreferrer">
                      Read more
                    </a>
                  ) : null}
                </p>
              </>
            ) : info.status === "missing" ? (
              <p className="muted">There&apos;s no encyclopedia entry for this label.</p>
            ) : (
              <p className="muted">General information will appear once the observatory has been online to fetch it.</p>
            )}
            {facts ? (
              <dl className="kv" style={{ marginTop: 14 }}>
                <dt>Active</dt>
                <dd>{ACTIVITY[facts.activity] ?? facts.activity}</dd>
                <dt>Size</dt>
                <dd>{facts.size}</dd>
                <dt>Eats</dt>
                <dd>{facts.diet}</dd>
                <dt>In New Jersey</dt>
                <dd>{facts.nj_status}</dd>
              </dl>
            ) : null}
          </div>
          {info.has_image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img className="wiki-img" src={`/api/species/${encodeURIComponent(name)}/image`} alt={`${name}, from Wikipedia`} />
          ) : null}
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Every visit</h2>
          <span className="muted">{d.encounters} total</span>
        </div>
        <RecentGrid items={d.gallery} />
      </section>
    </>
  );
}

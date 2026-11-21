import Link from "next/link";
import type { EncounterSummary, SpeciesSummary } from "@/lib/api";
import { localTime, pct } from "@/lib/format";
import { heroTitle, moonPhase } from "@/lib/night";
import { portraitStyle } from "@/lib/portrait";
import LitImage, { Portrait } from "./LitImage";

const frameSrc = (id: number | null) => (id == null ? null : `/frames/${id}/file`);
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function shortName(e: EncounterSummary): string {
  const s = e.species[0];
  if (!s || s.species === "pending") return "Identifying…";
  return s.uncertain ? `${cap(s.species)}?` : cap(s.species);
}

export function LastNight({ visits, fallback, now }: { visits: EncounterSummary[]; fallback: EncounterSummary[]; now: Date }) {
  const moon = moonPhase(now);
  const empty = visits.length === 0;
  const items = (empty ? fallback : [...visits].reverse()).slice(0, 4);
  return (
    <section className="film" aria-label="Last night" style={{ ["--n" as string]: Math.max(items.length, 1) }}>
      <div className="night">
        <b>Last night</b>
        {empty ? (
          <span>
            No visitors.
            {fallback[0] ? <> Most recent: {localTime(fallback[0].start_at, { hour: undefined, minute: undefined })}</> : null}
          </span>
        ) : (
          <span>
            {visits.length} visitor{visits.length === 1 ? "" : "s"}, dusk to dawn
          </span>
        )}
        <em>☾ {moon.name.toLowerCase()}</em>
      </div>
      {items.map((e) => (
        <Link key={e.id} href={`/encounters/${e.id}`} className="frame">
          {e.best_frame_id != null ? <LitImage src={`/frames/${e.best_frame_id}/file`} alt={shortName(e)} /> : <div className="withheld">Photo withheld</div>}
          <span className="when">{localTime(e.start_at, empty ? { hour: undefined, minute: undefined } : { month: undefined, day: undefined })}</span>
          <em>{shortName(e)}</em>
        </Link>
      ))}
    </section>
  );
}

export function Hero({ e }: { e: EncounterSummary }) {
  const s = e.species[0];
  const title = heroTitle(e.species);
  const when = localTime(e.start_at, { weekday: "long", month: undefined, day: undefined });
  const sure = s && s.species !== "pending" && s.confidence ? ` · ${pct(s.confidence)} sure` : "";
  return (
    <section className="hero" aria-label="Latest visitor">
      {e.best_frame_id != null ? (
        <LitImage src={`/frames/${e.best_frame_id}/file`} alt={title} loading="eager" />
      ) : (
        <div className="withheld">Photo withheld: a person is in the frame</div>
      )}
      <div className="shade" aria-hidden />
      {e.best_bbox ? (
        <div
          className="glowbox"
          aria-hidden
          style={{ left: `${e.best_bbox[0] * 100}%`, top: `${e.best_bbox[1] * 100}%`, width: `${e.best_bbox[2] * 100}%`, height: `${e.best_bbox[3] * 100}%` }}
        />
      ) : null}
      <span className="stamp">{localTime(e.start_at, { second: "2-digit" })} · {e.device}</span>
      <div className="cap">
        <div>
          <h1>{title}</h1>
          <p>
            Visited {when}
            {sure} · {e.media_count} photo{e.media_count === 1 ? "" : "s"}
          </p>
        </div>
        <Link className="pill" href={`/encounters/${e.id}`}>
          See the visit
        </Link>
      </div>
    </section>
  );
}

export function Facts({ species, visits, busiest, lastNight }: { species: number; visits: number; busiest: string; lastNight: number }) {
  return (
    <dl className="facts">
      <div><dt>species so far</dt><dd>{species}</dd></div>
      <div><dt>visits</dt><dd>{visits}</dd></div>
      <div><dt>busiest hour</dt><dd>{busiest}</dd></div>
      <div><dt>visitors last night</dt><dd>{lastNight}</dd></div>
    </dl>
  );
}

export function Regulars({ species, active }: { species: SpeciesSummary[]; active?: string }) {
  const newest = species.reduce<string | null>((best, s) => (!best || s.last_seen > (species.find((x) => x.species === best)?.last_seen ?? "") ? s.species : best), null);
  return (
    <ul className="regulars">
      {species.map((s) => (
        <li key={s.species}>
          <Link href={active === s.species ? "/" : `/?species=${encodeURIComponent(s.species)}`} aria-current={active === s.species}>
            {s.best_frame_id != null && s.best_bbox ? (
              <Portrait
                src={frameSrc(s.best_frame_id)}
                style={portraitStyle(s.best_bbox)}
                className={`portrait ${s.species === newest ? "newest" : ""} ${s.any_uncertain ? "unsure" : ""}`}
              />
            ) : (
              <i className={`portrait initial ${s.any_uncertain ? "unsure" : ""}`} aria-hidden>
                {s.species.charAt(0).toUpperCase()}
              </i>
            )}
            <b>{cap(s.species)}</b>
            <span>
              {s.encounters} visit{s.encounters === 1 ? "" : "s"}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function RecentGrid({ items }: { items: EncounterSummary[] }) {
  return (
    <div className="bento">
      {items.map((e, i) => (
        <Link key={e.id} href={`/encounters/${e.id}`} className={`tile ${i === 0 ? "big" : ""}`}>
          {e.best_frame_id != null ? <LitImage src={`/frames/${e.best_frame_id}/file`} alt={shortName(e)} /> : <div className="withheld">Photo withheld</div>}
          <div className="lab">
            <b>{shortName(e)}</b>
            <span>{localTime(e.start_at)}</span>
          </div>
        </Link>
      ))}
    </div>
  );
}

import Link from "next/link";
import Offline from "@/components/Offline";
import Photo from "@/components/Photo";
import { edge, EdgeUnavailable, qs, type EncounterSummary, type SpeciesSummary } from "@/lib/api";
import { localTime, speciesLine } from "@/lib/format";

export const dynamic = "force-dynamic";

type Search = Promise<{ species?: string; uncertain?: string }>;

function topSpecies(e: EncounterSummary) {
  const s = e.species[0];
  if (!s) return { name: "Animal", conf: undefined };
  if (s.species === "pending") return { name: "Identifying…", conf: undefined };
  return { name: s.uncertain ? `${s.species}?` : s.species, conf: s.confidence };
}

export default async function Home({ searchParams }: { searchParams: Search }) {
  const { species, uncertain } = await searchParams;
  let encounters: EncounterSummary[];
  let summary: SpeciesSummary[];
  try {
    [encounters, summary] = await Promise.all([
      edge<EncounterSummary[]>(`/api/encounters${qs({ species, uncertain, limit: "60" })}`),
      edge<SpeciesSummary[]>("/api/species"),
    ]);
  } catch (e) {
    return <Offline message={e instanceof EdgeUnavailable ? e.message : undefined} />;
  }

  const [latest, ...rest] = encounters;
  const filtered = Boolean(species || uncertain);

  return (
    <>
      {latest && !filtered ? (
        <section className="lead" aria-label="Latest sighting">
          <Link href={`/encounters/${latest.id}`}>
            <Photo
              frameId={latest.best_frame_id}
              alt={speciesLine(latest.species)}
              boxes={latest.best_bbox ? [{ bbox: latest.best_bbox }] : []}
              capturedAt={latest.start_at}
              species={topSpecies(latest).name}
              confidence={topSpecies(latest).conf}
              hiddenReason={latest.best_frame_id == null ? "Photo withheld: a person is in frame" : undefined}
            />
          </Link>
          <div className="facts">
            <h1>{speciesLine(latest.species)}</h1>
            <p>
              Latest visit, {localTime(latest.start_at, { weekday: "long" })}.{" "}
              {latest.status === "pending"
                ? "Species identification is still running; the photo was flagged as an animal by MegaDetector."
                : "Identified by SpeciesNet with the New Jersey location filter."}
            </p>
            <dl className="kv">
              <dt>Camera</dt>
              <dd>{latest.device}</dd>
              <dt>Photos</dt>
              <dd>{latest.media_count}</dd>
              <dt>Species seen</dt>
              <dd>{summary.length}</dd>
            </dl>
            <p>
              <Link className="button" href={`/encounters/${latest.id}`}>
                Open this sighting
              </Link>
            </p>
          </div>
        </section>
      ) : null}

      <section className="section" aria-labelledby="species-h">
        <div className="section-head">
          <h2 id="species-h">Species</h2>
          {filtered ? <Link href="/">Show all sightings</Link> : null}
        </div>
        <ul className="species-list">
          {summary.map((s) => (
            <li key={s.species}>
              <Link
                className={`chip ${s.any_uncertain ? "unc" : ""}`}
                href={`/?species=${encodeURIComponent(s.species)}`}
                aria-current={species === s.species}
              >
                {s.species} <b>{s.encounters}</b>
              </Link>
            </li>
          ))}
          <li>
            <Link className="chip unc" href="/?uncertain=true" aria-current={uncertain === "true"}>
              Needs review
            </Link>
          </li>
        </ul>
      </section>

      <section className="section" aria-labelledby="recent-h">
        <div className="section-head">
          <h2 id="recent-h">{filtered ? `${species ?? "Uncertain"} sightings` : "Recent sightings"}</h2>
          <span className="muted">{encounters.length} shown</span>
        </div>
        {encounters.length === 0 ? (
          <div className="notice">
            No sightings yet. Import photos with <code>uv run observatory import &lt;folder&gt;</code> or point the camera&apos;s
            FTP upload at the Pi.
          </div>
        ) : (
          <div className="strip">
            {(filtered ? encounters : rest).map((e) => (
              <Link key={e.id} href={`/encounters/${e.id}`}>
                <Photo
                  frameId={e.best_frame_id}
                  alt={speciesLine(e.species)}
                  boxes={e.best_bbox ? [{ bbox: e.best_bbox }] : []}
                  capturedAt={e.start_at}
                  species={topSpecies(e).name}
                  confidence={topSpecies(e).conf}
                  hiddenReason={e.best_frame_id == null ? "Photo withheld: person in frame" : undefined}
                />
                <div className="caption">
                  {speciesLine(e.species)} · {e.media_count} photo{e.media_count === 1 ? "" : "s"}
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </>
  );
}

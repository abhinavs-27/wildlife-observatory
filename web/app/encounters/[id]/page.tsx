import Link from "next/link";
import { notFound } from "next/navigation";
import CorrectionForm from "@/components/CorrectionForm";
import Offline from "@/components/Offline";
import Photo from "@/components/Photo";
import Replay from "@/components/Replay";
import { edge, EdgeUnavailable, type EncounterDetail, type ReplayFrame } from "@/lib/api";
import { localTime, pct, speciesLine } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function EncounterPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let enc: EncounterDetail;
  let frames: ReplayFrame[] = [];
  try {
    [enc, frames] = await Promise.all([
      edge<EncounterDetail>(`/api/encounters/${id}`),
      edge<ReplayFrame[]>(`/api/encounters/${id}/frames`),
    ]);
  } catch (e) {
    if (e instanceof Error && e.message === "not-found") notFound();
    return <Offline message={e instanceof EdgeUnavailable ? e.message : undefined} />;
  }

  const animalDets = enc.media.flatMap((m) => m.detections.filter((d) => d.category === "animal"));
  const labelOptions = Array.from(
    new Set(animalDets.flatMap((d) => d.classification?.raw_topk.map((t) => t.label.split(";").pop() || "") ?? [])),
  ).filter(Boolean);

  return (
    <>
      <p>
        <Link href="/">All sightings</Link>
      </p>
      <h1 className="title-cap" style={{ marginBottom: 6 }}>{speciesLine(enc.species)}</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        {localTime(enc.start_at, { weekday: "long", year: "numeric" })}
        {enc.end_at !== enc.start_at ? ` to ${localTime(enc.end_at, { month: undefined, day: undefined })}` : ""} ·{" "}
        {enc.device} · {enc.media.length} photo{enc.media.length === 1 ? "" : "s"} · {enc.tracks.length} track
        {enc.tracks.length === 1 ? "" : "s"}{" "}
        {enc.status === "pending" ? <span className="badge warn">Identifying</span> : null}
        {enc.status === "rejected" ? <span className="badge bad">Marked not an animal</span> : null}
      </p>

      <div className="detail">
        <div className="frames">
          {frames.length > 1 ? (
            <figure style={{ margin: 0 }}>
              <Replay frames={frames} alt={speciesLine(enc.species)} controls className="player" />
              <figcaption className="muted" style={{ fontSize: "0.85rem", paddingTop: 4 }}>
                The whole visit, {frames.length} frames in order. Tap to pause.
              </figcaption>
            </figure>
          ) : null}
          {enc.media.map((m) =>
            m.frames
              .filter((f) => m.detections.some((d) => d.frame_id === f.id) || m.frames.length === 1)
              .map((f) => {
                const dets = m.detections.filter((d) => d.frame_id === f.id);
                const top = dets.find((d) => d.category === "animal");
                return (
                  <figure key={f.id} style={{ margin: 0 }}>
                    <Photo
                      frameId={f.id}
                      alt={`${m.original_name} frame ${f.idx}`}
                      capturedAt={new Date(new Date(m.captured_at).getTime() + f.time_offset_s * 1000).toISOString()}
                      species={top?.classification?.common_name}
                      confidence={top?.classification?.score}
                      boxes={dets.map((d) => ({
                        bbox: d.bbox,
                        kind: d.category,
                        label:
                          d.category === "animal"
                            ? `${d.classification?.common_name ?? "animal"} ${pct(d.classification?.score ?? d.confidence)}`
                            : `${d.category} ${pct(d.confidence)}`,
                      }))}
                    />
                    <figcaption className="muted" style={{ fontSize: "0.85rem", paddingTop: 4 }}>
                      {m.original_name}
                      {m.kind === "video" ? ` · frame at ${f.time_offset_s.toFixed(1)} s` : ""} · time from{" "}
                      {m.captured_at_source}
                      {m.has_person ? " · contains a person (kept private)" : ""}
                    </figcaption>
                  </figure>
                );
              }),
          )}
        </div>

        <aside>
          <div className="panel">
            <h3>What the models saw</h3>
            {animalDets.length === 0 ? <p className="muted">No animal detections in this sighting.</p> : null}
            {animalDets.map((d) => (
              <div key={d.id} style={{ marginTop: 12 }}>
                <div>
                  {d.classification?.common_name ? (
                    <Link href={`/species/${encodeURIComponent(d.classification.common_name)}`}>
                      <b>{d.classification.common_name}</b>
                    </Link>
                  ) : (
                    <b>Not identified yet</b>
                  )}{" "}
                  {d.classification ? (
                    d.classification.is_uncertain ? (
                      <span className="badge warn">Uncertain</span>
                    ) : (
                      <span className="badge ok">{pct(d.classification.score)}</span>
                    )
                  ) : (
                    <span className="badge">Pending</span>
                  )}
                  {d.correction ? <span className="badge"> {d.correction.action}ed</span> : null}
                </div>
                <div className="tax">
                  Detected by {d.model} {d.model_version} at {pct(d.confidence)}
                  {d.classification
                    ? ` · ${d.classification.model} ${d.classification.model_version}, ${d.classification.rollup_level} level, source ${d.classification.source ?? "n/a"}, geofence ${d.classification.geofence}`
                    : ""}
                </div>
                {d.classification ? (
                  <>
                    <div className="tax">
                      {[d.classification.taxon_class, d.classification.taxon_order, d.classification.taxon_family, d.classification.taxon_genus, d.classification.taxon_species]
                        .filter(Boolean)
                        .join(" › ")}
                    </div>
                    <ul className="topk" aria-label="Classifier's top guesses">
                      {d.classification.raw_topk.map((t) => (
                        <li key={t.label}>
                          <span>{t.label.split(";").pop()}</span>
                          <span>{pct(t.score)}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </div>
            ))}
          </div>

          <div className="panel">
            <h3>Correct this sighting</h3>
            <p className="muted" style={{ fontSize: "0.9rem" }}>
              Corrections are saved alongside the model&apos;s prediction; nothing is overwritten.
            </p>
            <CorrectionForm encounterId={enc.id} suggestions={labelOptions} />
            {enc.corrections.length ? (
              <ul className="topk">
                {enc.corrections.map((c) => (
                  <li key={c.id}>
                    <span>
                      {c.action}
                      {c.label ? `: ${c.label}` : ""}
                    </span>
                    <span className="muted">{localTime(c.created_at)}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>

          <div className="panel">
            <h3>Alerts</h3>
            {enc.alerts.length === 0 ? (
              <p className="muted">No alert for this sighting (imported in bulk, too old, or low confidence).</p>
            ) : (
              <ul className="topk">
                {enc.alerts.map((a) => (
                  <li key={a.id}>
                    <span>{a.body}</span>
                    <span className="muted">{a.status}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      </div>
    </>
  );
}

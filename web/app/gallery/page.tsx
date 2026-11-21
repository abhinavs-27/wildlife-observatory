import Link from "next/link";
import Offline from "@/components/Offline";
import { edge, EdgeUnavailable, qs, type MediaItem, type SpeciesSummary } from "@/lib/api";
import { localTime } from "@/lib/format";

export const dynamic = "force-dynamic";

type Search = Promise<{ species?: string; status?: string; kind?: string }>;

const STATUS_LABEL: Record<string, string> = {
  detected: "Animal",
  empty: "Empty",
  pending: "Waiting for detection",
  failed: "Failed",
};

export default async function Gallery({ searchParams }: { searchParams: Search }) {
  const { species, status, kind } = await searchParams;
  let media: MediaItem[];
  let summary: SpeciesSummary[];
  try {
    [media, summary] = await Promise.all([
      edge<MediaItem[]>(`/api/media${qs({ species, status, kind, limit: "120" })}`),
      edge<SpeciesSummary[]>("/api/species"),
    ]);
  } catch (e) {
    return <Offline message={e instanceof EdgeUnavailable ? e.message : undefined} />;
  }

  const link = (p: Record<string, string | undefined>) => `/gallery${qs({ species, status, kind, ...p })}`;

  return (
    <>
      <h1 style={{ marginBottom: 16 }}>Photos and clips</h1>
      <div className="filters" role="group" aria-label="Filters">
        <Link className="chip" href="/gallery" aria-current={!species && !status && !kind}>
          Everything
        </Link>
        {["detected", "empty", "failed"].map((s) => (
          <Link key={s} className="chip" href={link({ status: status === s ? undefined : s })} aria-current={status === s}>
            {STATUS_LABEL[s]}
          </Link>
        ))}
        <Link className="chip" href={link({ kind: kind === "video" ? undefined : "video" })} aria-current={kind === "video"}>
          Videos
        </Link>
        {summary.map((s) => (
          <Link
            key={s.species}
            className="chip"
            href={link({ species: species === s.species ? undefined : s.species })}
            aria-current={species === s.species}
          >
            {s.species}
          </Link>
        ))}
      </div>
      <p className="muted">Photos with people in them are hidden here for privacy; they stay available inside each sighting.</p>
      {media.length === 0 ? (
        <div className="notice">Nothing matches these filters.</div>
      ) : (
        <div className="gallery">
          {media.map((m) => {
            const body =
              m.frame_id != null ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={`/frames/${m.frame_id}/file`} alt={m.original_name} loading="lazy" style={{ borderRadius: 3, aspectRatio: "4/3", objectFit: "cover", width: "100%" }} />
              ) : (
                <div className="empty-photo">{m.status === "failed" ? `Couldn't process: ${m.error ?? "unknown error"}` : m.kind === "video" ? "Video (no animal frames)" : "No preview"}</div>
              );
            return (
              <figure key={m.id}>
                {m.encounter_id ? <Link href={`/encounters/${m.encounter_id}`}>{body}</Link> : body}
                <figcaption>
                  <span>{localTime(m.captured_at)}</span>
                  <span>
                    {m.kind === "video" ? "Video · " : ""}
                    {STATUS_LABEL[m.status] ?? m.status}
                    {m.n_animals > 1 ? ` (${m.n_animals})` : ""}
                  </span>
                </figcaption>
              </figure>
            );
          })}
        </div>
      )}
    </>
  );
}

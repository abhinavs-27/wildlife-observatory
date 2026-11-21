import Link from "next/link";
import type { Digest } from "@/lib/api";
import LitImage from "./LitImage";

export default function DigestView({ d }: { d: Digest }) {
  return (
    <div className="digest">
      <div className="digest-photo">
        {d.best_frame_id != null ? (
          <Link href={`/encounters/${d.best_encounter_id}`}>
            <LitImage src={`/frames/${d.best_frame_id}/file`} alt={d.best_species ?? "Photo of the week"} loading="eager" />
            <span className="stamp">Photo of the week · {d.best_species}</span>
          </Link>
        ) : (
          <div className="withheld">No photo this week</div>
        )}
      </div>
      <div className="digest-body">
        <h2>{d.headline}</h2>
        {d.species_counts.length ? (
          <ul className="species-list" style={{ margin: "10px 0 14px" }}>
            {d.species_counts.map(([sp, n]) => (
              <li key={sp}>
                <Link className="chip" href={`/species/${encodeURIComponent(sp)}`}>
                  {sp} <b>{n}</b>
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
        {d.new_species.length ? <p className="new-species">New this week: {d.new_species.join(", ")}!</p> : null}
        {d.highlights.length ? (
          <ul className="digest-highlights">
            {d.highlights.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">No highlights yet.</p>
        )}
      </div>
    </div>
  );
}

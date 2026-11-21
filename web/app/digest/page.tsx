import Link from "next/link";
import DigestView from "@/components/DigestView";
import Offline from "@/components/Offline";
import { edge, EdgeUnavailable, type Digest, type DigestSummary } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function DigestIndex() {
  let current: Digest;
  let past: DigestSummary[];
  try {
    [current, past] = await Promise.all([edge<Digest>("/api/digests/current"), edge<DigestSummary[]>("/api/digests")]);
  } catch (e) {
    return <Offline message={e instanceof EdgeUnavailable ? e.message : undefined} />;
  }
  return (
    <>
      <h1 style={{ marginBottom: 4 }}>This week in the yard</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        So far this week (since Monday). Every Monday at 8 am the full week is sent as a push to you and the family channel.
      </p>
      <DigestView d={current} />
      <section className="section">
        <h2>Past weeks</h2>
        {past.length === 0 ? (
          <p className="muted">The first weekly summary goes out next Monday morning.</p>
        ) : (
          <ul className="digest-list">
            {past.map((p) => (
              <li key={p.week}>
                <Link href={`/digest/${p.week}`}>
                  <b>
                    {p.start} to {p.end}
                  </b>
                  <span>{p.headline}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

import Link from "next/link";
import { notFound } from "next/navigation";
import DigestView from "@/components/DigestView";
import Offline from "@/components/Offline";
import { edge, EdgeUnavailable, type Digest } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function DigestWeek({ params }: { params: Promise<{ week: string }> }) {
  const { week } = await params;
  let d: Digest;
  try {
    d = await edge<Digest>(`/api/digests/${encodeURIComponent(week)}`);
  } catch (e) {
    if (e instanceof Error && e.message === "not-found") notFound();
    return <Offline message={e instanceof EdgeUnavailable ? e.message : undefined} />;
  }
  return (
    <>
      <p>
        <Link href="/digest">All weeks</Link>
      </p>
      <h1 style={{ marginBottom: 4 }}>
        Week of {d.start}
      </h1>
      <p className="muted" style={{ marginTop: 0 }}>
        {d.start} to {d.end}
      </p>
      <DigestView d={d} />
    </>
  );
}

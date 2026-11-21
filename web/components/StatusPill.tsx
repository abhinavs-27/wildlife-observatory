import Link from "next/link";
import { edge, type Health } from "@/lib/api";

export default async function StatusPill() {
  let health: Health | null = null;
  try {
    health = await edge<Health>("/api/health/details");
  } catch {
    health = null;
  }
  if (!health) {
    return (
      <Link href="/status" className="status-pill bad">
        <span className="dot" aria-hidden /> Edge offline
      </Link>
    );
  }
  return (
    <Link href="/status" className={`status-pill ${health.ok ? "" : "bad"}`}>
      <span className="dot" aria-hidden />
      {health.ok ? "All systems normal" : `${health.problems.length} issue${health.problems.length > 1 ? "s" : ""}`}
    </Link>
  );
}

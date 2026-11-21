export const TZ = process.env.NEXT_PUBLIC_CAMERA_TIMEZONE || "America/New_York";

export function localTime(iso: string, opts: Intl.DateTimeFormatOptions = {}): string {
  return new Date(iso).toLocaleString("en-US", {
    timeZone: TZ,
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    ...opts,
  });
}

export function imprint(iso: string): string {
  // Trail-camera style: 2024-06-01 06:42:10
  const d = new Date(iso);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}:${get("second")}`;
}

export function pct(x: number | undefined | null): string {
  return x == null ? "" : `${Math.round(x * 100)}%`;
}

export function speciesLine(species: { species: string; count: number; uncertain: boolean }[]): string {
  if (!species.length) return "Animal";
  return species
    .map((s) => {
      const name = s.species === "pending" ? "Identifying…" : s.species;
      return `${s.count > 1 ? `${s.count} × ` : ""}${name}${s.uncertain ? " (uncertain)" : ""}`;
    })
    .join(", ");
}

export function ago(iso: string | null): string {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

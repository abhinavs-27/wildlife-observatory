// Pure helpers for the "last night" filmstrip and the hero copy. No dependencies.

/** Offset (minutes) of `tz` from UTC at instant `d`, e.g. -300 for New York in winter. */
function tzOffsetMinutes(d: Date, tz: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(d);
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
  return Math.round((asUtc - d.getTime()) / 60000);
}

/** Local wall-clock (y, m, d, h) in `tz` → UTC Date. */
function zoned(y: number, m: number, day: number, h: number, tz: string): Date {
  const guess = new Date(Date.UTC(y, m - 1, day, h));
  const off = tzOffsetMinutes(guess, tz);
  return new Date(guess.getTime() - off * 60000);
}

/** "Last night" = 18:00 yesterday → 07:00 today, local to the camera. */
export function lastNightWindow(now: Date, tz: string): { from: string; to: string } {
  const local = new Date(now.getTime() + tzOffsetMinutes(now, tz) * 60000);
  const y = local.getUTCFullYear();
  const m = local.getUTCMonth() + 1;
  const d = local.getUTCDate();
  // The window always ends at 07:00 today (local). Before 07:00 that's the night ending now.
  const endDay = new Date(Date.UTC(y, m - 1, d));
  const start = new Date(endDay.getTime() - 86400000);
  return {
    from: zoned(start.getUTCFullYear(), start.getUTCMonth() + 1, start.getUTCDate(), 18, tz).toISOString(),
    to: zoned(endDay.getUTCFullYear(), endDay.getUTCMonth() + 1, endDay.getUTCDate(), 7, tz).toISOString(),
  };
}

const SYNODIC = 29.530588853;
const NEW_MOON_2000 = Date.UTC(2000, 0, 6, 18, 14);
const PHASES = ["New moon", "Waxing crescent", "First quarter", "Waxing gibbous", "Full moon", "Waning gibbous", "Last quarter", "Waning crescent"];

export function moonPhase(d: Date): { name: string; illumination: number } {
  const age = ((((d.getTime() - NEW_MOON_2000) / 86400000) % SYNODIC) + SYNODIC) % SYNODIC;
  const illumination = (1 - Math.cos((2 * Math.PI * age) / SYNODIC)) / 2;
  const idx = Math.floor(((age / SYNODIC) * 8 + 0.5)) % 8;
  return { name: PHASES[idx], illumination };
}

type Sp = { species: string; count: number; uncertain: boolean; confidence?: number };

export function heroTitle(species: Sp[]): string {
  const s = species[0];
  if (!s) return "An animal";
  if (s.species === "pending") return "Identifying…";
  const name = s.species.charAt(0).toUpperCase() + s.species.slice(1);
  const lead = s.uncertain ? `Possibly a ${s.species}` : name;
  const more = species.length > 1 ? ` + ${species.length - 1} more` : "";
  return s.count > 1 && !s.uncertain ? `${s.count} × ${name}${more}` : `${lead}${more}`;
}

// Server-side data access. Runs inside the Next.js server, which reaches the edge directly.
const EDGE = process.env.EDGE_INTERNAL_URL || "http://localhost:8000";

export type SpeciesCount = {
  species: string;
  count: number;
  uncertain: boolean;
  confidence?: number;
  corrected?: boolean;
};

export type EncounterSummary = {
  id: number;
  device: string;
  start_at: string;
  end_at: string;
  species: SpeciesCount[];
  status: "pending" | "classified" | "rejected";
  best_frame_id: number | null;
  best_detection_id: number | null;
  best_bbox: [number, number, number, number] | null;
  media_count: number;
};

export type Classification = {
  id: number;
  common_name: string;
  score: number;
  is_uncertain: number;
  rollup_level: string;
  source: string | null;
  raw_topk: { label: string; score: number }[];
  taxon_class: string;
  taxon_order: string;
  taxon_family: string;
  taxon_genus: string;
  taxon_species: string;
  geofence: string;
  model: string;
  model_version: string;
};

export type Detection = {
  id: number;
  frame_id: number;
  category: "animal" | "person" | "vehicle";
  confidence: number;
  bbox: [number, number, number, number];
  verification_status: string;
  model: string;
  model_version: string;
  classification?: Classification;
  correction: { action: string; label: string | null; created_at: string } | null;
};

export type MediaDetail = {
  id: number;
  kind: "image" | "video";
  original_name: string;
  captured_at: string;
  captured_at_source: string;
  status: string;
  error: string | null;
  has_person: boolean;
  width: number | null;
  height: number | null;
  duration_s: number | null;
  frames: { id: number; idx: number; time_offset_s: number; width: number | null; height: number | null }[];
  detections: Detection[];
};

export type EncounterDetail = EncounterSummary & {
  media: MediaDetail[];
  tracks: { id: number; species: string; confidence: number; is_uncertain: number; n_detections: number }[];
  corrections: { id: number; action: string; label: string | null; note: string | null; created_at: string }[];
  alerts: { id: number; status: string; body: string; created_at: string; sent_at: string | null; error: string | null }[];
};

export type MediaItem = {
  id: number;
  kind: string;
  original_name: string;
  captured_at: string;
  status: string;
  error: string | null;
  has_person: number;
  frame_id: number | null;
  encounter_id: number | null;
  n_animals: number;
};

export type SpeciesSummary = {
  species: string;
  encounters: number;
  animals: number;
  any_uncertain: number;
  first_seen: string;
  last_seen: string;
  last_encounter_id: number;
  best_frame_id: number | null;
  best_bbox: [number, number, number, number] | null;
};

export type Health = {
  ok: boolean;
  problems: string[];
  disk_pct: number;
  disk_free_gb: number;
  queues: Record<string, number>;
  failed_jobs: number;
  workers: { id: string; kinds: string[]; last_seen: string; online: boolean; info: Record<string, unknown> }[];
  last_ingest: string | null;
  last_capture: string | null;
  last_backup: string | null;
  alert_backlog: number;
  alerts_failed: number;
  quarantined: number;
  models: { name: string; version: string; task: string }[];
  settings: { camera_timezone: string; country: string; admin1_region: string; ntfy_enabled: boolean };
};

export type Activity = {
  timezone: string;
  total: number;
  by_hour: { hour: number; count: number }[];
  by_day: { day: string; count: number }[];
};

export class EdgeUnavailable extends Error {}

export async function edge<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${EDGE}${path}`, { cache: "no-store" });
  } catch {
    throw new EdgeUnavailable(`Can't reach the edge service at ${EDGE}`);
  }
  if (res.status === 404) throw new Error("not-found");
  if (!res.ok) throw new Error(`edge ${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export function qs(params: Record<string, string | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : "";
}

export type Insight = {
  id: string;
  kind: string;
  species: string | null;
  text: string;
  detail: string;
  n: number;
  encounter_ids: number[];
  strength: number;
};

export type Milestone = {
  id: number;
  kind: string;
  species: string | null;
  encounter_id: number | null;
  text: string;
  night: string;
  status: string;
  created_at: string;
};

export type ReplayFrame = {
  frame_id: number;
  media_id: number;
  t: number;
  has_person: boolean;
  boxes: { bbox: [number, number, number, number]; category: string; confidence: number }[];
};

export type ActivityPoint = { encounter_id: number; minute_of_day: number; date: string; species: string; uncertain: boolean };

export type ActivityFull = Activity & {
  points: ActivityPoint[];
  night: { date: string; sunset_min: number; sunrise_min: number };
};

export type SpeciesInfo = {
  common_name: string;
  status: string;
  wiki_title?: string | null;
  extract?: string | null;
  page_url?: string | null;
  has_image: boolean;
  scientific_name: string | null;
  facts: { activity: string; size: string; diet: string; nj_status: string } | null;
};

export type SpeciesDetail = SpeciesSummary & {
  info: SpeciesInfo;
  usual_time: string | null;
  calendar: { date: string; count: number }[];
  calendar_total_in_range: number;
  gallery: EncounterSummary[];
  insights: Insight[];
  milestones: Milestone[];
  rolled_up: boolean;
};

export type Digest = {
  week: string;
  start: string;
  end: string;
  visits: number;
  species: number;
  species_counts: [string, number][];
  new_species: string[];
  best_encounter_id: number | null;
  best_frame_id: number | null;
  best_species: string | null;
  headline: string;
  highlights: string[];
  sent_at?: string | null;
  in_progress?: boolean;
};

export type DigestSummary = { week: string; sent_at: string; headline: string; visits: number; species: number; best_frame_id: number | null; start: string; end: string };

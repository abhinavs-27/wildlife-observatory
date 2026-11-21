import Link from "next/link";
import type { ActivityPoint } from "@/lib/api";

// Validated with dataviz validate_palette.js on surface #0c1416 (dark): all checks pass.
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"];
const OTHER = "#7d8a85";

type Props = {
  points: ActivityPoint[];
  night: { sunset_min: number; sunrise_min: number };
  size?: number;
  /** Single-species mode: one hue, no legend. */
  single?: boolean;
  title?: string;
};

function polar(cx: number, cy: number, r: number, minute: number) {
  // midnight at the bottom, noon at the top, clockwise
  const a = (minute / 1440) * 2 * Math.PI + Math.PI / 2;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

function arc(cx: number, cy: number, r: number, from: number, to: number) {
  const span = (to - from + 1440) % 1440;
  const [x1, y1] = polar(cx, cy, r, from);
  const [x2, y2] = polar(cx, cy, r, to);
  return `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${span > 720 ? 1 : 0} 1 ${x2} ${y2} Z`;
}

const label = (m: number) => {
  const h = Math.floor(m / 60) % 24;
  const mm = String(m % 60).padStart(2, "0");
  return `${h % 12 === 0 ? 12 : h % 12}:${mm} ${h < 12 ? "am" : "pm"}`;
};

/** 24-hour radial chart: each visit is a dot at its local time; night is shaded. */
export default function ActivityClock({ points, night, size = 340, single = false, title = "When visits happen" }: Props) {
  const cx = size / 2;
  const cy = size / 2;
  const R = size / 2 - 34;
  const counts = new Map<string, number>();
  points.forEach((p) => counts.set(p.species, (counts.get(p.species) ?? 0) + 1));
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, single ? 1 : SERIES.length).map(([s]) => s);
  const color = (s: string) => (single ? SERIES[0] : top.includes(s) ? SERIES[top.indexOf(s)] : OTHER);

  // spread dots that land in the same 20-minute bucket outward
  const bucket = new Map<number, number>();
  const dots = points.map((p) => {
    const b = Math.floor(p.minute_of_day / 20);
    const k = bucket.get(b) ?? 0;
    bucket.set(b, k + 1);
    const r = R - 14 - (k % 8) * 11;
    const [x, y] = polar(cx, cy, r, p.minute_of_day);
    return { ...p, x, y };
  });
  const hours = [0, 3, 6, 9, 12, 15, 18, 21];
  const legend = [...top.map((s) => ({ s, c: color(s), n: counts.get(s) ?? 0 }))];
  const otherN = points.length - legend.reduce((a, l) => a + l.n, 0);

  return (
    <figure className="clock" style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${size} ${size}`} width="100%" style={{ maxWidth: size }} role="img" aria-label={`${title}: ${points.length} visits plotted on a 24-hour clock`}>
        <circle cx={cx} cy={cy} r={R} className="clock-face" />
        <path d={arc(cx, cy, R, night.sunset_min, night.sunrise_min)} className="clock-night" />
        {hours.map((h) => {
          const [x1, y1] = polar(cx, cy, R, h * 60);
          const [x2, y2] = polar(cx, cy, R + 6, h * 60);
          const [tx, ty] = polar(cx, cy, R + 20, h * 60);
          return (
            <g key={h}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} className="clock-tick" />
              <text x={tx} y={ty} className="clock-label" textAnchor="middle" dominantBaseline="middle">
                {h === 0 ? "12a" : h === 12 ? "12p" : h < 12 ? `${h}a` : `${h - 12}p`}
              </text>
            </g>
          );
        })}
        <text x={cx} y={cy - 8} className="clock-center" textAnchor="middle">{points.length}</text>
        <text x={cx} y={cy + 12} className="clock-sub" textAnchor="middle">visits</text>
        {dots.map((d) => (
          <Link key={d.encounter_id} href={`/encounters/${d.encounter_id}`}>
            <circle cx={d.x} cy={d.y} r={5.5} fill={color(d.species)} className={`clock-dot ${d.uncertain ? "unsure" : ""}`}>
              <title>{`${d.species}${d.uncertain ? " (uncertain)" : ""}, ${label(d.minute_of_day)}, ${d.date}`}</title>
            </circle>
          </Link>
        ))}
      </svg>
      {!single ? (
        <figcaption>
          <ul className="legend">
            {legend.map((l) => (
              <li key={l.s}>
                <i style={{ background: l.c }} aria-hidden /> {l.s} <span className="muted">{l.n}</span>
              </li>
            ))}
            {otherN > 0 ? (
              <li>
                <i style={{ background: OTHER }} aria-hidden /> other <span className="muted">{otherN}</span>
              </li>
            ) : null}
            <li>
              <i className="night-key" aria-hidden /> night (sunset {label(night.sunset_min)} to sunrise {label(night.sunrise_min)})
            </li>
          </ul>
        </figcaption>
      ) : null}
    </figure>
  );
}

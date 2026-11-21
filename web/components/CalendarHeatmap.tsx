// Single-hue sequential ramp (sage), light → strong on the dark surface. Zero is the empty cell.
const RAMP = ["#1a2a2e", "#2f5135", "#4d7b43", "#76a85f", "#a8d68a"];

function level(n: number, max: number) {
  if (n <= 0) return 0;
  if (max <= 1) return 4;
  return Math.min(4, 1 + Math.floor(((n - 1) / max) * 4));
}

/** GitHub-style calendar of visits by day (columns are weeks). */
export default function CalendarHeatmap({ days, label = "Visits by day" }: { days: { date: string; count: number }[]; label?: string }) {
  if (!days.length) return null;
  const cell = 12;
  const gap = 3;
  const first = new Date(days[0].date + "T12:00:00Z");
  const offset = first.getUTCDay(); // 0 = Sunday
  const max = Math.max(...days.map((d) => d.count));
  const cols = Math.ceil((days.length + offset) / 7);
  const w = cols * (cell + gap);
  const h = 7 * (cell + gap);
  const months: { x: number; text: string }[] = [];
  days.forEach((d, i) => {
    if (d.date.endsWith("-01") || i === 0) {
      const col = Math.floor((i + offset) / 7);
      months.push({ x: col * (cell + gap), text: new Date(d.date + "T12:00:00Z").toLocaleString("en-US", { month: "short", timeZone: "UTC" }) });
    }
  });
  const total = days.reduce((a, d) => a + d.count, 0);
  return (
    <figure className="heatmap" style={{ margin: 0 }}>
      <div className="heatmap-scroll">
        <svg viewBox={`0 -16 ${w} ${h + 16}`} width={w} height={h + 16} role="img" aria-label={`${label}: ${total} visits`}>
          {months.map((m) => (
            <text key={m.x + m.text} x={m.x} y={-5} className="clock-label">
              {m.text}
            </text>
          ))}
          {days.map((d, i) => {
            const col = Math.floor((i + offset) / 7);
            const row = (i + offset) % 7;
            return (
              <rect key={d.date} x={col * (cell + gap)} y={row * (cell + gap)} width={cell} height={cell} rx={3} fill={RAMP[level(d.count, max)]}>
                <title>{`${d.date}: ${d.count} visit${d.count === 1 ? "" : "s"}`}</title>
              </rect>
            );
          })}
        </svg>
      </div>
      <figcaption className="heatmap-legend">
        <span className="muted">Fewer</span>
        {RAMP.map((c) => (
          <i key={c} style={{ background: c }} aria-hidden />
        ))}
        <span className="muted">More</span>
      </figcaption>
      <details className="table-view">
        <summary>Show as table</summary>
        <table>
          <tbody>
            {days
              .filter((d) => d.count > 0)
              .map((d) => (
                <tr key={d.date}>
                  <th scope="row">{d.date}</th>
                  <td>{d.count}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

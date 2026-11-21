type Datum = { key: string; label: string; count: number };

/** Single-series bar chart: one hue, 2px gaps, rounded data-ends, hover tooltips, table view. */
export default function BarChart({ data, title, tickEvery = 1, unit = "sightings" }: { data: Datum[]; title: string; tickEvery?: number; unit?: string }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  return (
    <figure className="chart" style={{ margin: 0 }}>
      <figcaption>
        <h3 style={{ marginBottom: 10 }}>{title}</h3>
      </figcaption>
      <div className="bars" role="img" aria-label={`${title}: bar chart`}>
        {data.map((d) => (
          <div className="bar-slot" key={d.key} tabIndex={0} aria-label={`${d.label}: ${d.count} ${unit}`}>
            <div className="bar" style={{ height: `${(d.count / max) * 100}%` }} />
            <span className="tip">
              {d.label}: {d.count} {unit}
            </span>
          </div>
        ))}
      </div>
      <div className="axis" aria-hidden>
        {data.map((d, i) => (
          <span key={d.key}>{i % tickEvery === 0 ? d.label : ""}</span>
        ))}
      </div>
      <details className="table-view">
        <summary>Show as table</summary>
        <table>
          <tbody>
            {data.map((d) => (
              <tr key={d.key}>
                <th scope="row">{d.label}</th>
                <td>{d.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

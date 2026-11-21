import Offline from "@/components/Offline";
import { edge, EdgeUnavailable, type Health } from "@/lib/api";
import { ago } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function StatusPage() {
  let h: Health;
  try {
    h = await edge<Health>("/api/health/details");
  } catch (e) {
    return <Offline message={e instanceof EdgeUnavailable ? e.message : undefined} />;
  }
  return (
    <>
      <h1 style={{ marginBottom: 16 }}>System</h1>
      {h.problems.length ? (
        <ul className="problems">
          {h.problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      ) : (
        <div className="ok-banner">Everything is running normally.</div>
      )}
      <div className="detail">
        <div>
          <div className="panel">
            <h3>Pi and storage</h3>
            <dl className="kv" style={{ marginTop: 10 }}>
              <dt>Disk used</dt>
              <dd>
                {h.disk_pct}% ({h.disk_free_gb} GB free)
              </dd>
              <dt>Last photo received</dt>
              <dd>{ago(h.last_ingest)}</dd>
              <dt>Last backup</dt>
              <dd>{ago(h.last_backup)}</dd>
              <dt>Alerts waiting to send</dt>
              <dd>{h.alert_backlog}</dd>
              <dt>Phone alerts</dt>
              <dd>{h.settings.ntfy_enabled ? "On (ntfy)" : "Off: set NTFY_TOPIC to turn on"}</dd>
              <dt>Quarantined files</dt>
              <dd>{h.quarantined}</dd>
              <dt>Location filter</dt>
              <dd>
                {h.settings.country} / {h.settings.admin1_region}
              </dd>
            </dl>
          </div>
          <div className="panel">
            <h3>Job queue</h3>
            <table className="plain">
              <tbody>
                {Object.entries(h.queues).map(([k, v]) => (
                  <tr key={k}>
                    <th scope="row">{k.replace(":", ": ")}</th>
                    <td>{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <aside>
          <div className="panel">
            <h3>Workers</h3>
            {h.workers.length === 0 ? <p className="muted">No worker has connected yet.</p> : null}
            <table className="plain">
              <tbody>
                {h.workers.map((w) => (
                  <tr key={w.id}>
                    <td>
                      <b>{w.id}</b>
                      <div className="tax">{w.kinds.join(", ")}</div>
                    </td>
                    <td>
                      <span className={`badge ${w.online ? "ok" : "bad"}`}>{w.online ? "Online" : "Offline"}</span>
                      <div className="tax">{ago(w.last_seen)}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="panel">
            <h3>Models</h3>
            <table className="plain">
              <tbody>
                {h.models.map((m) => (
                  <tr key={`${m.name}${m.version}${m.task}`}>
                    <td>{m.name}</td>
                    <td>{m.version}</td>
                    <td className="muted">{m.task}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </aside>
      </div>
    </>
  );
}

"use client";

import Link from "next/link";
import { useState } from "react";

type AskResult = { text: string; intent: string; sources: number[] };

const EXAMPLES = [
  "What animals have visited?",
  "Show all fox sightings",
  "When are deer most active?",
  "What was the rarest species detected?",
  "When was a raccoon last seen?",
  "How many bobcat visits this month?",
];

export default function AskPage() {
  const [q, setQ] = useState("");
  const [result, setResult] = useState<AskResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(question: string) {
    setQ(question);
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question }),
      });
      if (!res.ok) throw new Error(`The edge returned ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1 style={{ marginBottom: 6 }}>Ask the observatory</h1>
      <p className="muted" style={{ marginTop: 0, maxWidth: "62ch" }}>
        Answers come straight from the sightings database and link to the photos behind them. If a question isn&apos;t
        supported yet, it says so instead of guessing.
      </p>
      <form
        className="ask-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (q.trim()) void ask(q.trim());
        }}
      >
        <input type="text" aria-label="Question" value={q} onChange={(e) => setQ(e.target.value)} placeholder="When are deer most active?" />
        <button type="submit" disabled={busy}>
          Ask
        </button>
      </form>
      <div className="suggest">
        {EXAMPLES.map((ex) => (
          <button key={ex} type="button" onClick={() => void ask(ex)}>
            {ex}
          </button>
        ))}
      </div>
      {error ? <p role="alert">{error}</p> : null}
      {result ? (
        <section aria-live="polite">
          <p className="answer">{result.text}</p>
          {result.sources.length ? (
            <>
              <h3>Sightings behind this answer</h3>
              <ul className="species-list" style={{ marginTop: 8 }}>
                {result.sources.slice(0, 40).map((id) => (
                  <li key={id}>
                    <Link className="chip" href={`/encounters/${id}`}>
                      Sighting {id}
                    </Link>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </section>
      ) : null}
    </>
  );
}

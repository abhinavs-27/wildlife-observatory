"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function CorrectionForm({ encounterId, suggestions }: { encounterId: number; suggestions: string[] }) {
  const router = useRouter();
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function send(action: "relabel" | "confirm" | "reject") {
    if (action === "relabel" && !label.trim()) {
      setMessage("Type the species name first.");
      return;
    }
    setBusy(true);
    setMessage(null);
    const res = await fetch("/api/corrections", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ target_type: "encounter", target_id: encounterId, action, label: label || null }),
    });
    setBusy(false);
    if (!res.ok) {
      setMessage(`Couldn't save the correction (${res.status}).`);
      return;
    }
    setMessage(action === "relabel" ? `Relabelled as ${label}.` : action === "confirm" ? "Confirmed." : "Marked as not an animal.");
    setLabel("");
    router.refresh();
  }

  return (
    <form
      className="correct"
      onSubmit={(e) => {
        e.preventDefault();
        void send("relabel");
      }}
    >
      <label htmlFor="species-input">Species</label>
      <div className="row">
        <input
          id="species-input"
          type="text"
          list="species-suggestions"
          placeholder="e.g. eastern gray squirrel"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
        <datalist id="species-suggestions">
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
        <button type="submit" disabled={busy}>
          Relabel
        </button>
      </div>
      <div className="row">
        <button type="button" className="secondary" disabled={busy} onClick={() => void send("confirm")}>
          Confirm prediction
        </button>
        <button type="button" className="danger" disabled={busy} onClick={() => void send("reject")}>
          Not an animal
        </button>
      </div>
      {message ? <p role="status">{message}</p> : null}
    </form>
  );
}

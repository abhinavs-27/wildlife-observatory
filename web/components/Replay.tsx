"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReplayFrame } from "@/lib/api";
import LitImage from "./LitImage";

type Props = {
  frames: ReplayFrame[];
  alt: string;
  /** Show a scrubber + frame time (sighting page). */
  controls?: boolean;
  /** Hide frames that contain a person (home page, digest). */
  hidePeople?: boolean;
  className?: string;
  fallbackFrameId?: number | null;
  fallbackBox?: [number, number, number, number] | null;
};

const STEP_MS = 900;

/** Plays a visit's burst/clip frames as a soft loop. Static under prefers-reduced-motion. */
export default function Replay({ frames, alt, controls = false, hidePeople = false, className = "", fallbackFrameId, fallbackBox }: Props) {
  const list = useMemo(() => {
    const f = hidePeople ? frames.filter((x) => !x.has_person) : frames;
    if (f.length) return f.slice(0, controls ? 60 : 8);
    return fallbackFrameId != null
      ? [{ frame_id: fallbackFrameId, media_id: 0, t: 0, has_person: false, boxes: fallbackBox ? [{ bbox: fallbackBox, category: "animal", confidence: 1 }] : [] }]
      : [];
  }, [frames, hidePeople, controls, fallbackFrameId, fallbackBox]);
  const [i, setI] = useState(0);
  const [paused, setPaused] = useState(false);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  useEffect(() => {
    if (list.length < 2 || paused || reduced) return;
    const t = setInterval(() => setI((x) => (x + 1) % list.length), STEP_MS);
    return () => clearInterval(t);
  }, [list.length, paused, reduced]);

  if (!list.length) return <div className={`replay ${className}`}><div className="withheld">No photo to show</div></div>;
  const current = list[Math.min(i, list.length - 1)];
  const t0 = list[0].t;

  return (
    <div
      className={`replay ${className} ${list.length === 1 ? "single" : ""}`}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onClick={() => setPaused((p) => !p)}
    >
      {list.map((f, idx) => (
        <div key={f.frame_id} className={`replay-frame ${idx === i ? "on" : ""}`} aria-hidden={idx !== i}>
          <LitImage src={`/frames/${f.frame_id}/file`} alt={idx === i ? alt : ""} loading={idx < 2 ? "eager" : "lazy"} />
          {f.boxes
            .filter((b) => b.category === "animal")
            .map((b, k) => (
              <span
                key={k}
                className="glowbox"
                style={{ left: `${b.bbox[0] * 100}%`, top: `${b.bbox[1] * 100}%`, width: `${b.bbox[2] * 100}%`, height: `${b.bbox[3] * 100}%` }}
              />
            ))}
        </div>
      ))}
      {list.length > 1 && !controls ? (
        <span className="replay-dots" aria-hidden>
          {list.map((f, idx) => (
            <i key={f.frame_id} className={idx === i ? "on" : ""} />
          ))}
        </span>
      ) : null}
      {controls && list.length > 1 ? (
        <div className="scrubber" onClick={(e) => e.stopPropagation()}>
          <button type="button" className="secondary" onClick={() => setPaused((p) => !p)} aria-label={paused ? "Play" : "Pause"}>
            {paused || reduced ? "Play" : "Pause"}
          </button>
          <input
            type="range"
            min={0}
            max={list.length - 1}
            value={i}
            aria-label="Frame"
            onChange={(e) => {
              setPaused(true);
              setI(Number(e.target.value));
            }}
          />
          <span className="muted">
            {i + 1}/{list.length} · +{Math.max(0, current.t - t0).toFixed(1)} s
          </span>
        </div>
      ) : null}
    </div>
  );
}

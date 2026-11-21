import { imprint, pct } from "@/lib/format";
import LitImage from "./LitImage";

export type Box = {
  bbox: [number, number, number, number];
  label?: string;
  kind?: "animal" | "person" | "vehicle";
};

type Props = {
  frameId: number | null;
  alt: string;
  boxes?: Box[];
  capturedAt?: string;
  species?: string;
  confidence?: number;
  hiddenReason?: string;
};

/** Camera-trap photo with detection boxes and a trail-cam style imprint strip. */
export default function Photo({ frameId, alt, boxes = [], capturedAt, species, confidence, hiddenReason }: Props) {
  if (hiddenReason || frameId == null) {
    return <div className="photo hidden-person">{hiddenReason ?? "No image"}</div>;
  }
  return (
    <div className="photo">
      <LitImage src={`/frames/${frameId}/file`} alt={alt} />
      {boxes.map((b, i) => (
        <div
          key={i}
          className={`box ${b.kind === "person" ? "person" : ""}`}
          style={{
            left: `${b.bbox[0] * 100}%`,
            top: `${b.bbox[1] * 100}%`,
            width: `${b.bbox[2] * 100}%`,
            height: `${b.bbox[3] * 100}%`,
          }}
        >
          {b.label ? <span className="tag">{b.label}</span> : null}
        </div>
      ))}
      {capturedAt ? (
        <div className="imprint">
          <span>{imprint(capturedAt)}</span>
          {species ? (
            <span className="sp">
              {species}
              {confidence != null ? ` ${pct(confidence)}` : ""}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

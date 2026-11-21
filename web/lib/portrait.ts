// Crop a photo to the animal using its normalized detection box (CSS background tricks).

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function portraitStyle(bbox: [number, number, number, number]): {
  backgroundSize: string;
  backgroundPosition: string;
} {
  const [x, y, w, h] = bbox;
  const z = clamp(0.75 / Math.max(w, h, 0.01), 1.2, 6);
  const v = 1 / z;
  const pos = (c: number) => (v >= 1 ? 0 : clamp((c - v / 2) / (1 - v), 0, 1));
  return {
    backgroundSize: `${Math.round(z * 100)}%`,
    backgroundPosition: `${Math.round(pos(x + w / 2) * 100)}% ${Math.round(pos(y + h / 2) * 100)}%`,
  };
}

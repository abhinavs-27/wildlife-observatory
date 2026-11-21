"use client";

import { useEffect, useState } from "react";

const THRESHOLD = 0.35;
const cache = new Map<string, boolean>();

/** True when the image is dark (night/IR), measured on a 32×32 canvas. Display-only. */
export function useNightLift(src: string | null | undefined): boolean {
  const [dark, setDark] = useState(() => (src ? cache.get(src) ?? false : false));
  useEffect(() => {
    if (!src) return;
    if (cache.has(src)) {
      setDark(cache.get(src)!);
      return;
    }
    const img = new Image();
    img.decoding = "async";
    img.onload = () => {
      try {
        const c = document.createElement("canvas");
        c.width = c.height = 32;
        const ctx = c.getContext("2d", { willReadFrequently: true });
        if (!ctx) return;
        ctx.drawImage(img, 0, 0, 32, 32);
        const d = ctx.getImageData(0, 0, 32, 32).data;
        let sum = 0;
        for (let i = 0; i < d.length; i += 4) sum += 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
        const isDark = sum / (d.length / 4) / 255 < THRESHOLD;
        cache.set(src, isDark);
        setDark(isDark);
      } catch {
        /* ignore: lift is cosmetic */
      }
    };
    img.src = src;
  }, [src]);
  return dark;
}

"use client";

import { useState } from "react";
import { useNightLift } from "./useNightLift";

type Props = { src: string; alt: string; className?: string; loading?: "lazy" | "eager" };

/** <img> that gently brightens dark night/IR photos for display. Originals are untouched.
 *  If the file was cleaned up to save space, shows a quiet note instead of a broken image. */
export default function LitImage({ src, alt, className = "", loading = "lazy" }: Props) {
  const dark = useNightLift(src);
  const [missing, setMissing] = useState(false);
  if (missing) return <div className="withheld">Photo removed to save space</div>;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={alt}
      loading={loading}
      onError={() => setMissing(true)}
      className={`${className} ${dark ? "lift" : ""}`.trim()}
    />
  );
}

export function Portrait({ src, style, className = "" }: { src: string | null; style?: React.CSSProperties; className?: string }) {
  const dark = useNightLift(src);
  return (
    <i
      aria-hidden
      className={`${className} ${dark ? "lift" : ""}`.trim()}
      style={src ? { backgroundImage: `url(${src})`, ...style } : undefined}
    />
  );
}

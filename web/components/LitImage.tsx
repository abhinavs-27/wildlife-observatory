"use client";

import { useNightLift } from "./useNightLift";

type Props = { src: string; alt: string; className?: string; loading?: "lazy" | "eager" };

/** <img> that gently brightens dark night/IR photos for display. Originals are untouched. */
export default function LitImage({ src, alt, className = "", loading = "lazy" }: Props) {
  const dark = useNightLift(src);
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt={alt} loading={loading} className={`${className} ${dark ? "lift" : ""}`.trim()} />;
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

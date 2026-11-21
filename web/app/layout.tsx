import type { Metadata, Viewport } from "next";
import { Atkinson_Hyperlegible, Barlow_Condensed } from "next/font/google";
import Link from "next/link";
import StatusPill from "@/components/StatusPill";
import "./globals.css";

const barlow = Barlow_Condensed({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--font-barlow" });
const atkinson = Atkinson_Hyperlegible({ subsets: ["latin"], weight: ["400", "700"], variable: "--font-atkinson" });

export const metadata: Metadata = {
  title: "Wildlife Observatory",
  description: "Backyard camera-trap sightings, identified with MegaDetector and SpeciesNet.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${barlow.variable} ${atkinson.variable}`}>
      <body>
        <div className="shell">
          <header className="topbar">
            <Link href="/" className="brand">
              Wildlife Observatory<small>backyard, NJ</small>
            </Link>
            <nav className="nav" aria-label="Main">
              <Link href="/">Sightings</Link>
              <Link href="/gallery">Photos</Link>
              <Link href="/activity">Activity</Link>
              <Link href="/ask">Ask</Link>
              <Link href="/status">System</Link>
            </nav>
            <StatusPill />
          </header>
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}

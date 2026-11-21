import type { NextConfig } from "next";

// The browser only ever talks to this origin; /api, /media and /frames are proxied to the
// edge service so the dashboard works the same on localhost, the LAN and Tailscale.
const EDGE = process.env.EDGE_INTERNAL_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${EDGE}/api/:path*` },
      { source: "/media/:path*", destination: `${EDGE}/media/:path*` },
      { source: "/frames/:path*", destination: `${EDGE}/frames/:path*` },
    ];
  },
};

export default nextConfig;

import type { NextConfig } from "next";

const API = process.env.TAXPROOF_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // The browser only talks to the Next origin; /api is proxied to FastAPI (no CORS, one link to share).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;

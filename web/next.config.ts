import type { NextConfig } from "next";

const backend = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";
const nextConfig: NextConfig = {
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};
export default nextConfig;

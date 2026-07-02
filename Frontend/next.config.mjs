/** @type {import('next').NextConfig} */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

const nextConfig = {
  async rewrites() {
    return [
      { source: "/api/backend/:path*", destination: `${API_BASE}/:path*` },
    ];
  },
};

export default nextConfig;

import type { NextConfig } from "next";

const backendInternalUrl = (process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  allowedDevOrigins: ["*.trycloudflare.com"],
  async rewrites() {
    return [
      {
        source: "/backend-api/:path*",
        destination: `${backendInternalUrl}/:path*`,
      },
      {
        source: "/api/webhooks/:path*",
        destination: `${backendInternalUrl}/api/webhooks/:path*`,
      },
      {
        source: "/api/public/:path*",
        destination: `${backendInternalUrl}/api/public/:path*`,
      },
    ];
  },
};

export default nextConfig;

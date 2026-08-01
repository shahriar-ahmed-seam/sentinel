import type { NextConfig } from "next";

const apiBase = process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "standalone",
  experimental: { optimizePackageImports: ["recharts"] },
  async rewrites() {
    // When no public API URL is configured the browser talks to /api and /v1 on
    // the same origin and Next proxies through to the control plane. That keeps
    // the deployment CORS-free and hides the backend host.
    if (!apiBase) return [];
    return [
      { source: "/api/:path*", destination: `${apiBase}/api/:path*` },
      { source: "/v1/:path*", destination: `${apiBase}/v1/:path*` },
      { source: "/metrics", destination: `${apiBase}/metrics` },
      { source: "/health", destination: `${apiBase}/health` },
    ];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
        ],
      },
    ];
  },
};

export default nextConfig;

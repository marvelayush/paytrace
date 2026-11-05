import type { NextConfig } from "next";

/**
 * Two ways to reach the API in production (see deployment.md):
 * - proxy (deployment default): set BACKEND_URL and NEXT_PUBLIC_API_URL=/api; this app forwards /api/* to
 *   the backend, so the session cookie is first-party and sign-in works in Safari and on phones.
 *   Uploads pass through the proxy and are limited to about 4.5 MB.
 * - direct (local development): NEXT_PUBLIC_API_URL is the backend's URL; uploads go straight to it.
 */
const backendUrl = process.env.BACKEND_URL?.replace(/\/$/, "");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    return backendUrl ? [{ source: "/api/:path*", destination: `${backendUrl}/:path*` }] : [];
  },
};

export default nextConfig;

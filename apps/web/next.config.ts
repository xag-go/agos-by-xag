import path from "node:path";
import type { NextConfig } from "next";

// Baseline security headers for every response. A strict nonce-based CSP
// is added with authentication (step: auth), where the request proxy lives.
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
  {
    key: "Permissions-Policy",
    // The microphone is for voice notes in chats, on this site only.
    value: "camera=(), microphone=(self), geolocation=(), payment=(), usb=()",
  },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // No page uses next/image: never run the image optimizer on this server.
  images: { unoptimized: true },
  // Self-contained server for the Docker image (only traced files are copied).
  output: "standalone",
  // Monorepo: trace from the repository root so workspace packages are included.
  outputFileTracingRoot: path.join(import.meta.dirname, "../.."),
  // Workspace packages ship TypeScript source.
  transpilePackages: [
    "@agos/core",
    "@agos/db",
    "@agos/security",
    "@agos/workspace",
  ],
  experimental: {
    // Chat messages carry screenshots, voice notes and files (30 MB, base64).
    serverActions: { bodySizeLimit: "45mb" },
    proxyClientMaxBodySize: "45mb",
  },
  headers() {
    return Promise.resolve([{ source: "/:path*", headers: securityHeaders }]);
  },
};

export default nextConfig;

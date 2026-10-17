import type { NextConfig } from "next";

/**
 * VeriPay deploys to Azure Static Web Apps (Free plan) as a PURE STATIC
 * EXPORT: `next build` emits a fully static site into apps/web/out.
 *
 * Consequences, enforced by convention across this app:
 * - no server actions, no API routes, no server-side data fetching;
 * - no next/image optimization (images.unoptimized);
 * - everything that talks to the VeriPay API runs client-side (src/lib/api.ts)
 *   and must degrade gracefully when the API is unreachable.
 */
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;

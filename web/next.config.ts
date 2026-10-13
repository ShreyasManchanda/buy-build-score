import type { NextConfig } from "next";

const API_DEV_ORIGIN = process.env.API_DEV_ORIGIN ?? "http://localhost:8000";
// Opt-in for testing a production build locally (`API_PROXY_ORIGIN=http://localhost:8000 next build`).
// Never set on Vercel, where Services routes /api/* before Next.js sees it.
const API_PROXY_ORIGIN = process.env.API_PROXY_ORIGIN;

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // In production Vercel Services routes /api/* to the FastAPI service before Next.js sees it.
  // In dev, proxy /api/* to the local uvicorn.
  async rewrites() {
    const origin = process.env.NODE_ENV === "development" ? API_DEV_ORIGIN : API_PROXY_ORIGIN;
    if (!origin) return [];
    return [{ source: "/api/:path*", destination: `${origin}/api/:path*` }];
  },
};

export default nextConfig;

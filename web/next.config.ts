import type { NextConfig } from "next";

const API_DEV_ORIGIN = process.env.API_DEV_ORIGIN ?? "http://localhost:8000";

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
    if (process.env.NODE_ENV !== "development") return [];
    return [{ source: "/api/:path*", destination: `${API_DEV_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;

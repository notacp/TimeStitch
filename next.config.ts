import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // Only proxy to local backend in development
    // In production (Vercel), the vercel.json rewrites handle routing to serverless functions
    if (process.env.NODE_ENV === "development") {
      return [
        {
          source: "/api/:path*",
          destination: "http://127.0.0.1:8000/api/:path*",
        },
      ];
    }
    return [];
  },
  reactCompiler: true,
};

export default nextConfig;

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The documented local URL uses 127.0.0.1 so the browser and API share a
  // cookie site. Next.js 16 otherwise blocks its dev assets when the dev
  // server was started on localhost.
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;

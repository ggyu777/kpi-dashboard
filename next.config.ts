import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  serverExternalPackages: ["@google-analytics/data", "google-auth-library"],
};

export default nextConfig;

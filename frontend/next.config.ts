import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: 'standalone', // Required for Docker deployment

  // Increase body size limit for file uploads (default is 10MB)
  experimental: {
    serverActions: {
      bodySizeLimit: '100mb',
    },
  },

  // Skip type checking and ESLint during production builds
  // Type checking should be done in CI/CD or locally
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },

  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "cdn.simpleicons.org",
      },
    ],
  },
  async rewrites() {
    // Use private Railway URL for server-side rewrites (more secure & faster)
    // Falls back to public URL, then localhost
    const backendUrl = process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;

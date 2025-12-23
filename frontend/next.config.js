/** @type {import('next').NextConfig} */
const nextConfig = {
  // Enable standalone output for Docker deployment
  output: 'standalone',

  // Disable static generation for dynamic routes
  // (Recommended for applications with authentication)
  reactStrictMode: true,

  // Environment variables that should be available to the browser
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  },

  // Optimize images
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: '**',
      },
    ],
  },

  // Webpack configuration
  webpack: (config) => {
    // Add any custom webpack config here if needed
    return config;
  },
}

module.exports = nextConfig

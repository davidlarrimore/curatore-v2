/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  typescript: {
    // Type checking is handled by the build process
    ignoreBuildErrors: false,
  },
  eslint: {
    ignoreDuringBuilds: false,
  },
  async redirects() {
    return [
      {
        source: '/health',
        destination: '/connections',
        permanent: true,
      },
    ]
  },
}

export default nextConfig
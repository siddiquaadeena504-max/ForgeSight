/** @type {import('next').NextConfig} */
const backend = process.env.BACKEND_HOSTPORT ? `http://${process.env.BACKEND_HOSTPORT}` : process.env.BACKEND_URL || "http://127.0.0.1:8000";
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  experimental: { proxyTimeout: 300000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};
export default nextConfig;

import type { NextConfig } from 'next';

// The browser only ever talks to Next; /api/* is proxied to the FastAPI
// backend server-side, so the backend URL never has to be exposed or CORS-ed.
const BACKEND = process.env.BACKEND_URL || 'http://localhost:8000';

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${BACKEND}/api/:path*` }];
  },
};

export default nextConfig;

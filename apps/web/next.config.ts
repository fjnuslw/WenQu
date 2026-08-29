import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 开发期允许 127.0.0.1/localhost 访问 dev 资源（Next 16 默认拦截跨源 dev 资源，会导致 hydration 静默失败）
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async rewrites() {
    // /api 同源代理（JSON，无流式）。/agents 走专用 Route Handler（SSE 流式需要独立上游连接，
    // 见 apps/web/src/app/agents/[...path]/route.ts 的说明）。
    const api = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:23480";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default nextConfig;

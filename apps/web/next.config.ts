import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 开发期允许 127.0.0.1/localhost 访问 dev 资源（Next 16 默认拦截跨源 dev 资源，会导致 hydration 静默失败）
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // /api 与 /agents 都走专用 Route Handler（node:http + keepAlive:false）：
  // rewrites 的 undici fetch 会把长 POST 在 ~30s 处 ECONNRESET（备课/采集实测），
  // node:http 代理在 SSE 40s+ 场景已验证稳定。见 app/api/[...path]/route.ts 与
  // app/agents/[...path]/route.ts。
};

export default nextConfig;

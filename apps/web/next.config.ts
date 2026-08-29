import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 开发期允许 127.0.0.1/localhost 访问 dev 资源（Next 16 默认拦截跨源 dev 资源，会导致 hydration 静默失败）
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async rewrites() {
    // 同源代理：浏览器只与本站(23482)通信，由 Next 服务端转发到后端。
    // 根治三类问题：CORS 预检、系统代理(Clash)对回环地址的劫持、端口漂移导致的地址失配。
    // 目标地址从 .env.local 读取（start.ps1 每次启动按实际解析端口写入）。
    const api = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:23480";
    const agents = process.env.AGENTS_PROXY_TARGET ?? "http://127.0.0.1:23481";
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
      { source: "/agents/:path*", destination: `${agents}/:path*` },
    ];
  },
};

export default nextConfig;

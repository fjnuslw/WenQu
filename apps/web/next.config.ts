import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 开发期允许 127.0.0.1/localhost 访问 dev 资源（Next 16 默认拦截跨源 dev 资源，会导致 hydration 静默失败）
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;

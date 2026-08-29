/** 运行时配置：显式声明。API key 允许缺席（服务可启动，建会话时显式 503），其余缺失即失败。 */

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

export interface AgentServiceConfig {
  port: number;
  dataDir: string;
  apiBaseUrl: string;
  defaultModel: string;
  /** DEEPSEEK_API_KEY 是否已配置；未配置时 /sessions 返回 503（显式而非运行中途炸裂） */
  hasApiKey: boolean;
}

/** 极简 .env 加载（KEY=VALUE，支持引号与 # 注释），避免额外依赖；字符串操作，不用正则。 */
function loadDotEnv(file: string): void {
  if (!existsSync(file)) return;
  for (const rawLine of readFileSync(file, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line === "" || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    const first = value[0];
    if (first !== undefined && value.length >= 2 && (first === '"' || first === "'") && value.endsWith(first)) {
      value = value.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = value;
  }
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AgentServiceConfig {
  loadDotEnv(path.resolve(process.cwd(), ".env"));
  const apiKey = env.DEEPSEEK_API_KEY ?? "";
  return {
    port: Number(env.AGENT_PORT ?? 23481),
    // 相对 apps/agents 的 cwd：../.. = 仓库根（与 api 的 data 目录同源）
    dataDir: env.AGENT_DATA_DIR ?? "../../data/sessions",
    apiBaseUrl: env.API_BASE_URL ?? "http://127.0.0.1:23480",
    defaultModel: env.AGENT_MODEL ?? "deepseek-v4-flash-vision-exp",
    hasApiKey: apiKey.length > 0,
  };
}

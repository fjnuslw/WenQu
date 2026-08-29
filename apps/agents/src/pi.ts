/**
 * 与 pi 生态的唯一接触面（spec §8 / 风险 1）：pi 的 API 变更只需要改这个文件。
 *
 * 模型注册说明：DeepSeek-V4-Flash-Vision-Exp 是实验性模型，尚未进入 pi-ai 0.84.3
 * 的静态目录（目录仅含 deepseek-v4-flash / deepseek-v4-pro）。处理方式是"显式配置"
 * 而非运行时兜底：用 createProvider 注册包含该模型条目的 deepseek provider。条目
 * 派生自同家族 deepseek-v4-flash 的目录配置（compat/thinking 参数同族共享），并开启
 * 图像输入；同时注册小写别名，便于按 DeepSeek 官方 id 风格配置。若上游请求字段不
 * 兼容，只需调整这里的派生来源。
 *
 * 已核实的接口（references/pi-mono，@earendil-works/pi-agent-core 0.84.3）：
 *   - `new Agent({ initialState: { systemPrompt, model }, streamFn })`
 *   - `agent.subscribe(cb)` / `await agent.prompt(text)`
 *   - 事件：message_update（assistantMessageEvent.text_delta.delta）、message_end
 *   - pi-ai：`createModels()` / `setProvider()` / `getModel()`；`createProvider`、
 *     `envApiKeyAuth` 由包根导出；`openAICompletionsApi` 位于子路径 api/openai-completions.lazy
 */
import { Agent, type AgentTool } from "@earendil-works/pi-agent-core";
import {
  createModels,
  createProvider,
  envApiKeyAuth,
  type Model,
  type Provider,
} from "@earendil-works/pi-ai";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";
import { DEEPSEEK_MODELS } from "@earendil-works/pi-ai/providers/deepseek.models";

import type { AgentServiceConfig } from "./config.js";

export const VISION_EXP_MODEL_ID = "DeepSeek-V4-Flash-Vision-Exp";

function buildDeepSeekProvider(): Provider<"openai-completions"> {
  const catalog = Object.values(DEEPSEEK_MODELS) as unknown as Model<"openai-completions">[];
  const flash = catalog.find((model) => model.id === "deepseek-v4-flash");
  if (!flash) {
    throw new Error("pi-ai 目录缺少 deepseek-v4-flash 基准条目，无法派生实验模型配置");
  }
  const visionExp: Model<"openai-completions"> = {
    ...flash,
    id: VISION_EXP_MODEL_ID,
    name: "DeepSeek V4 Flash Vision Exp",
    input: ["text", "image"],
  };
  const alias: Model<"openai-completions"> = { ...visionExp, id: VISION_EXP_MODEL_ID.toLowerCase() };
  return createProvider<"openai-completions">({
    id: "deepseek",
    name: "DeepSeek",
    baseUrl: "https://api.deepseek.com",
    auth: { apiKey: envApiKeyAuth("DeepSeek API key", ["DEEPSEEK_API_KEY"]) },
    models: [visionExp, alias, ...catalog],
    api: openAICompletionsApi(),
  });
}

export interface PiRuntime {
  agentFactory: (systemPrompt: string, tools?: AgentTool[]) => Agent;
}

export function bootstrapPi(config: AgentServiceConfig): PiRuntime {
  const models = createModels();
  models.setProvider(buildDeepSeekProvider());
  const model = models.getModel("deepseek", config.defaultModel);
  if (!model) {
    throw new Error(`pi-ai 目录中不存在: deepseek/${config.defaultModel}`);
  }
  return {
    agentFactory: (systemPrompt: string, tools?: AgentTool[]) =>
      new Agent({
        initialState: tools ? { systemPrompt, model, tools } : { systemPrompt, model },
        streamFn: models.streamSimple.bind(models),
      }),
  };
}

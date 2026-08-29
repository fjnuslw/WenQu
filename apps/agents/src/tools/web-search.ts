/**
 * web_search 工具：Bing 国内站抓取（无需 API key，国内可达），cheerio DOM 解析（禁正则抠 HTML，spec §7）。
 * parameters 为纯 JSON Schema 对象——pi-ai 对非 strict 请求原样透传
 * （references/pi-mono/packages/ai/src/api/constrained-sampling.ts:129）。
 */

import * as cheerio from "cheerio";
import type { AgentTool } from "@earendil-works/pi-agent-core";

const HEADERS: Record<string, string> = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
  "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
};

export interface WebSearchResult {
  title: string;
  url: string;
  snippet: string;
}

export async function webSearch(query: string): Promise<WebSearchResult[]> {
  const response = await fetch(
    `https://cn.bing.com/search?q=${encodeURIComponent(query)}&count=8&setlang=zh-hans`,
    { headers: HEADERS },
  );
  if (!response.ok) throw new Error(`Bing 返回 ${response.status}`);
  const $ = cheerio.load(await response.text());
  const results: WebSearchResult[] = [];
  $("li.b_algo").each((_, element) => {
    const anchor = $(element).find("h2 a").first();
    const title = anchor.text().trim();
    const url = anchor.attr("href") ?? "";
    // 摘要截断：控制工具结果体积，避免搜索噪声膨胀上下文（token 开销）
    const rawSnippet = $(element).find(".b_caption p, .b_lineclamp2, .b_lineclamp3").first().text().trim();
    const snippet = rawSnippet.length > 280 ? `${rawSnippet.slice(0, 280)}…` : rawSnippet;
    if (title && url) results.push({ title, url, snippet });
  });
  return results.slice(0, 5);
}

interface WebSearchArgs {
  query: string;
}

export const webSearchTool: AgentTool = {
  name: "web_search",
  label: "联网搜索",
  description:
    "搜索互联网（Bing）获取技术资料，返回标题、链接与摘要。解答时效性问题、版本相关内容或需要佐证时使用；纯概念题可不用。",
  parameters: {
    type: "object",
    properties: {
      query: { type: "string", description: "搜索关键词，如 'DeepSeek V3 MLA 原理'" },
    },
    required: ["query"],
    additionalProperties: false,
  },
  // pi-agent-core 的 execute 签名：首参是 toolCallId，第二参才是模型给的参数
  // （此前误把首参当 args，query 恒为 undefined → 真去搜了 "undefined" 这个词）
  execute: async (_toolCallId: string, args: WebSearchArgs) => {
    const query = typeof args?.query === "string" ? args.query.trim() : "";
    if (!query) {
      throw new Error("web_search 需要非空的字符串参数 query（搜索关键词）");
    }
    const results = await webSearch(query);
    if (results.length === 0) {
      return {
        content: [{ type: "text", text: `未搜索到与「${query}」相关的结果。` }],
        details: { count: 0 },
      };
    }
    const text = results
      .map((result, index) => `[${index + 1}] ${result.title}\n${result.url}\n${result.snippet}`)
      .join("\n\n");
    return {
      content: [{ type: "text", text }],
      details: { count: results.length },
    };
  },
} as unknown as AgentTool;

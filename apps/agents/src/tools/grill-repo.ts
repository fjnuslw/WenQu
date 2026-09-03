/**
 * 项目拷打只读工具面（G1）：
 * 本地基础工具 + API 能力工具——刻意排除 write/bash（拷打官只能读不能改）。
 * 路径监狱：所有读取 resolve 后必须仍在项目根内；单文件读取上限 64KB。
 * execute 签名：(toolCallId, params, ...)——pi-agent-core 契约（web-search 踩坑后固化）。
 */

import { readdir, realpath, stat } from "node:fs/promises";
import path from "node:path";

import type { AgentTool } from "@earendil-works/pi-agent-core";

const MAX_READ_BYTES = 64 * 1024;
const MAX_LIST_ENTRIES = 300;
const MAX_SEARCH_HITS = 40;

const EXCLUDE_DIRS = new Set([
  ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
  "out", "target", ".next", ".turbo", "coverage", ".idea", ".vscode", ".tmp", ".ruff_cache",
  ".workbuddy", ".zcode", "miniprogram_npm", "uni_modules", "unpackage", "vendor", "Pods",
]);

/** 路径监狱：把用户给的相对路径安全拼到项目根，逃逸即抛错（不静默兜底）。 */
function jailResolve(root: string, relPath: string): string {
  const rootResolved = path.resolve(root);
  const target = path.resolve(rootResolved, relPath);
  if (target !== rootResolved && !target.startsWith(rootResolved + path.sep)) {
    throw new Error(`路径越界（只能访问项目内文件）: ${relPath}`);
  }
  return target;
}

/** Existing-path guard: lexical containment alone is insufficient when a repository has symlinks. */
async function jailExisting(root: string, relPath: string): Promise<string> {
  const lexicalTarget = jailResolve(root, relPath);
  const [realRoot, realTarget] = await Promise.all([realpath(path.resolve(root)), realpath(lexicalTarget)]);
  if (realTarget !== realRoot && !realTarget.startsWith(realRoot + path.sep)) {
    throw new Error(`符号链接越界（只能访问项目内文件）: ${relPath}`);
  }
  return realTarget;
}

async function walkFiles(root: string, relDir: string, out: string[], depth: number): Promise<void> {
  if (out.length >= MAX_LIST_ENTRIES || depth > 8) return;
  const absDir = await jailExisting(root, relDir);
  const entries = await readdir(absDir, { withFileTypes: true });
  for (const entry of entries.sort((a, b) => (a.isDirectory() === b.isDirectory() ? a.name.localeCompare(b.name) : a.isDirectory() ? -1 : 1))) {
    if (out.length >= MAX_LIST_ENTRIES) return;
    const rel = relDir ? `${relDir}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      if (EXCLUDE_DIRS.has(entry.name)) continue;
      out.push(`${rel}/`);
      await walkFiles(root, rel, out, depth + 1);
    } else {
      out.push(rel);
    }
  }
}

export interface GrillTools {
  listFiles: AgentTool;
  readFile: AgentTool;
  searchCode: AgentTool;
  getRepoMap?: AgentTool;
  semanticSearch?: AgentTool;
  getGitOwnership?: AgentTool;
  all: AgentTool[];
}

export interface GrillToolOptions {
  projectId: number;
  apiBaseUrl: string;
  capabilities?: {
    repoMap?: boolean;
    semanticSearch?: boolean;
    gitOwnership?: boolean;
  };
}

export function buildGrillTools(projectRoot: string, options?: GrillToolOptions): GrillTools {
  const listFiles: AgentTool = {
    name: "list_files",
    label: "列目录",
    description: "列出项目内指定目录的文件树（dir 省略 = 项目根）。返回相对路径列表，目录以 / 结尾。",
    parameters: {
      type: "object",
      properties: {
        dir: { type: "string", description: "相对路径，如 'src'；省略为根目录" },
      },
      additionalProperties: false,
    },
    execute: async (_toolCallId: string, args: { dir?: string }) => {
      const out: string[] = [];
      await walkFiles(projectRoot, (args?.dir ?? "").replace(/\\/g, "/"), out, 0);
      if (out.length === 0) throw new Error(`目录为空或不存在: ${args?.dir ?? "(根)"}`);
      return {
        content: [{ type: "text", text: out.join("\n") }],
        details: { count: out.length },
      };
    },
  } as unknown as AgentTool;

  const readFile: AgentTool = {
    name: "read_file",
    label: "读文件",
    description: "读取项目内一个源文件（path 为相对路径），返回带行号的全文（超过 64KB 截断）。",
    parameters: {
      type: "object",
      properties: {
        path: { type: "string", description: "相对路径，如 'src/server.ts'" },
        start_line: { type: "number", description: "起始行（1 起，可省）" },
        end_line: { type: "number", description: "结束行（可省）" },
      },
      required: ["path"],
      additionalProperties: false,
    },
    execute: async (_toolCallId: string, args: { path: string; start_line?: number; end_line?: number }) => {
      if (typeof args?.path !== "string" || !args.path.trim()) {
        throw new Error("read_file 需要非空字符串参数 path");
      }
      const abs = await jailExisting(projectRoot, args.path.replace(/\\/g, "/"));
      const info = await stat(abs);
      if (!info.isFile()) throw new Error(`不是文件: ${args.path}`);
      const raw = await readFileUtf8(abs);
      const lines = raw.split("\n");
      const start = Math.max(1, args.start_line ?? 1);
      const end = Math.min(lines.length, args.end_line ?? lines.length);
      const numbered = lines
        .slice(start - 1, end)
        .map((line, index) => `${start + index} | ${line}`)
        .join("\n");
      return {
        content: [
          { type: "text", text: `${args.path}（第 ${start}-${end} 行，共 ${lines.length} 行）\n${numbered}` },
        ],
        details: { path: args.path, start, end, total_lines: lines.length },
      };
    },
  } as unknown as AgentTool;

  const searchCode: AgentTool = {
    name: "search_code",
    label: "搜代码",
    description: "在项目源码里搜一段文本（子串匹配，区分大小写；用于找函数/类/关键词出现的位置）。返回 文件:行号 与该行内容。",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "要搜的文本，如 'streamSSE' 或 'def create_plan'" },
      },
      required: ["query"],
      additionalProperties: false,
    },
    execute: async (_toolCallId: string, args: { query: string }) => {
      const query = typeof args?.query === "string" ? args.query : "";
      if (!query.trim()) throw new Error("search_code 需要非空字符串参数 query");
      const hits: string[] = [];
      await searchWalk(projectRoot, "", query, hits);
      if (hits.length === 0) {
        return { content: [{ type: "text", text: `未找到「${query}」` }], details: { count: 0 } };
      }
      return {
        content: [{ type: "text", text: hits.join("\n") }],
        details: { count: hits.length, query },
      };
    },
  } as unknown as AgentTool;

  const getRepoMap =
    options?.capabilities?.repoMap === true
      ? ({
          name: "get_repo_map",
          label: "看仓库地图",
          description:
            "读取 Tree-sitter 符号引用图排序后的仓库地图。适合先找架构中心和关键符号，再用 read_file 核证。",
          parameters: { type: "object", properties: {}, additionalProperties: false },
          execute: async () => {
            const data = await apiJson(
              options.apiBaseUrl,
              `/api/grill/projects/${options.projectId}/map`,
            );
            const text = typeof data.text === "string" ? data.text : "";
            if (!text) throw new Error("repo map 为空");
            return {
              content: [{ type: "text", text }],
              details: {
                parsedFiles: data.parsed_files,
                coverage: data.coverage,
                edgeCount: data.edge_count,
              },
            };
          },
        } as unknown as AgentTool)
      : undefined;

  const semanticSearch =
    options?.capabilities?.semanticSearch === true
      ? ({
          name: "semantic_search",
          label: "语义搜代码",
          description:
            "按自然语言语义搜索项目代码块，返回相关的文件:行号和源码。用于不知道函数名、只知道职责时定位实现。",
          parameters: {
            type: "object",
            properties: {
              query: { type: "string", description: "自然语言职责或设计意图，一次只搜一个目标" },
              limit: { type: "number", description: "返回 1-8 条，省略为 5" },
            },
            required: ["query"],
            additionalProperties: false,
          },
          execute: async (_toolCallId: string, args: { query: string; limit?: number }) => {
            const query = typeof args?.query === "string" ? args.query.trim() : "";
            if (!query) throw new Error("semantic_search 需要非空字符串参数 query");
            const data = await apiJson(
              options.apiBaseUrl,
              `/api/grill/projects/${options.projectId}/search`,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query, limit: Math.max(1, Math.min(args.limit ?? 5, 8)) }),
              },
            );
            const hits = Array.isArray(data.hits) ? data.hits : [];
            const text = hits.length
              ? hits
                  .map((raw) => {
                    const hit = raw as Record<string, unknown>;
                    const pathValue = String(hit.path ?? "unknown");
                    const start = Number(hit.start_line ?? 1);
                    const end = Number(hit.end_line ?? start);
                    const score = Number(hit.score ?? 0).toFixed(3);
                    const content = String(hit.content ?? "").slice(0, 2200);
                    return `${pathValue}:${start}-${end} [score=${score}]\n${content}`;
                  })
                  .join("\n\n---\n\n")
              : `没有找到与「${query}」相关的语义结果`;
            return { content: [{ type: "text", text }], details: { count: hits.length, query } };
          },
        } as unknown as AgentTool)
      : undefined;

  const getGitOwnership =
    options?.capabilities?.gitOwnership === true
      ? ({
          name: "get_git_ownership",
          label: "查 Git 归属",
          description:
            "读取 Git 历史归属摘要；可传相对路径查看该文件主要作者。只用于核实候选人贡献，不把提交量等同于能力。",
          parameters: {
            type: "object",
            properties: {
              path: { type: "string", description: "可选的项目内相对文件路径" },
            },
            additionalProperties: false,
          },
          execute: async (_toolCallId: string, args: { path?: string }) => {
            const pathQuery = args?.path?.trim()
              ? `?path=${encodeURIComponent(args.path.trim())}`
              : "";
            const data = await apiJson(
              options.apiBaseUrl,
              `/api/grill/projects/${options.projectId}/ownership${pathQuery}`,
            );
            return {
              content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
              details: { path: args?.path ?? null },
            };
          },
        } as unknown as AgentTool)
      : undefined;

  const all = [listFiles, readFile, searchCode, getRepoMap, semanticSearch, getGitOwnership].filter(
    (tool): tool is AgentTool => tool !== undefined,
  );
  return { listFiles, readFile, searchCode, getRepoMap, semanticSearch, getGitOwnership, all };
}

async function apiJson(
  baseUrl: string,
  apiPath: string,
  init?: RequestInit,
): Promise<Record<string, unknown>> {
  const normalizedBase = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
  const response = await fetch(`${normalizedBase}${apiPath}`, init);
  const payload = (await response.json().catch(() => null)) as
    | Record<string, unknown>
    | null;
  if (!response.ok) {
    const error = payload?.error as { message?: unknown } | undefined;
    throw new Error(
      typeof error?.message === "string" ? error.message : `仓库智能 API 返回 ${response.status}`,
    );
  }
  if (!payload) throw new Error("仓库智能 API 返回非 JSON 响应");
  return payload;
}

async function readFileUtf8(abs: string): Promise<string> {
  const { readFile } = await import("node:fs/promises");
  const buffer = await readFile(abs);
  return buffer.subarray(0, MAX_READ_BYTES).toString("utf8");
}

async function searchWalk(root: string, relDir: string, query: string, hits: string[]): Promise<void> {
  if (hits.length >= MAX_SEARCH_HITS) return;
  const absDir = await jailExisting(root, relDir);
  const entries = await readdir(absDir, { withFileTypes: true });
  for (const entry of entries) {
    if (hits.length >= MAX_SEARCH_HITS) return;
    const rel = relDir ? `${relDir}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      if (EXCLUDE_DIRS.has(entry.name)) continue;
      await searchWalk(root, rel, query, hits);
    } else {
      try {
        const abs = await jailExisting(root, rel);
        const info = await stat(abs);
        if (!info.isFile() || info.size > MAX_READ_BYTES * 4) continue;
        const text = await readFileUtf8(abs);
        const lines = text.split("\n");
        for (let index = 0; index < lines.length; index += 1) {
          const line = lines[index];
          if (line !== undefined && line.includes(query)) {
            hits.push(`${rel}:${index + 1} | ${line.trim().slice(0, 160)}`);
            if (hits.length >= MAX_SEARCH_HITS) return;
          }
        }
      } catch {
        // 二进制/无权限文件跳过（搜索的尽力而为是工具语义，不是兜底）
      }
    }
  }
}

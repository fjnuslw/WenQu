"use client";

import { code } from "@streamdown/code";
import { createMathPlugin } from "@streamdown/math";
import { Streamdown } from "streamdown";

import { cn } from "@/lib/utils";

import "katex/dist/katex.min.css";
import "streamdown/styles.css";

// 行内公式开单美元定界（DeepSeek 的 \( \) 会被下面的归一化转成 $...$）
const mathPlugin = createMathPlugin({ singleDollarTextMath: true });

/**
 * LLM 输出渲染：streamdown（流式 markdown，GFM/KaTeX/Shiki/未完成块容错）。
 * DeepSeek 习惯输出 \( \) 与 \[ \] 定界符，remark-math 只认 $ / $$——
 * 在代码栅栏外做纯字符串替换（display-layer 关切，不涉及内容语义）。
 */
function normalizeMathDelimiters(text: string): string {
  const segments = text.split("```");
  return segments
    .map((segment, index) => {
      if (index % 2 === 1) return segment; // 栅栏内原样保留
      return segment
        .replaceAll("\\[", () => "$$")
        .replaceAll("\\]", () => "$$")
        .replaceAll("\\(", () => "$")
        .replaceAll("\\)", () => "$");
    })
    .join("```");
}

/**
 * `文件路径:行号` → 可点击引用（拷打官回复的证据链入口）。
 * 这是生成侧的文本变换（把模式转成 markdown 链接），不是用正则解析 HTML/markdown——
 * spec §7 禁的是后者。仅 grill 语境启用，路径须含扩展名且行号为 1-5 位数字。
 */
const FILE_LINE_REF = /([A-Za-z0-9_\-./\\]+\.[A-Za-z0-9]{1,5}):(\d{1,5})/g;

function linkifyFileRefs(text: string): string {
  return text.replace(FILE_LINE_REF, (_match, path: string, line: string) => {
    return `[${path}:${line}](#open-file:${path}:${line})`;
  });
}

export function AssistantMarkdown({
  text,
  streaming = false,
  className,
  onOpenFileRef,
}: {
  text: string;
  streaming?: boolean;
  className?: string;
  /** 提供时启用 file:line 引用链接化（grill 模式）：点击回调 (path, line) */
  onOpenFileRef?: (path: string, line: number) => void;
}) {
  const body = onOpenFileRef
    ? linkifyFileRefs(normalizeMathDelimiters(text))
    : normalizeMathDelimiters(text);
  return (
    <Streamdown
      mode={streaming ? "streaming" : "static"}
      parseIncompleteMarkdown={streaming}
      plugins={{ code, math: mathPlugin }}
      className={cn("assistant-markdown text-sm leading-relaxed", className)}
      components={
        onOpenFileRef
          ? {
              a: ({ href, children }) => {
                if (typeof href === "string" && href.startsWith("#open-file:")) {
                  const ref = href.slice("#open-file:".length);
                  const separator = ref.lastIndexOf(":");
                  const path = ref.slice(0, separator);
                  const line = Number(ref.slice(separator + 1));
                  return (
                    <button
                      type="button"
                      className="rounded bg-accent/15 px-1 py-0.5 font-mono text-[0.85em] text-accent hover:bg-accent/25"
                      onClick={() => onOpenFileRef(path, Number.isFinite(line) ? line : 1)}
                    >
                      {children}
                    </button>
                  );
                }
                return <a href={href}>{children}</a>;
              },
            }
          : undefined
      }
    >
      {body}
    </Streamdown>
  );
}

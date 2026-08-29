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

export function AssistantMarkdown({
  text,
  streaming = false,
  className,
}: {
  text: string;
  streaming?: boolean;
  className?: string;
}) {
  return (
    <Streamdown
      mode={streaming ? "streaming" : "static"}
      parseIncompleteMarkdown={streaming}
      plugins={{ code, math: mathPlugin }}
      className={cn("assistant-markdown text-sm leading-relaxed", className)}
    >
      {normalizeMathDelimiters(text)}
    </Streamdown>
  );
}

"""非 GitHub 资源链接存活校验（只读）。

GitHub 仓库用 API 核验，课程/文档/论文/工具站用 HTTP 探测。
策略：先 HEAD，405/403 或返回异常时退化为 GET 读前 2KB（不落盘正文，只取状态与标题）。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

URLS = [
    # ---- 系统课程 ----
    "https://www.deeplearning.ai/short-courses/",
    "https://www.deeplearning.ai/short-courses/building-and-evaluating-advanced-rag/",
    "https://www.deeplearning.ai/short-courses/multi-ai-agent-systems-with-crewai/",
    "https://www.deeplearning.ai/short-courses/ai-agents-in-langgraph/",
    "https://huggingface.co/learn/llm-course/chapter1/1",
    "https://huggingface.co/learn/nlp-course/chapter1/1",
    "https://stanford-cs336.github.io/spring2025/",
    "https://web.stanford.edu/class/cs224n/",
    "https://fullstackdeeplearning.com/course/2022/",
    "https://madewithml.com/",
    "https://mlops-zoomcamp.com/",
    "https://www.ml.school/",
    # ---- 官方与框架文档 ----
    "https://modelcontextprotocol.io/",
    "https://docs.langchain.com/",
    "https://langchain-ai.github.io/langgraph/",
    "https://docs.llamaindex.ai/en/stable/",
    "https://dspy.ai/",
    "https://docs.vllm.ai/",
    "https://docs.dify.ai/",
    "https://docs.unsloth.ai/",
    "https://docs.sglang.ai/",
    "https://docs.anthropic.com/en/docs/build-with-claude/overview",
    "https://platform.openai.com/docs/guides/function-calling",
    # ---- 方法论/工程实践文章 ----
    "https://www.anthropic.com/research/building-effective-agents",
    "https://www.anthropic.com/engineering/writing-tools-for-agents",
    "https://www.promptingguide.ai/",
    "https://cookbook.openai.com/",
    "https://docs.claude.com/en/docs/agents-and-tools/agent-sdk/overview",
    # ---- 中文站点 ----
    "https://www.hello-algo.com/",
    "https://programmercarl.com/",
    "https://codetop.cc/",
    "https://neetcode.io/",
    "https://www.nowcoder.com/ta",
    "https://leetcode.cn/studyplan/top-100-liked/",
    "https://leetcode.cn/",
    "https://datawhale.cn/",
    "https://datawhalechina.github.io/all-in-rag/",
    "https://datawhalechina.github.io/hello-agents/",
    "https://llmbook-zh.github.io/",
    "https://github.com/stas00/ml-engineering",
    "https://arxiv.org/abs/2506.15655",
    # ---- 论文 ----
    "https://arxiv.org/abs/1706.03762",
    "https://arxiv.org/abs/2005.11401",
    "https://arxiv.org/abs/2106.09685",
    "https://arxiv.org/abs/2305.14314",
    "https://arxiv.org/abs/2205.14135",
    "https://arxiv.org/abs/2309.06180",
    "https://arxiv.org/abs/2308.04079",
    "https://arxiv.org/abs/2308.08155",
    "https://arxiv.org/abs/2210.03629",
    "https://arxiv.org/abs/2201.11903",
    "https://arxiv.org/abs/2305.18290",
    "https://arxiv.org/abs/2501.12948",
    "https://arxiv.org/abs/2402.03300",
    "https://arxiv.org/abs/1910.01108",
    "https://arxiv.org/abs/2001.08361",
    "https://arxiv.org/abs/2203.15556",
    "https://arxiv.org/abs/2104.09864",
    "https://arxiv.org/abs/2305.13245",
    "https://arxiv.org/abs/2306.15595",
]


def probe(url: str) -> dict:
    result = {"url": url, "status": None, "method": None, "error": None, "title": None}
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, headers=UA, method=method)
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                result["status"] = resp.status
                result["method"] = method
                result["final_url"] = resp.geturl()
                if method == "GET":
                    body = resp.read(4096).decode("utf-8", errors="ignore")
                    lo = body.lower()
                    if "<title" in lo:
                        start = lo.find("<title") + 7
                        end = lo.find("</title>", start)
                        result["title"] = body[start:end].strip()[:120]
                return result
        except urllib.error.HTTPError as exc:
            if method == "GET":
                result["status"] = exc.code
                result["method"] = method
                result["error"] = str(exc.reason)
                return result
            if exc.code not in (403, 405, 400, 501, 429):
                result["status"] = exc.code
                result["method"] = method
                result["error"] = str(exc.reason)
                return result
        except Exception as exc:  # noqa: BLE001 - 网络探测需要兜住所有异常并记录
            if method == "GET":
                result["error"] = f"{type(exc).__name__}: {exc}"
                return result
    return result


def main() -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(probe, URLS))
    ok = sum(1 for r in results if r["status"] and 200 <= r["status"] < 400)
    (OUT_DIR / "link_check.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    for r in results:
        flag = "OK " if r["status"] and 200 <= r["status"] < 400 else "BAD"
        print(f"{flag} {str(r['status']):<5} {r['url']}")
    print(f"ok={ok}/{len(results)}")


if __name__ == "__main__":
    main()

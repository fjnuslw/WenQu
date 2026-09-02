"""校验全部锚点 URL 的存活状态。

- 200/2xx/3xx → 通过
- 404 → 明确失效（需修）
- 403/405/429 或超时 → 可疑（可能是反爬/限流，标记人工复核，不自动判死）
GitHub blob 页面对爬虫常返回 200（raw 或 blob 都行）；文档站 HEAD 被拒时退 GET 读 1KB。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "apps" / "api" / "src"))

from getoffer.paths.catalog import load_catalog  # noqa: E402

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def probe(url: str) -> tuple[int | None, str]:
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, headers=UA, method=method)
            with urllib.request.urlopen(req, timeout=25) as resp:
                resp.read(512) if method == "GET" else None
                return resp.status, method
        except urllib.error.HTTPError as exc:
            if method == "GET":
                return exc.code, "GET"
            if exc.code not in (403, 405, 429, 400, 501):
                return exc.code, method
        except Exception as exc:  # noqa: BLE001
            if method == "GET":
                return None, type(exc).__name__
    return None, "unknown"


def main() -> None:
    catalog = load_catalog()
    urls: list[tuple[str, str, str]] = []  # (node, resource_id, url)
    for node in catalog.nodes:
        for rid, pins in node.pins.items():
            for pin in pins:
                urls.append((node.id, rid, pin.url))

    print(f"共 {len(urls)} 个锚点，并发探测…\n")
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda u: (u, probe(u[2])), urls))

    broken, suspicious = [], []
    for (node, rid, url), (status, method) in results:
        if status and 200 <= status < 400:
            continue
        if status == 404:
            broken.append((node, rid, url))
        else:
            suspicious.append((node, rid, url, status, method))

    print(f"失效(404) {len(broken)} 个：")
    for node, rid, url in broken:
        print(f"  404  [{node}] {url}")

    print(f"\n可疑(需人工复核) {len(suspicious)} 个：")
    for node, rid, url, status, method in suspicious:
        print(f"  {status}/{method}  [{node}] {url}")

    (ROOT / "pin_check.json").write_text(
        json.dumps({"broken": broken, "suspicious": suspicious}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n总计 {len(urls)}，明确失效 {len(broken)}，可疑 {len(suspicious)}")


if __name__ == "__main__":
    main()

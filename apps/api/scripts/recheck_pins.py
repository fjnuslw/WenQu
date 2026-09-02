"""学习路径锚点复检（F7 P2）。

链接会腐烂——仓库会重命名文件、文档站会改版、公司会下线页面。
本脚本把「一次性校验」变成「可重复执行的巡检」，供手动或定时运行：

    python scripts/recheck_pins.py                 # 全量巡检，控制台摘要
    python scripts/recheck_pins.py --json          # 输出机器可读报告
    python scripts/recheck_pins.py --only lc-      # 只查手撕线（节点 id 前缀）
    python scripts/recheck_pins.py --workers 4     # 降并发（网络不稳时）
    python scripts/recheck_pins.py --since-days 90 # 与上次巡检间隔不足则跳过

判定口径（保守，不冤枉好链接）：
- 2xx / 3xx → 通过（重定向会跟随，urllib 默认跟随 5 跳）
- 404 / 410 → 明确失效，必须修
- 403 / 405 / 429 / 超时 / 连接错误 → 可疑。多是反爬与限流而非真死，
  不自动判死，只提示人工复核；连续两次可疑才升级为待修。

退出码：0 = 无明确失效；1 = 存在明确失效（可用于定时任务告警）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

API_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(API_SRC))

from getoffer.paths.catalog import STALE_PUSH_DAYS, load_catalog  # noqa: E402

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

# 这些状态码不是"页面没了"，而是对方拒绝 HEAD 或限流，需退 GET 复核
RETRY_ON_HEAD = (400, 403, 405, 429, 501)

# 报告落在项目根 data/（与 sessions 等运行时数据同级），而非 apps/ 下
# recheck_pins.py 位于 apps/api/scripts/ → parents[3] = 项目根
PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = PROJECT_ROOT / "data" / "pin_recheck_report.json"


def probe(url: str) -> tuple[int | None, str]:
    """探测单个 URL：先 HEAD，被拒则退 GET 读 512 字节。"""
    last_method = "HEAD"
    for method in ("HEAD", "GET"):
        last_method = method
        try:
            req = urllib.request.Request(url, headers=UA, method=method)
            with urllib.request.urlopen(req, timeout=30) as resp:
                if method == "GET":
                    resp.read(512)
                return resp.status, method
        except urllib.error.HTTPError as exc:
            if method == "GET":
                return exc.code, "GET"
            if exc.code not in RETRY_ON_HEAD:
                return exc.code, method
        except Exception as exc:  # noqa: BLE001
            if method == "GET":
                return None, type(exc).__name__
    return None, last_method


def classify(status: int | None) -> str:
    if status is None:
        return "suspicious"
    if 200 <= status < 400:
        return "ok"
    if status in (404, 410):
        return "broken"
    return "suspicious"


def load_previous() -> dict:
    """上一次巡检结果：用于把"连续两次可疑"升级为待修。"""
    if not REPORT_PATH.exists():
        return {}
    try:
        data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        return {item["url"]: item["verdict"] for item in data.get("items", [])}
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="学习路径锚点链接复检")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告而非人类可读摘要")
    parser.add_argument("--only", default="", help="只检指定节点 id 前缀，如 lc- / app-")
    parser.add_argument("--workers", type=int, default=12, help="并发数（默认 12）")
    parser.add_argument("--since-days", type=int, default=0, help="距上次巡检不足 N 天则跳过")
    parser.add_argument("--include-resources", action="store_true", help="同时探测资源首页")
    args = parser.parse_args()

    # 间隔保护：避免定时任务每次都打外部站点
    if args.since_days > 0 and REPORT_PATH.exists():
        try:
            prev = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
            last = datetime.fromisoformat(prev["checked_at"])
            elapsed = (datetime.now(UTC) - last).days
            if elapsed < args.since_days:
                print(f"距上次巡检仅 {elapsed} 天（阈值 {args.since_days}），跳过。")
                return 0
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    catalog = load_catalog()
    previous = load_previous()

    targets: list[tuple[str, str, str, str]] = []  # (kind, node_id, resource_id, url)
    for node in catalog.nodes:
        if args.only and not node.id.startswith(args.only):
            continue
        for rid, pins in node.pins.items():
            for pin in pins:
                targets.append(("pin", node.id, rid, pin.url))
        if args.include_resources:
            for rid in node.resources:
                targets.append(("home", node.id, rid, catalog.resource_by_id[rid].url))

    # 同一 URL 可能被多个节点引用，去重后只打一次
    unique = {item[3]: item for item in targets}
    urls = list(unique.keys())

    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        statuses = dict(zip(urls, pool.map(probe, urls), strict=False))
    elapsed_s = round(time.time() - started, 1)

    items = []
    for url in urls:
        kind, node_id, rid, _ = unique[url]
        status, method = statuses[url]
        verdict = classify(status)
        # 连续两次可疑 → 升级为待修：单次可疑多为限流，重复可疑说明确实有问题
        escalated = verdict == "suspicious" and previous.get(url) == "suspicious"
        items.append(
            {
                "kind": kind,
                "node": node_id,
                "resource": rid,
                "url": url,
                "status": status,
                "method": method,
                "verdict": "broken" if escalated else verdict,
                "escalated": escalated,
            }
        )

    broken = [i for i in items if i["verdict"] == "broken"]
    suspicious = [i for i in items if i["verdict"] == "suspicious"]

    # 资源陈旧度：来自目录自身的 pushed_at，不消耗任何网络请求
    today = date.today()
    stale = []
    seen: set[str] = set()
    for resource in catalog.resources:
        if resource.id in seen or not resource.pushed_at or resource.internal:
            continue
        seen.add(resource.id)
        try:
            pushed = date.fromisoformat(resource.pushed_at[:10])
        except ValueError:
            continue
        days = (today - pushed).days
        if days > STALE_PUSH_DAYS:
            stale.append({"id": resource.id, "title": resource.title, "days": days})

    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": elapsed_s,
        "total": len(items),
        "broken_count": len(broken),
        "suspicious_count": len(suspicious),
        "stale_count": len(stale),
        "items": items,
        "stale_resources": stale,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 1 if broken else 0

    print(f"巡检 {len(items)} 条链接（去重后），耗时 {elapsed_s}s")
    print(f"  通过     {len(items) - len(broken) - len(suspicious)}")
    print(f"  明确失效 {len(broken)}")
    print(f"  可疑     {len(suspicious)}")
    print(f"  陈旧资源 {len(stale)}（>{STALE_PUSH_DAYS} 天未更新）")

    if broken:
        print("\n明确失效（必须修）：")
        for item in broken:
            tag = " [连续可疑升级]" if item["escalated"] else ""
            print(f"  {item['status']} [{item['node']} · {item['resource']}]{tag}")
            print(f"       {item['url']}")
    if suspicious:
        print("\n可疑（多为限流/反爬，人工复核）：")
        for item in suspicious:
            print(f"  {item['status']}/{item['method']} [{item['node']}] {item['url']}")
    if stale:
        print("\n陈旧资源（考虑替换或标注）：")
        for item in stale[:15]:
            print(f"  {item['days']} 天 · {item['title'][:48]}")

    print(f"\n完整报告：{REPORT_PATH}")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())

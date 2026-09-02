"""全源批量导入 runner：把一个（或全部）摄入源按批次跑到收敛。

用法（在 apps/api 目录、venv 下）：
    .venv/Scripts/python scripts/import_source.py --slug faq-of-llm-interview
    .venv/Scripts/python scripts/import_source.py --all            # 顺序跑所有可导入源

错误熔断：连续 5 个批次失败即终止该源。
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from getoffer.ingest.sources import SOURCES, AllowedUse  # noqa: E402


def run_source(client: httpx.Client, base_url: str, slug: str, batch: int, max_batches: int) -> bool:
    """跑单个源直到收敛；返回是否成功。"""
    consecutive_errors = 0
    for batch_no in range(1, max_batches + 1):
        try:
            response = client.post(f"{base_url}/api/ingest/sources/{slug}/run", params={"max_files": batch})
        except httpx.HTTPError as exc:
            print(f"  [{slug}] batch {batch_no}: 请求失败 {exc}")
            consecutive_errors += 1
            if consecutive_errors >= 5:
                print(f"  [{slug}] 连续 5 次失败，熔断")
                return False
            time.sleep(5)
            continue
        # 服务端可能返回非 JSON（如未处理异常的裸 500）：按错误计数处理，绝不因此崩掉整个作业
        try:
            payload = response.json()
        except ValueError:
            payload = {
                "error": {
                    "message": response.text[:200] or "(empty body)",
                    "status": response.status_code,
                }
            }
        if response.status_code != 200 or "error" in payload:
            print(f"  [{slug}] batch {batch_no}: {payload}")
            consecutive_errors += 1
            if consecutive_errors >= 5:
                print(f"  [{slug}] 连续 5 次失败，熔断")
                return False
            time.sleep(5)
            continue
        consecutive_errors = 0
        print(
            f"  [{slug}] batch {batch_no}: +{payload['inserted']} "
            f"(dup {payload['duplicates']}, 剩余 {payload['files_remaining']})"
        )
        if payload["files_remaining"] == 0:
            print(f"  [{slug}] 全部文件处理完成")
            return True
        time.sleep(2)
    print(f"  [{slug}] 达到最大批次数")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--slug", help="单个源 slug")
    group.add_argument("--all", action="store_true", help="顺序跑所有非 reference_only 源")
    parser.add_argument("--batch", type=int, default=12)
    parser.add_argument("--max-batches", type=int, default=200)
    args = parser.parse_args()

    base_url = "http://127.0.0.1:23480"
    slugs = (
        [spec.slug for spec in SOURCES.values() if spec.allowed_use is not AllowedUse.REFERENCE_ONLY]
        if args.all
        else [args.slug]
    )
    if args.all:
        print(f"可导入源 {len(slugs)} 个（reference_only 已跳过）")

    with httpx.Client(timeout=600) as client:
        health = client.get(f"{base_url}/api/health")
        health.raise_for_status()
        for slug in slugs:
            print(f"==> 导入源 {slug}")
            run_source(client, base_url, slug, args.batch, args.max_batches)
            time.sleep(3)
    print("全部完成")


if __name__ == "__main__":
    main()

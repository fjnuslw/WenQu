"""把核验过的资源清单导出为 api 侧数据文件。

输出：apps/api/src/getoffer/paths/data/resources.json
约束：只导出「节点会引用」的字段，不搬运任何正文；数字全部回读取证数据。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API_DATA = ROOT.parents[1] / "apps" / "api" / "src" / "getoffer" / "paths" / "data"

KEEP = (
    "id",
    "track",
    "stage",
    "priority",
    "kind",
    "title",
    "url",
    "repo",
    "stars",
    "license",
    "pushed_at",
    "why",
)


def main() -> None:
    rows = json.loads((ROOT / "inventory.json").read_text(encoding="utf-8"))
    out = []
    for row in rows:
        item = {key: row.get(key) for key in KEEP}
        item["internal"] = bool(row.get("internal"))
        out.append(item)
    API_DATA.mkdir(parents=True, exist_ok=True)
    (API_DATA / "resources.json").write_text(
        json.dumps({"verified_at": "2026-08-30", "items": out}, ensure_ascii=False, indent=1)
        + "\n",
        encoding="utf-8",
    )
    print(f"exported {len(out)} resources -> {API_DATA / 'resources.json'}")


if __name__ == "__main__":
    main()

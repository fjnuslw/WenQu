"""机械清理：剔除「锚点 URL == 资源首页 URL」的冗余 pin。

规则：锚点必须比资源本身更具体；相等即冗余，直接删。
论文类资源（arxiv abs 就是该资源 url）因此会失去冗余 pin——这是对的，论文本身就是精确位置。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # 仓库根
API = ROOT / "apps" / "api" / "src" / "getoffer" / "paths"
DATA = API / "data"

resources = json.loads((DATA / "resources.json").read_text(encoding="utf-8"))["items"]
res_url = {r["id"]: r["url"].rstrip("/") for r in resources}

changed = 0
for name in ["nodes_l0", "nodes_app", "nodes_algo", "nodes_dev", "nodes_lc"]:
    path = DATA / f"{name}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    for node in doc["nodes"]:
        pins = node.get("pins", {})
        for rid in list(pins.keys()):
            rurl = res_url.get(rid, "")
            kept = [pin for pin in pins[rid] if pin["url"].rstrip("/") != rurl]
            if kept:
                pins[rid] = kept
            else:
                del pins[rid]
                changed += 1
        if not pins:
            node.pop("pins", None)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

print(f"removed {changed} empty-pin entries")

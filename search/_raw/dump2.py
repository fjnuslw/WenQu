"""打印写锚点所需的目录结构（第二次汇总）。"""
from __future__ import annotations

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
t = json.loads((ROOT / "gh_trees.json").read_text(encoding="utf-8"))
a = json.loads((ROOT / "anchor_trees.json").read_text(encoding="utf-8"))
a2 = json.loads((ROOT / "anchor_trees2.json").read_text(encoding="utf-8"))

def files(repo: str) -> list[str]:
    d = t.get(repo) or a.get(repo) or a2.get(repo)
    return [p.lstrip("/") for p in (d.get("kept") or d.get("files", []))] if d else []

def ls(repo, pat="", n=14, ext=(".md", ".ipynb", ".py", ".mdx", ".yaml", ".yml")):
    ps = [
        p for p in files(repo)
        if p.lower().endswith(ext)
        and not any(x in p.lower() for x in ("/images/", "/pics/", ".github/", "changelog", "contributing", "license", ".gitignore"))
    ]
    if pat:
        ps = [p for p in ps if pat.lower() in p.lower()]
    print(f"=== {repo} [{pat}] {len(ps)}")
    for p in ps[:n]:
        print("   ", p)

ls("datawhalechina/hello-agents", "章 ", 20)
ls("bojieli/ai-agent-book", "", 24)
ls("huggingface/peft", "conceptual", 10)
ls("pguso/agents-from-scratch", "", 20)
ls("pguso/rag-from-scratch", "", 20)
ls("The-Pocket/PocketFlow-Tutorial-Codebase-Knowledge", "", 16)
ls("shareAI-lab/learn-claude-code", "", 18)
ls("HKUDS/LightRAG", "examples", 12)
ls("infiniflow/ragflow", "docs/guides", 12)
ls("ConardLi/easy-dataset", "", 14)
ls("modelscope/ms-swift", "docs/source_en", 8)
ls("axolotl-ai-cloud/axolotl", "README", 4)
ls("unslothai/unsloth", "", 10)
ls("microsoft/autogen", "website/docs", 8)
ls("khangich/machine-learning-interview", "", 14)

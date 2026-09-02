"""学习路径目录：加载、校验与查询（F7）。

设计要点（spec 续二十二 §3）：
- **目录不落库**：paths/stages/nodes/resources 是内容，放 JSON 进 Git，可 diff 可评审；
  数据库只存用户进度（`learning_enrollments` / `learning_node_progress`）。
- **零静默降级**：Pydantic 全量校验 + 交叉引用检查（stage 存在、resource id 存在、
  节点 id 唯一、阶段内 order 不重复），任一失败抛 `PathsCatalogError`。
- **进程内缓存**：目录只读且随版本发布，首次加载后缓存；不提供热重载，改目录走重启。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from getoffer.errors import PathsCatalogError
from getoffer.ingest.tag_vocab import CANONICAL_TAGS

DATA_DIR = Path(__file__).resolve().parent / "data"

# 阶段/节点的 stale 判定阈值（天）：资源超过该时间未推送，前端提示可能过时
STALE_PUSH_DAYS = 365

# 节点 related.tags 白名单：题库 canonical 标签 + 岗位大类（track）。
# 标签要用于 /bank?tag=X 深链，写错（「手撕」而非「手撕代码」）会静默筛出 0 题，
# 因此加载期硬校验拦截。
ALLOWED_NODE_TAGS: frozenset[str] = frozenset(CANONICAL_TAGS) | frozenset(
    {"大模型应用", "大模型算法", "大模型应用算法", "视觉算法", "通用基础", "数据工程"}
)


class ResourceModel(BaseModel):
    id: str
    track: str
    stage: int
    priority: Literal["core", "optional", "reference"]
    kind: Literal["repo", "course", "doc", "paper", "book", "site"]
    title: str
    url: str
    repo: str | None = None
    stars: int | None = None
    license: str | None = None
    pushed_at: str | None = None
    #: 项目本身是什么（一句话定义），区别于节点级 why（为什么放这里）
    description: str = ""
    why: str = ""
    internal: bool = False


class PathModel(BaseModel):
    slug: str
    title: str
    subtitle: str = ""
    order: int
    accent: str = "accent"
    icon: str = "Compass"
    for_who: str = ""
    weeks: str = ""
    outcomes: list[str] = Field(default_factory=list)


class StageModel(BaseModel):
    id: str
    path: str
    order: int
    title: str
    goal: str = ""
    weeks: str = ""


class NodeRelated(BaseModel):
    tags: list[str] = Field(default_factory=list)
    question_kind: str | None = None


class ResourcePin(BaseModel):
    """资源锚点：把「去看这个项目」精确到「看这个文件的这一节」。

    url 必须是能直接点开的具体位置（文档页 / 仓库内文件 / 具体题号），
    只写仓库首页等于没有定位，评审时不接受。
    """

    label: str
    url: str
    note: str = ""


class NodeModel(BaseModel):
    id: str
    stage: str
    order: int
    kind: Literal["learn", "build", "drill"]
    title: str
    objective: str = ""
    deliverable: str = ""
    acceptance: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    #: 资源 id → 锚点列表。key 必须出现在 resources 中（交叉校验会拦住挂错的锚点）。
    pins: dict[str, list[ResourcePin]] = Field(default_factory=dict)
    hours: int = 0
    related: NodeRelated = Field(default_factory=NodeRelated)


class Catalog(BaseModel):
    verified_at: str = ""
    paths: list[PathModel]
    stages: list[StageModel]
    nodes: list[NodeModel]
    resources: list[ResourceModel]

    # -- 索引（构建后填充，不参与序列化）--
    resource_by_id: dict[str, ResourceModel] = Field(default_factory=dict, exclude=True)
    stages_by_path: dict[str, list[StageModel]] = Field(default_factory=dict, exclude=True)
    nodes_by_stage: dict[str, list[NodeModel]] = Field(default_factory=dict, exclude=True)
    node_by_id: dict[str, NodeModel] = Field(default_factory=dict, exclude=True)
    path_by_slug: dict[str, PathModel] = Field(default_factory=dict, exclude=True)


def _load_json(name: str) -> dict[str, Any]:
    path = DATA_DIR / name
    if not path.exists():
        raise PathsCatalogError(f"学习路径数据文件缺失: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PathsCatalogError(f"学习路径数据文件不是合法 JSON: {path.name}: {exc}") from exc


def _validate(catalog: Catalog) -> None:
    """交叉引用校验：失败即抛，不跳过坏数据（spec §7 禁静默降级）。"""
    problems: list[str] = []

    for resource in catalog.resources:
        if resource.id in catalog.resource_by_id:
            problems.append(f"资源 id 重复: {resource.id}")
        catalog.resource_by_id[resource.id] = resource

    for path in catalog.paths:
        if path.slug in catalog.path_by_slug:
            problems.append(f"路径 slug 重复: {path.slug}")
        catalog.path_by_slug[path.slug] = path

    for stage in catalog.stages:
        if stage.path not in catalog.path_by_slug:
            problems.append(f"阶段 {stage.id} 引用了不存在的路径: {stage.path}")
        catalog.stages_by_path.setdefault(stage.path, []).append(stage)

    for node in catalog.nodes:
        if node.id in catalog.node_by_id:
            problems.append(f"节点 id 重复: {node.id}")
        catalog.node_by_id[node.id] = node
        if node.stage not in {stage.id for stage in catalog.stages}:
            problems.append(f"节点 {node.id} 引用了不存在的阶段: {node.stage}")
            continue
        catalog.nodes_by_stage.setdefault(node.stage, []).append(node)
        for resource_id in node.resources:
            if resource_id not in catalog.resource_by_id:
                problems.append(f"节点 {node.id} 引用了不存在的资源: {resource_id}")
        for resource_id, pins in node.pins.items():
            if resource_id not in node.resources:
                problems.append(f"节点 {node.id} 的锚点挂在未引用的资源上: {resource_id}")
            resource = catalog.resource_by_id.get(resource_id)
            for pin in pins:
                if not pin.url.startswith(("http://", "https://", "/")):
                    problems.append(f"节点 {node.id} 的锚点 URL 不合法: {pin.url}")
                if resource is not None and pin.url.rstrip("/") == resource.url.rstrip("/"):
                    problems.append(f"节点 {node.id} 的锚点 {resource_id} 与资源首页相同，等于没有定位")
        # 标签必须能在题库筛出题：拼错或用了非 canonical 简称（如「手撕」实为
        # 「手撕代码」）会让 /bank?tag=X 深链筛出 0 题，且不会有任何报错提示。
        for tag in node.related.tags:
            if tag not in ALLOWED_NODE_TAGS:
                problems.append(
                    f"节点 {node.id} 的标签「{tag}」不在题库标签表内，"
                    f"深链会筛出 0 题（可用：{', '.join(sorted(ALLOWED_NODE_TAGS)[:8])}…）"
                )

    for stage_id, nodes in catalog.nodes_by_stage.items():
        orders = [node.order for node in nodes]
        if len(orders) != len(set(orders)):
            problems.append(f"阶段 {stage_id} 内节点 order 重复: {sorted(orders)}")

    if problems:
        raise PathsCatalogError(
            f"学习路径目录校验未通过（共 {len(problems)} 处）",
            details={"problems": problems[:50]},
        )

    for path in catalog.paths:
        catalog.stages_by_path.setdefault(path.slug, []).sort(key=lambda s: s.order)
    for nodes in catalog.nodes_by_stage.values():
        nodes.sort(key=lambda n: n.order)


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    paths_raw = _load_json("paths.json")
    resources_raw = _load_json("resources.json")
    nodes: list[dict[str, Any]] = []
    for track in ("l0", "app", "algo", "dev", "lc"):
        nodes.extend(_load_json(f"nodes_{track}.json").get("nodes", []))

    try:
        catalog = Catalog(
            verified_at=paths_raw.get("verified_at", ""),
            paths=paths_raw.get("paths", []),
            stages=paths_raw.get("stages", []),
            nodes=nodes,
            resources=resources_raw.get("items", []),
        )
    except ValidationError as exc:
        raise PathsCatalogError(f"学习路径目录字段校验失败: {exc}") from exc

    _validate(catalog)
    return catalog


def stage_out(stage: StageModel, catalog: Catalog) -> dict[str, Any]:
    nodes = catalog.nodes_by_stage.get(stage.id, [])
    return {
        "id": stage.id,
        "order": stage.order,
        "title": stage.title,
        "goal": stage.goal,
        "weeks": stage.weeks,
        "nodes": [node_out(node, catalog) for node in nodes],
    }


def node_out(node: NodeModel, catalog: Catalog) -> dict[str, Any]:
    return {
        "id": node.id,
        "order": node.order,
        "kind": node.kind,
        "title": node.title,
        "objective": node.objective,
        "deliverable": node.deliverable,
        "acceptance": list(node.acceptance),
        "hours": node.hours,
        "related": {"tags": list(node.related.tags), "question_kind": node.related.question_kind},
        "resources": [resource_with_pins(node, rid, catalog) for rid in node.resources],
    }


def resource_with_pins(node: NodeModel, resource_id: str, catalog: Catalog) -> dict[str, Any]:
    resource = catalog.resource_by_id.get(resource_id)
    if resource is None:  # 交叉校验已在加载期拦住，这里只做防御
        raise PathsCatalogError(f"节点 {node.id} 引用了不存在的资源: {resource_id}")
    payload = resource_out(resource)
    payload["pins"] = [
        {"label": pin.label, "url": pin.url, "note": pin.note} for pin in node.pins.get(resource_id, [])
    ]
    return payload


def resource_out(resource: ResourceModel) -> dict[str, Any]:
    stale = False
    if resource.pushed_at:
        try:
            pushed = date.fromisoformat(resource.pushed_at[:10])
            stale = (date.today() - pushed).days > STALE_PUSH_DAYS
        except ValueError:
            stale = False
    return {
        "id": resource.id,
        "title": resource.title,
        "description": resource.description,
        "url": resource.url,
        "kind": resource.kind,
        "priority": resource.priority,
        "repo": resource.repo,
        "stars": resource.stars,
        "license": resource.license,
        "pushed_at": resource.pushed_at,
        "stale": stale,
        "internal": resource.internal,
        "why": resource.why,
    }


def path_nodes(catalog: Catalog, slug: str) -> Iterable[NodeModel]:
    for stage in catalog.stages_by_path.get(slug, []):
        yield from catalog.nodes_by_stage.get(stage.id, [])

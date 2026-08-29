"""Markdown → AST → 章节树。

使用 mistune v3 的 AST 输出，标题/代码块信息来自节点类型与 attrs，
禁止正则抠标题（spec §7 D5）。节点形状以 references/ 中 mistune 文档为准，
tests/test_markdown_ast.py 在依赖安装后运行以固化假设。
"""

from dataclasses import dataclass, field

import mistune

Node = dict

_PARSER = mistune.create_markdown(renderer=None)


def parse_markdown(text: str) -> list[Node]:
    """返回 mistune v3 AST 顶层节点列表。"""
    result = _PARSER(text)
    if not isinstance(result, list):  # pragma: no cover - mistune 配置错误时显式失败
        raise TypeError(f"mistune AST 解析器返回了 {type(result).__name__}，期望 list")
    return result


def node_text(node: Node) -> str:
    """递归取节点文本：有 children 先拼接 children，否则取 raw。"""
    children = node.get("children")
    if isinstance(children, list) and children:
        return "".join(node_text(child) for child in children)
    raw = node.get("raw")
    return raw if isinstance(raw, str) else ""


def blocks_text(blocks: list[Node]) -> str:
    """把一组块级节点还原为可读文本（保留代码块内容与列表结构）。"""
    parts: list[str] = []
    for block in blocks:
        kind = block.get("type")
        if kind == "block_code":
            parts.append(block.get("raw", ""))
        elif kind == "list":
            for item in block.get("children", []):
                item_text = "\n".join(node_text(child) for child in item.get("children", []))
                parts.append(f"- {item_text}")
        elif kind in ("paragraph", "block_quote", "block_html", "thematic_break", "heading"):
            parts.append(node_text(block))
    return "\n\n".join(part for part in parts if part.strip())


@dataclass
class Section:
    """章节：由标题切分，嵌套用 children 表达。"""

    title: str
    level: int
    blocks: list[Node] = field(default_factory=list)
    children: list["Section"] = field(default_factory=list)

    @property
    def text(self) -> str:
        return blocks_text(self.blocks)

    def iter_self_and_descendants(self):
        yield self
        for child in self.children:
            yield from child.iter_self_and_descendants()


def split_sections(tokens: list[Node]) -> tuple[list[Node], list[Section]]:
    """按标题切分为章节树。返回 (不属于任何章节的顶层块, 章节树根列表)。"""
    roots: list[Section] = []
    stack: list[Section] = []
    preamble: list[Node] = []

    for node in tokens:
        if node.get("type") == "heading":
            level = int((node.get("attrs") or {}).get("level") or 1)
            title = node_text(node).strip()
            section = Section(title=title or "(untitled)", level=level)
            while stack and stack[-1].level >= level:
                stack.pop()
            (stack[-1].children if stack else roots).append(section)
            stack.append(section)
        else:
            if stack:
                stack[-1].blocks.append(node)
            else:
                preamble.append(node)
    return preamble, roots


def flatten_sections(roots: list[Section]) -> list[Section]:
    flat: list[Section] = []
    for root in roots:
        flat.extend(root.iter_self_and_descendants())
    return flat

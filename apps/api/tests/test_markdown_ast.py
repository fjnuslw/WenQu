"""markdown AST 解析假设的固化测试（spec §7：解析器行为由测试锁定，不靠正则）。

关键假设（由本测试锁定，mistune v3）：
- heading 的层级来自 attrs.level；
- 第一个标题之前的块属于 preamble；
- 章节树按标题层级嵌套（level-1 标题是根）；
- NFKC 会把全角标点（？）归一为半角（?），全角字母数字归一为半角。
"""

from getoffer.ingest import markdown_ast

SAMPLE = """\
这是前言，不属于任何章节。

# 顶层说明

## Transformer 基础

为什么需要位置编码？

```python
def rope(x):
    return x
```

### 变体

RoPE 与 ALiBi 的区别是什么？

- 列表项一
- 列表项二

## RAG

什么是混合检索？
"""


def _sample_sections():
    tokens = markdown_ast.parse_markdown(SAMPLE)
    _, roots = markdown_ast.split_sections(tokens)
    assert len(roots) == 1, "level-1 标题应构成唯一根"
    root = roots[0]
    assert root.title == "顶层说明"
    assert len(root.children) == 2
    return root, root.children[0], root.children[1]


def test_split_sections_builds_tree() -> None:
    root, transformer, rag = _sample_sections()
    assert transformer.title == "Transformer 基础"
    assert rag.title == "RAG"
    assert len(transformer.children) == 1
    assert transformer.children[0].title == "变体"


def test_section_text_keeps_code_and_lists() -> None:
    _, transformer, rag = _sample_sections()
    assert "为什么需要位置编码" in transformer.text
    assert "def rope(x):" in transformer.text
    variant = transformer.children[0]
    assert "RoPE 与 ALiBi 的区别是什么" in variant.text
    assert "列表项一" in variant.text
    assert "什么是混合检索" in rag.text


def test_preamble_excluded_from_sections() -> None:
    tokens = markdown_ast.parse_markdown(SAMPLE)
    preamble, roots = markdown_ast.split_sections(tokens)
    joined = markdown_ast.blocks_text(preamble)
    assert "前言" in joined
    assert "混合检索" not in joined
    assert "位置编码" not in joined


def test_nested_section_text_isolated() -> None:
    _, transformer, rag = _sample_sections()
    variant = transformer.children[0]
    assert "RoPE 与 ALiBi" in variant.text
    # 父章节文本不应包含子章节标题下的内容
    assert "列表项一" not in transformer.text
    assert "位置编码" not in variant.text

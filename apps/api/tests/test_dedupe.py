"""导入器纯函数测试：规范化与内容哈希（幂等 upsert 的基础）。"""

from getoffer.ingest.importers.markdown_repo import content_hash, normalize_text


def test_normalize_folds_whitespace_and_case() -> None:
    # 注意：NFKC 把全角 ？ 归一为半角 ?，故期望值是半角问号
    assert normalize_text("  什么是   RAG？\n ") == "什么是 rag?"


def test_normalize_nfkc_unifies_fullwidth() -> None:
    assert normalize_text("ＲＡＧ") == normalize_text("RAG")


def test_content_hash_stable_across_formatting() -> None:
    a = content_hash("什么是  RAG？")
    b = content_hash("什么是 RAG？ \n")
    assert a == b
    assert content_hash("什么是 Agent？") != a

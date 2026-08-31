"""公开汇总只按已核验的独立公司边界读取，不将预备题库算作面经。"""

import pytest

from getoffer.errors import UpstreamError
from getoffer.ingest.collect.csdn import parse_csdn_reviewed_collection


def test_csdn_public_collection_only_keeps_actual_interview_rounds():
    html = """<div id='content_views'><h2>很多家公司的汇总</h2>
    <h3>淘天【offer】：</h3><h4>介绍：</h4><p>公司介绍不应变成面试题。</p>
    <h4>一面：</h4><ul><li>怎样评估检索质量？</li></ul>
    <h4>HR面：</h4><p>为什么选择这个岗位？</p>
    <h3>字节AML【offer】：</h3><h4>预备面经：</h4><p>他人预备题不应进入本次经历。</p>
    <h4>一面：</h4><p>怎样控制模型推理延迟？</p><h4>二面：</h4><p>多模态样本如何筛选？</p></div>"""
    posts = parse_csdn_reviewed_collection(html)
    assert len(posts) == 2
    assert posts[0].url == posts[1].url
    assert "预备题" not in posts[1].content
    assert "公司介绍" not in posts[0].content
    assert "二面" in posts[1].content
    assert "多模态" not in posts[0].content


def test_csdn_collection_layout_change_requires_review():
    with pytest.raises(UpstreamError):
        parse_csdn_reviewed_collection("<div id='content_views'><h3>未审核的公司</h3></div>")

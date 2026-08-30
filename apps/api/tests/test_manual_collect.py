"""人工摘录渠道映射测试（不访问来源网站）。"""

import pytest

from getoffer.errors import ValidationFailed
from getoffer.ingest.collect.manual import get_manual_channel


@pytest.mark.parametrize(
    ("source_name", "expected_slug"),
    (
        ("小红书人工摘录", "manual-xhs"),
        ("小红书", "manual-xhs"),
        ("抖音人工摘录", "manual-douyin"),
        ("抖音", "manual-douyin"),
        ("知乎人工摘录", "manual-zhihu"),
        ("知乎", "manual-zhihu"),
        ("Reddit 人工摘录", "manual-reddit"),
        ("Reddit", "manual-reddit"),
        ("reddit", "manual-reddit"),
        ("linux.do 人工摘录", "manual-linux-do"),
        ("linux.do", "manual-linux-do"),
    ),
)
def test_get_manual_channel_maps_social_sources(source_name: str, expected_slug: str) -> None:
    assert get_manual_channel(source_name).slug == expected_slug


def test_get_manual_channel_rejects_unknown_source() -> None:
    with pytest.raises(ValidationFailed):
        get_manual_channel("未知平台")

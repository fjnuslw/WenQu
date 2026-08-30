"""种子：24 家大模型相关公司的官方校招/网申入口（2026-08 人工核验存活）。

- 只写官方域名入口；按 Company.name 精确匹配，其次按 aliases 匹配；
- 幂等：URL/备注有变化才 UPDATE，新增别名合并去重，不做删除；
- 数据来源：用户逐家核验的官方网申入口清单（详见 docs/spec.md 续十九）。
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.config import load_settings
from getoffer.db import make_engine, make_sessionmaker
from getoffer.models import Company

CAREER_LINKS: list[dict[str, str | list[str]]] = [
    {
        "name": "字节跳动",
        "url": "https://jobs.bytedance.com/campus/",
        "note": "Seed 大模型另有专项：seed.bytedance.com",
    },
    {
        "name": "阿里巴巴",
        "url": "https://campus-talent.alibaba.com/campus/gov",
        "note": "2027 届校招已开，覆盖集团多个业务",
    },
    {"name": "腾讯", "url": "https://join.qq.com/", "note": "中国区校招永久域名"},
    {
        "name": "Google",
        "url": "https://careers.google.cn/jobs/",
        "note": "无国内秋招批次，岗位滚动上线；筛 Intern / University Graduate + China",
    },
    {
        "name": "DeepSeek",
        "url": "https://talent.deepseek.com/",
        "note": "算法/研究/Agent/Infra 岗位集中在官方招聘站",
    },
    {
        "name": "微软",
        "url": "https://careers.microsoft.com/v2/global/en/students",
        "note": "学生/应届统一入口，筛 China（北京/上海/苏州等）；岗位滚动上线",
    },
    {"name": "百度", "url": "https://talent.baidu.com/jobs/list", "note": "2027 届校招已开放"},
    {
        "name": "华为",
        "url": "https://career.huawei.com/cn/campus-recruitment",
        "note": "官方唯一校招投递平台（应届/实习/留学生）",
    },
    {"name": "蚂蚁集团", "url": "https://talent.antgroup.com/campus/home", "note": ""},
    {"name": "智谱AI", "url": "https://www.zhipuai.cn/zh/joinus", "note": "页面内切换「校园招聘」"},
    {"name": "小红书", "url": "https://job.xiaohongshu.com/campus", "note": ""},
    {
        "name": "美团",
        "url": "https://career.meituan.com/web/campus",
        "note": "含北斗计划/转正实习/日常实习",
    },
    {"name": "京东", "url": "https://campus.jd.com/", "note": ""},
    {"name": "月之暗面", "url": "https://careers.kimi.com/campus", "note": "校招与社招分站"},
    {"name": "科大讯飞", "url": "https://campus.iflytek.com/", "note": "27 届秋招已启动"},
    {"name": "商汤", "url": "https://hr.sensetime.com/", "note": "首页分社招/校招入口"},
    {
        "name": "快手",
        "url": "https://zhaopin.kuaishou.cn/",
        "note": "顶部可切校园招聘/日常实习/社招",
    },
    {
        "name": "拼多多",
        "url": "https://careers.pddglobalhr.com/campus",
        "note": "2027 届校招已开放，另有实习入口",
    },
    {
        "name": "小米",
        "url": "https://hr.xiaomi.com/website/campus.html",
        "note": "另有 2027 全球顶尖人才项目",
    },
    {
        "name": "MiniMax",
        "url": "https://www.minimaxi.com/careers",
        "note": "2027 届校招开放中，另有 Top Talent/实习通道",
    },
    {
        "name": "亚马逊",
        "url": "https://www.amazon.jobs/content/zh/career-programs/university",
        "note": "实习+应届全职统一入口，筛 China；岗位滚动上线",
    },
    {
        "name": "网易",
        "url": "https://campus.163.com/",
        "note": "互娱/雷火等游戏业务另走 campus.game.163.com",
    },
    {"name": "哔哩哔哩", "url": "https://jobs.bilibili.com/campus/positions", "note": ""},
    {
        "name": "微博",
        "url": "https://career.sina.com.cn/campus-recruitment/sina/43536",
        "note": "新浪与微博共用招聘体系",
        "aliases": ["新浪", "sina"],
    },
]


async def _find_company(session: AsyncSession, entry: dict) -> Company | None:
    name = str(entry["name"])
    aliases = {str(a).lower() for a in entry.get("aliases", [])}
    rows = (await session.scalars(select(Company))).all()
    for row in rows:
        if row.name == name:
            return row
    for row in rows:
        row_aliases = {str(a).lower() for a in (row.aliases or [])}
        if name.lower() in row_aliases or (aliases & row_aliases):
            return row
    return None


async def main() -> None:
    engine = make_engine(load_settings())
    sm = make_sessionmaker(engine)
    updated = missing = unchanged = 0
    async with sm() as session:
        for entry in CAREER_LINKS:
            row = await _find_company(session, entry)  # type: ignore[arg-type]
            if row is None:
                missing += 1
                print(f"MISS  {entry['name']}: 库中没有对应公司")
                continue
            changed = []
            if row.career_url != entry["url"]:
                row.career_url = str(entry["url"])
                changed.append("url")
            new_note = str(entry["note"]) or None
            if row.career_note != new_note:
                row.career_note = new_note
                changed.append("note")
            merged_aliases = list(row.aliases or [])
            for alias in entry.get("aliases", []):
                if alias not in merged_aliases:
                    merged_aliases.append(alias)
                    if "aliases" not in changed:
                        changed.append("aliases")
            row.aliases = merged_aliases
            if changed:
                updated += 1
                print(f"SET   {row.name}: {'/'.join(changed)} -> {row.career_url}")
            else:
                unchanged += 1
                print(f"KEEP  {row.name}: 已一致")
        await session.commit()
    await engine.dispose()
    print(f"\n完成：更新 {updated}，一致 {unchanged}，缺失 {missing}")


if __name__ == "__main__":
    asyncio.run(main())

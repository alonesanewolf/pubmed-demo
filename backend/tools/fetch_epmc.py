#!/usr/bin/env python3
"""Europe PMC 采集器：生成预置数据集的另一条通道。

## 为什么有第二个采集器（实测数据说话）

| 通道 | 1000 篇耗时 | 吞吐 |
|---|---|---|
| NCBI efetch（fetch_dataset.py） | 10 次请求 × ~11.6s ≈ 2 分钟/关键词 | ~187KB/s |
| Europe PMC（本脚本） | 1 次请求 ~11.5s | ~549KB/s |

腾讯云上海 → NCBI 的国际带宽只有 ~187KB/s，5 个关键词要 10 分钟以上；
Europe PMC 单次请求可取 1000 条，全部关键词约 2 分钟。
另外用户本机直连 NCBI 的 TLS 被阻断，但 Europe PMC 通 —— 这个采集器
在服务器和本机都能跑。

Europe PMC 是 EMBL-EBI 维护的 PubMed/MEDLINE 完整镜像，PMID 一致。
预置数据的 source 字段会如实标注采集通道，不冒充 NCBI。

用法：
    python tools/fetch_epmc.py --keyword "CRISPR gene editing" --limit 1000
    python tools/fetch_epmc.py --preset          # 一次抓全部预设关键词
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.services.dataset import save_preset, slugify  # noqa: E402
from app.services.journal_metrics import (  # noqa: E402
    JournalMetricStore,
    attach_metrics,
)
from app.services.parser import Paper  # noqa: E402
from app.settings import get_settings  # noqa: E402

EPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
# SRC:MED 限定 MEDLINE 记录，保证和 PubMed 是同一批数据
SOURCE_FILTER = "AND SRC:MED"

DEFAULT_PRESETS: list[tuple[str, str]] = [
    ("CRISPR gene editing", "CRISPR 基因编辑"),
    ("gut microbiome and obesity", "肠道菌群与肥胖"),
    ("machine learning drug discovery", "机器学习辅助药物发现"),
    ("SARS-CoV-2 vaccine efficacy", "新冠疫苗有效性"),
    ("single-cell RNA sequencing", "单细胞测序"),
]


def _first_str(*values) -> str:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def record_to_paper(rec: dict) -> Paper | None:
    """Europe PMC core 记录 -> Paper。字段路径都做过容错。"""
    pmid = _first_str(rec.get("pmid"), rec.get("id"))
    if not pmid.isdigit():
        return None  # 预印本等没有 PMID 的记录不要

    jinfo = rec.get("journalInfo") or {}
    journal = jinfo.get("journal") or {}
    issn = _first_str(journal.get("issn"), rec.get("issn"))
    year = rec.get("pubYear") or jinfo.get("yearOfPublication") or jinfo.get("yearOfPublication")
    try:
        year = int(str(year)[:4])
    except (TypeError, ValueError):
        year = None

    authors = [
        a.strip()
        for a in _first_str(rec.get("authorString")).split(",")
        if a.strip()
    ]
    pubtypes = [
        str(p) for p in ((rec.get("pubTypeList") or {}).get("pubType") or [])
        if isinstance(p, str)
    ]
    mesh = [
        _first_str((m or {}).get("descriptorName"))
        for m in ((rec.get("meshHeadingList") or {}).get("meshHeading") or [])
    ]

    return Paper(
        pmid=pmid,
        title=rec.get("title") or "",
        abstract=rec.get("abstractText") or "",
        journal=_first_str(journal.get("title")),
        journal_abbrev=_first_str(journal.get("medlineAbbreviation")),
        issn=issn,
        year=year,
        volume=_first_str(journal.get("volume")),
        issue=_first_str(journal.get("issue")),
        pages=_first_str(rec.get("pageInfo")),
        doi=_first_str(rec.get("doi")),
        authors=authors,
        pubtypes=pubtypes,
        mesh_terms=[m for m in mesh if m],
        language=_first_str(rec.get("language")),
        # citations 恒为 None：契约规定 PubMed 不提供被引数，
        # Europe PMC 虽有 citedByCount，但混用两种口径会让榜单不可比
        citations=None,
    )


async def fetch_one(client: httpx.AsyncClient, keyword: str, label: str, limit: int) -> bool:
    query = f"{keyword} {SOURCE_FILTER}"
    resp = await client.get(
        f"{EPMC_BASE}/search",
        params={
            "query": query,
            "resultType": "core",
            "format": "json",
            "pageSize": min(limit, 1000),  # 官方单页上限 1000
            # 按被引次数降序抓「领域内高影响力文献」而不是默认的最新优先。
            # 实测默认排序下 1000 篇全挤在最近 3 个年份，年份分布图没有信息量；
            # 按被引排序后经典老文献+最新成果混合，年份跨度自然展开，
            # 也和 demo 的「影响力排序」叙事一致。
            "sort": "CITED desc",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    total = int(data.get("hitCount") or 0)
    results = data.get("resultList", {}).get("result") or []

    papers = [p for p in (record_to_paper(r) for r in results) if p is not None]
    if not papers:
        print(f"  [跳过] {keyword!r} 无结果")
        return False

    # 期刊表路径必须走 settings.journals_file（backend/data/journals.json）。
    # 曾经手拼成 backend/app/data/journals.json，种子表静默加载为空，
    # 整批数据指标覆盖率 0% 且不报错 —— 这类错只有看覆盖率数字才能发现。
    store = JournalMetricStore(get_settings().journals_file)
    cov = attach_metrics(papers, store)

    slug = slugify(keyword)
    save_preset(
        slug,
        keyword=keyword,
        label=label,
        total_count=total,
        papers=papers,
        source="Europe PMC API（PubMed/MEDLINE 镜像，EMBL-EBI）",
    )
    print(
        f"  [完成] {slug}  命中 {total:,} 篇 / 抓取 {len(papers)} 篇  "
        f"指标覆盖率 {cov['rate'] * 100:.1f}%"
    )
    return True


async def main() -> int:
    ap = argparse.ArgumentParser(description="经 Europe PMC 采集 PubMed 预置数据集")
    ap.add_argument("--keyword", help="单个关键词")
    ap.add_argument("--label", default="", help="显示名称")
    ap.add_argument("--limit", type=int, default=1000, help="抓取多少篇（单次请求上限 1000）")
    ap.add_argument("--preset", action="store_true", help="抓取全部预设关键词")
    args = ap.parse_args()

    if args.preset:
        jobs = list(DEFAULT_PRESETS)
    elif args.keyword:
        jobs = [(args.keyword, args.label or args.keyword)]
    else:
        ap.error("需要 --keyword 或 --preset")

    t0 = time.perf_counter()
    ok = 0
    async with httpx.AsyncClient(timeout=60) as client:
        for keyword, label in jobs:
            try:
                if await fetch_one(client, keyword, label, args.limit):
                    ok += 1
            except Exception as e:
                print(f"  [失败] {keyword}: {type(e).__name__}: {e}")

    print(f"\n== 完成 {ok}/{len(jobs)}，耗时 {time.perf_counter() - t0:.0f}s，产物在 backend/data/presets/ ==")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

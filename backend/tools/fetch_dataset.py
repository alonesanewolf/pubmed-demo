#!/usr/bin/env python3
"""本地抓取脚本：在能连 PubMed 的环境生成预置数据集。

用法：
    # Windows
    python tools\\fetch_dataset.py --keyword "CRISPR gene editing" --limit 1000
    python tools\\fetch_dataset.py --preset          # 一次抓全部预设关键词

为什么要单独一个脚本：
    境内服务器直连 eutils.ncbi.nlm.nih.gov 很可能不通（TCP 层就被拦）。
    所以「采集」和「服务」分开放 —— 采集在能连外网的机器上跑（本地、
    或开了代理的环境），产物是纯 JSON，直接 scp 到服务器即可。
    服务器只负责读 JSON 和算统计，不碰外网。

⚠️ 别把 NCBI API Key 写进命令行（会留在 shell 历史里），用环境变量：
    Windows:  set NCBI_API_KEY=xxxx
    Linux:    export NCBI_API_KEY=xxxx
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# 允许从仓库根直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.dataset import save_preset, slugify  # noqa: E402
from app.services.journal_metrics import (  # noqa: E402
    JournalMetricStore,
    attach_metrics,
)
from app.services.pubmed import PubMedClient, probe_connectivity  # noqa: E402
from app.settings import get_settings  # noqa: E402

# 预设关键词：覆盖不同学科，演示时便于展示工具的通用性
DEFAULT_PRESETS: list[tuple[str, str]] = [
    ("CRISPR gene editing", "CRISPR 基因编辑"),
    ("gut microbiome and obesity", "肠道菌群与肥胖"),
    ("machine learning drug discovery", "机器学习辅助药物发现"),
    ("SARS-CoV-2 vaccine efficacy", "新冠疫苗有效性"),
    ("single-cell RNA sequencing", "单细胞测序"),
]


async def fetch_one(keyword: str, label: str, limit: int) -> bool:
    async with PubMedClient() as client:
        print(f"  检索 {keyword!r} ...")
        total, papers = await client.search_and_fetch(keyword, limit=limit)
        if not papers:
            print(f"  [跳过] 无结果")
            return False

        # 期刊表路径走 settings.journals_file（backend/data/journals.json）。
        # 曾经手拼成 app/data/journals.json，种子表静默加载为空、
        # 整批数据指标覆盖率 0% 且不报错 —— 只有看覆盖率数字才能发现。
        store = JournalMetricStore(get_settings().journals_file)
        cov = attach_metrics(papers, store)

        slug = slugify(keyword)
        save_preset(slug, keyword=keyword, label=label, total_count=total, papers=papers)

        print(
            f"  [完成] {slug}  命中 {total:,} 篇 / 抓取 {len(papers)} 篇  "
            f"指标覆盖率 {cov['rate'] * 100:.1f}%"
        )
        return True


async def main() -> int:
    ap = argparse.ArgumentParser(description="抓取 PubMed 生成预置数据集")
    ap.add_argument("--keyword", help="单个关键词")
    ap.add_argument("--label", default="", help="显示名称")
    ap.add_argument("--limit", type=int, default=1000, help="每���取多少篇")
    ap.add_argument("--preset", action="store_true", help="抓取全部预设关键词")
    args = ap.parse_args()

    if not os.environ.get("NCBI_API_KEY"):
        print(
            "⚠️  未设置 NCBI_API_KEY 环境变量。\n"
            "    无 Key 也能跑，但限流 3 req/s 且配额更紧。\n"
            "    申请地址：https://www.ncbi.nlm.nih.gov/account/settings/\n",
            file=sys.stderr,
        )

    print("== 连通性自检 ==")
    probe = await probe_connectivity()
    print(f"  {probe}")
    if not probe.get("reachable"):
        print(
            "\n✗ 连不上 PubMed，无法采集。\n"
            "  常见原因：\n"
            "   · 当前网络无法直连 eutils.ncbi.nlm.nih.gov（国内网络常见）\n"
            "   · 如果你本地有代理，先在浏览器确认能打开 pubmed.ncbi.nlm.nih.gov，\n"
            "     然后给本脚本设上代理：\n"
            "       set HTTPS_PROXY=http://127.0.0.1:<你的代理端口>\n"
            "     或 set ALL_PROXY=socks5://127.0.0.1:<端口>\n",
            file=sys.stderr,
        )
        return 1

    print("\n== 开始抓取 ==")
    if args.preset:
        jobs = [(k, l) for k, l in DEFAULT_PRESETS]
    elif args.keyword:
        jobs = [(args.keyword, args.label or args.keyword)]
    else:
        ap.error("需要 --keyword 或 --preset")

    ok = 0
    for keyword, label in jobs:
        try:
            if await fetch_one(keyword, label, args.limit):
                ok += 1
        except Exception as e:
            print(f"  [失败] {keyword}: {type(e).__name__}: {e}")

    print(f"\n== 完成 {ok}/{len(jobs)} == 产物在 backend/data/presets/")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

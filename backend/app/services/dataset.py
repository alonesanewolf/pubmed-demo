"""数据集层：预置数据集的读写，以及统一出口。

## 为什么是「本地预生成」而不是「实时查询」

这台服务器部署在腾讯云上海（境内），**直连 eutils.ncbi.nlm.nih.gov 在 TCP 层
就可能被拦**。这不是配置问题，是网络现实。

所以架构上把数据来源做成可切换的：

- `DATA_MODE=local`  —— 只读 `data/presets/*.json`，完全不碰外网（默认）
- `DATA_MODE=remote` —— 实时查 PubMed
- `DATA_MODE=hybrid` —— 优先本地，miss 时回落远程

演示用 `local` 更稳：现场断网也能完整跑通全流程。
题目本身也要求「预置离线示例数据」，这正好是同一个需求。

## 存原始文献而不是存聚合结果

聚合结果（统计、图表）可以随时重算，存了反而会在改了聚类参数后过期。
但**摘要必须留着** —— AI 综述要用，而且摘要占了绝大部分体积。
所以 presets 里存的是 Paper 对象列表，聚合在请求时算。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..llm.deepseek import get_provider
from ..settings import get_settings
from .analysis import build_stats, build_wordcloud, cluster_directions, select_top_papers
from .journal_metrics import JournalMetricStore, attach_metrics, get_journal_store
from .parser import Paper
from .review import (
    _REVIEW_SYSTEM,
    build_review_prompt,
    count_chinese_words,
    label_clusters,
    validate_and_split,
)

_PAPER_FIELDS = (
    "pmid", "title", "abstract", "journal", "journal_abbrev", "issn", "year",
    "volume", "issue", "pages", "doi", "authors", "pubtypes", "mesh_terms",
    "language",
)


# ---------- 存取 ----------

def slugify(keyword: str) -> str:
    """把关键词转成安全的文件名 slug。

    中文关键词要保留（方便一眼认出），只清掉路径分隔符和控制字符。
    """
    s = keyword.strip().lower()
    s = re.sub(r"[^\w一-鿿]+", "-", s)
    return s.strip("-")[:60] or "untitled"


def paper_from_dict(d: dict[str, Any]) -> Paper:
    return Paper(
        pmid=str(d.get("pmid", "")),
        title=d.get("title", "") or "",
        abstract=d.get("abstract", "") or "",
        journal=d.get("journal", "") or "",
        journal_abbrev=d.get("journal_abbrev", "") or "",
        issn=d.get("issn", "") or "",
        year=d.get("year"),
        volume=d.get("volume", "") or "",
        issue=d.get("issue", "") or "",
        pages=d.get("pages", "") or "",
        doi=d.get("doi", "") or "",
        authors=list(d.get("authors") or []),
        pubtypes=list(d.get("pubtypes") or []),
        mesh_terms=list(d.get("mesh_terms") or []),
        language=d.get("language", "") or "",
        # citations 恒为 None：PubMed 不提供被引数，见 parser.py 说明
        citations=None,
    )


def save_preset(slug: str, *, keyword: str, label: str, total_count: int,
                papers: list[Paper], source: str = "NCBI E-utilities") -> Path:
    s = get_settings()
    payload = {
        "slug": slug,
        "label": label,
        "keyword": keyword,
        "total_count": total_count,
        "fetched_count": len(papers),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": source,
        "papers": [p.to_dict() for p in papers],
    }
    path = s.presets_dir / f"{slug}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


# ---------- 预置数据缓存 ----------
# 预置数据集体积大（5 个约 13MB）。不缓存时每次 /api/presets、/api/health
# 都要全量 json.loads 一遍，单 worker 下几个并发就把请求全部堵死
# （实测 6 并发 /api/health，三个 20s 超时）。
# 失效键用 (mtime_ns, size)：scp 覆盖文件后自动重载，不需要重启服务。
_PRESET_CACHE: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}


def _load_preset_cached(path: Path) -> dict[str, Any] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    sig = (st.st_mtime_ns, st.st_size)
    hit = _PRESET_CACHE.get(str(path))
    if hit is not None and hit[0] == sig:
        return hit[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    _PRESET_CACHE[str(path)] = (sig, raw)
    return raw


def load_preset(slug: str) -> dict[str, Any] | None:
    return _load_preset_cached(get_settings().presets_dir / f"{slug}.json")


def list_presets() -> list[dict[str, Any]]:
    s = get_settings()
    store = get_journal_store(s.journals_file)
    items: list[dict[str, Any]] = []
    for path in sorted(s.presets_dir.glob("*.json")):
        raw = _load_preset_cached(path)
        if raw is None:
            continue
        items.append({
            "slug": raw.get("slug", path.stem),
            "label": raw.get("label", path.stem),
            "keyword": raw.get("keyword", ""),
            "total_count": raw.get("total_count", 0),
            "fetched_count": raw.get("fetched_count", 0),
            "generated_at": raw.get("generated_at"),
            "metrics_rate": _quick_coverage(raw, store),
        })
    return items


def _quick_coverage(raw: dict[str, Any], store: JournalMetricStore | None = None) -> float:
    """列表页只要个粗略覆盖率，完整统计在详情接口里算。"""
    papers = raw.get("papers") or []
    if not papers:
        return 0.0
    if store is None:
        store = get_journal_store(get_settings().journals_file)
    hit = 0
    for d in papers:
        if store.match(
            issn=(d.get("issn") or "").strip(),
            journal=(d.get("journal") or "").strip(),
            abbrev=(d.get("journal_abbrev") or "").strip(),
        ).reason is None:
            hit += 1
    return round(hit / len(papers), 4)


# ---------- 聚合出口 ----------

def build_payload(
    slug: str,
    *,
    papers: list[Paper],
    keyword: str,
    label: str,
    total_count: int,
    generated_at: str,
    source: str,
    with_clusters: bool = True,
) -> dict[str, Any]:
    """把原始文献聚合成契约里的完整数据集响应。"""
    s = get_settings()
    store = get_journal_store(s.journals_file)

    coverage = attach_metrics(papers, store)

    known_years = [p.year for p in papers if p.year]
    year_range = {
        "min": min(known_years) if known_years else None,
        "max": max(known_years) if known_years else None,
    }

    top_papers = select_top_papers(
        papers, top_n=s.top_n_papers, recent_years=s.recent_years
    )

    clusters: list[dict[str, Any]] = []
    if with_clusters:
        clusters = cluster_directions(papers, k=6)
        for c in clusters:
            c.pop("pmids", None)  # 不要把内部聚类细节发给前端

    stats = build_stats(papers, recent_years=s.recent_years)

    return {
        "slug": slug,
        "label": label,
        "keyword": keyword,
        "total_count": total_count,
        "fetched_count": len(papers),
        "year_range": year_range,
        "generated_at": generated_at,
        "source": source,
        "metrics_coverage": {
            "total_papers": coverage["total_papers"],
            "matched": coverage["matched"],
            "rate": coverage["rate"],
            "unmatched_top": coverage["unmatched_top"],
        },
        "stats": stats,
        "wordcloud": build_wordcloud(papers, top_n=150),
        "clusters": clusters,
        "top_papers": top_papers,
        "data_quality_note": (
            f"影响因子与分区来自内置期刊指标表（{store.stats().get('metric_year') or '未标注年份'}），"
            f"当前覆盖率 {coverage['rate'] * 100:.1f}%。"
            "PubMed 官方 API 不提供影响因子与分区数据，未覆盖的期刊显示为 NA。"
            "PubMed 亦不提供被引次数，故引用数一栏均为 NA。"
        ),
    }


def get_dataset(slug: str) -> dict[str, Any] | None:
    raw = load_preset(slug)
    if raw is None:
        return None
    papers = [paper_from_dict(d) for d in (raw.get("papers") or [])]
    if not papers:
        return None
    return build_payload(
        slug,
        papers=papers,
        keyword=raw.get("keyword", ""),
        label=raw.get("label", slug),
        total_count=raw.get("total_count", len(papers)),
        generated_at=raw.get("generated_at", ""),
        source=raw.get("source", "本地预置数据集"),
    )


def get_paper(slug: str, pmid: str) -> dict[str, Any] | None:
    raw = load_preset(slug)
    if raw is None:
        return None
    for d in raw.get("papers") or []:
        if str(d.get("pmid")) == str(pmid):
            p = paper_from_dict(d)
            store = JournalMetricStore(get_settings().journals_file)
            res = store.match(issn=p.issn, journal=p.journal, abbrev=p.journal_abbrev)
            return {
                "pmid": p.pmid,
                "title": p.title,
                "abstract": p.abstract,
                "authors": p.authors,
                "journal": p.journal,
                "if": res.impact_factor,
                "jcr": res.jcr_quartile,
                "cas": res.cas_partition,
                "year": p.year,
                "doi": p.doi,
                "pubtypes": p.pubtypes,
                "mesh_terms": p.mesh_terms,
                "pubmed_url": p.pubmed_url,
            }
    return None


# ---------- AI 综述 ----------

async def generate_review(slug: str, *, max_words: int = 500) -> dict[str, Any]:
    """生成领域综述。任何失败都返回 degraded 结果，不抛异常。"""
    raw = load_preset(slug)
    if raw is None:
        return {
            "slug": slug, "degraded": True, "degraded_reason": "数据集不存在",
            "sections": [], "citations": [], "model": "", "word_count": 0,
        }

    papers = [paper_from_dict(d) for d in (raw.get("papers") or [])]
    payload = get_dataset(slug) or {}
    top_papers = payload.get("top_papers", [])
    allowed = {str(p["pmid"]) for p in top_papers} | {p.pmid for p in papers}

    # ---- 先给聚类起中文名 ----
    clusters = payload.get("clusters") or []
    if clusters:
        clusters, cluster_note = await label_clusters(clusters)
        payload["clusters"] = clusters

    provider = get_provider()
    if not provider.available:
        return {
            "slug": slug,
            "model": provider.model,
            "degraded": True,
            "degraded_reason": "未配置 DEEPSEEK_API_KEY，AI 能力不可用，已降级为纯统计模式",
            "word_count": 0,
            "sections": [],
            "citations": _citation_table(top_papers),
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    yr = payload.get("year_range") or {}
    cov = payload.get("metrics_coverage") or {}
    prompt = build_review_prompt(
        keyword=raw.get("keyword", ""),
        total_count=payload.get("total_count", 0),
        fetched_count=payload.get("fetched_count", 0),
        year_range=f"{yr.get('min', '?')} - {yr.get('max', '?')}",
        coverage=f"{cov.get('rate', 0) * 100:.1f}%",
        clusters=clusters,
        top_papers=top_papers,
        max_words=max_words,
        # 题目要求「基于文献摘要生成综述」，所以摘要必须进 prompt。
        # 从 preset 的原始记录里取，不进 dataset payload（契约不动，体积不涨）。
        abstracts={p.pmid: p.abstract for p in papers if p.abstract},
    )

    # 输出预算走配置（LLM_REVIEW_MAX_TOKENS，默认 8192），不写死在调用处。
    # 早期版本写死 4096，且那条「4096 稳定产出」的结论是在输入很小的时候测的 ——
    # prompt 规模涨到 ~4.5 万 token 之后，推理阶段照样把 4096 烧光（线上实测降级）。
    # 现在两件事一起做：压缩输入（见 review.py 的 _MAX_PAPERS_IN_PROMPT/_ABSTRACT_CHARS）
    # + 把预算放大一档并留出配置口。
    result = await provider.complete(
        prompt, system=_REVIEW_SYSTEM, max_tokens=get_settings().llm_review_max_tokens
    )

    if not result.ok:
        return {
            "slug": slug,
            "model": provider.model,
            "degraded": True,
            "degraded_reason": f"AI 服务暂不可用（{result.reason}），已降级为纯统计模式",
            "word_count": 0,
            "sections": [],
            "citations": _citation_table(top_papers),
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    # ---- 幻觉防护：白名单校验后再分点 ----
    sections, hallucinated = validate_and_split(result.text, allowed)

    return {
        "slug": slug,
        "model": result.model,
        "degraded": False,
        "degraded_reason": None,
        "hallucinated_filtered": hallucinated,
        "word_count": count_chinese_words(result.text),
        "sections": sections,
        "citations": _citation_table(top_papers),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "cost_estimate_cny": result.cost_estimate_cny,
    }


def _citation_table(top_papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """引用表：给前端把 PMID 角标映射回可读的文献信息。"""
    return [
        {
            "pmid": p["pmid"], "rank": p["rank"], "title": p["title"],
            "journal": p["journal"], "if": p["if"],
        }
        for p in top_papers[:100]
    ]

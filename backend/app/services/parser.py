"""PubMed XML (efetch) 解析器。

几个必须处理的现实问题（都是 NCBI 返回格式里的真实坑）：

1. `<ArticleTitle>` 里会混 HTML 标签（`<i>`, `<sub>`, `<sup>`），必须剥掉，
   否则前端会显示成字面量 ``<i>``。
2. `<PubDate>` 里可能没有 `<Year>`，只有 `<MedlineDate>` 形如 ``2024 Jan-Feb``，
   直接取 Year 会拿到空值。
3. 引用次数（被引数）**E-utilities 根本不返回**。这不是我们没做，是数据源没有。
   所以 citations 一律为 None，页面上要显式说明，不能用 0 冒充。
4. 期刊名有多个来源（`<Journal><Title>` 全称 / `<ISOAbbreviation>` 缩写 /
   `<MedlineTA>`），做指标表匹配时要按优先级依次尝试。

解析只用标准库 xml.etree.ElementTree，不引 lxml —— 2G 内存的机器上少一个
带 C 扩展的依赖是划算的。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable


# ---------- 工具函数 ----------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_MEDLINE_DATE_RE = re.compile(r"(\d{4})")


def _text(node: ET.Element | None) -> str:
    """取节点的全部文字，自动剥掉内嵌 HTML 标签并压缩空白。"""
    if node is None:
        return ""
    raw = "".join(node.itertext())
    cleaned = _TAG_RE.sub("", raw)
    return _WS_RE.sub(" ", cleaned).strip()


def _find_text(parent: ET.Element | None, path: str) -> str:
    if parent is None:
        return ""
    return _text(parent.find(path))


def _parse_year(pubdate: ET.Element | None) -> int | None:
    """从 <PubDate> 取年份；没有 <Year> 时退回 <MedlineDate> 的前四位数字。"""
    if pubdate is None:
        return None
    year_el = pubdate.find("Year")
    if year_el is not None and (year_el.text or "").strip().isdigit():
        return int(year_el.text.strip())
    medline_date = _text(pubdate.find("MedlineDate"))
    m = _MEDLINE_DATE_RE.search(medline_date)
    return int(m.group(1)) if m else None


# ---------- 数据结构 ----------


@dataclass(slots=True)
class Paper:
    """一篇文献的规范化记录。"""

    pmid: str
    title: str
    abstract: str = ""
    journal: str = ""
    journal_abbrev: str = ""
    issn: str = ""
    year: int | None = None
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    authors: list[str] = field(default_factory=list)
    pubtypes: list[str] = field(default_factory=list)
    mesh_terms: list[str] = field(default_factory=list)
    language: str = ""

    # ⚠️ PubMed E-utilities 不返回被引次数，只能是 None。
    #    任何地方都不许用 0 代替 —— 0 会被读成「被引 0 次」，是错误信息。
    citations: int | None = None

    # 解析后由 journal_metrics 回填
    impact_factor: float | None = None
    jcr_quartile: str | None = None
    cas_partition: str | None = None
    metrics_reason: str | None = None  # 未匹配时的原因说明

    @property
    def pubmed_url(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["pubmed_url"] = self.pubmed_url
        return d


# ---------- 主解析入口 ----------


def parse_pubmed_xml(xml_text: str) -> list[Paper]:
    """解析 efetch 返回的 PubmedArticleSet / PubmedBookArticleSet XML。"""
    # XML 声明里可能带 BOM 或前导空白，统一清掉，否则 ET 会直接抛 ParseError
    xml_text = xml_text.lstrip("﻿ \t\r\n")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"PubMed 返回的 XML 无法解析：{e}") from e

    papers: list[Paper] = []

    for node in root.iter("PubmedArticle"):
        p = _parse_pubmed_article(node)
        if p is not None:
            papers.append(p)

    # efetch 在 rettype=docsum 或某些综述场景下会返回 PubmedBookArticle
    for node in root.iter("PubmedBookArticle"):
        p = _parse_pubmed_book(node)
        if p is not None:
            papers.append(p)

    return papers


def _parse_pubmed_article(node: ET.Element) -> Paper | None:
    medline = node.find("MedlineCitation")
    if medline is None:
        return None

    pmid = _find_text(medline, "PMID")
    if not pmid:
        return None

    article = medline.find("Article")
    journal_el = article.find("Journal") if article is not None else None
    issue_el = journal_el.find("JournalIssue") if journal_el is not None else None

    # ---- 期刊标识：全称 / 缩写 / ISSN，按匹配优先级收集 ----
    journal_full = _find_text(journal_el, "Title")
    journal_abbrev = _find_text(journal_el, "ISOAbbreviation")
    medline_ta = _find_text(medline, "MedlineJournalInfo/MedlineTA")

    issn = ""
    if journal_el is not None:
        for issn_el in journal_el.findall("ISSN"):
            # 电子版 ISSN 优先
            if issn_el.get("IssnType") == "Electronic" and (issn_el.text or "").strip():
                issn = issn_el.text.strip()
                break
        if not issn:
            first = journal_el.find("ISSN")
            if first is not None:
                issn = (first.text or "").strip()

    # 期刊名兜底链：全称 → 缩写 → MedlineTA
    journal = journal_full or journal_abbrev or medline_ta

    # ---- 标题（内含 HTML 标签，已由 _text 剥掉）----
    title = _find_text(article, "ArticleTitle")

    # ---- 摘要：可能是无标签整段，也可能是带 Label 的结构化摘要 ----
    # 结构化摘要（BACKGROUND / RESULTS / METHODS / CONCLUSIONS）是 PubMed 的常见格式，
    # 标签本身就是语义分隔，**必须保留** —— 全部剥掉会把这几段糊成一坨，
    # 前端既没法分段展示，做综述的 LLM 也丢掉了结构信息。
    abstract_parts: list[str] = []
    abstract_el = article.find("Abstract") if article is not None else None
    if abstract_el is not None:
        for at in abstract_el.findall("AbstractText"):
            label = (at.get("Label") or "").strip()
            body = _text(at)
            if not body:
                continue
            abstract_parts.append(f"{label}: {body}" if label else body)
    abstract = " ".join(abstract_parts).strip()

    # ---- 作者：LastName + Initials，控制在 10 个以内 ----
    authors: list[str] = []
    author_list = article.find("AuthorList") if article is not None else None
    if author_list is not None:
        for a in author_list.findall("Author"):
            last = _find_text(a, "LastName")
            initials = _find_text(a, "Initials")
            collective = _find_text(a, "CollectiveName")
            if last:
                authors.append(f"{last} {initials}".strip())
            elif collective:
                authors.append(collective)
            if len(authors) >= 10:
                break

    # ---- 文献类型 ----
    pubtypes: list[str] = []
    ptl = article.find("PublicationTypeList") if article is not None else None
    if ptl is not None:
        pubtypes = [_text(pt) for pt in ptl.findall("PublicationType") if _text(pt)]

    # ---- MeSH 主题词 ----
    mesh_terms: list[str] = []
    mhl = medline.find("MeshHeadingList")
    if mhl is not None:
        for mh in mhl.findall("MeshHeading"):
            dn = mh.find("DescriptorName")
            if dn is not None:
                t = _text(dn)
                if t:
                    mesh_terms.append(t)

    # ---- DOI / 其他 ArticleId ----
    doi = ""
    article_id_list = node.find("PubmedData/ArticleIdList")
    if article_id_list is not None:
        for aid in article_id_list.findall("ArticleId"):
            if aid.get("IdType") == "doi":
                doi = (aid.text or "").strip()
                break

    return Paper(
        pmid=pmid,
        title=title,
        abstract=abstract,
        journal=journal,
        journal_abbrev=journal_abbrev or medline_ta,
        issn=issn,
        year=_parse_year(issue_el.find("PubDate") if issue_el is not None else None),
        volume=_find_text(issue_el, "Volume") if issue_el is not None else "",
        issue=_find_text(issue_el, "Issue") if issue_el is not None else "",
        pages=_find_text(article, "Pagination/MedlinePgn"),
        doi=doi,
        authors=authors,
        pubtypes=pubtypes,
        mesh_terms=mesh_terms[:12],
        language=_find_text(article, "Language"),
        # citations 保持 None —— PubMed 不提供被引数
    )


def _parse_pubmed_book(node: ET.Element) -> Paper | None:
    """BookDoc 解析。书籍章节没有影响因子概念，但仍要能进统计。"""
    book = node.find("BookDocument")
    pmid = _find_text(book, "PMID")
    if not pmid:
        return None

    journal = _find_text(book, "Book/BookTitle") or "Book Chapter"
    title = _find_text(book, "ArticleTitle") or _find_text(book, "Book/BookTitle")

    authors: list[str] = []
    author_list = book.find("AuthorList")
    if author_list is not None:
        for a in author_list.findall("Author"):
            last = _find_text(a, "LastName")
            if last:
                authors.append(last)

    return Paper(
        pmid=pmid,
        title=title,
        abstract=_find_text(book, "Abstract"),
        journal=journal,
        year=_parse_year(book.find("PubDate")),
        authors=authors[:10],
        pubtypes=["Book Chapter"],
    )


def parse_summary_json(payload: dict[str, Any]) -> list[Paper]:
    """解析 esummary 的 JSON 返回。

    用途：esummary 比 efetch 轻得多，适合只补齐「期刊全称」时用，
    避免为了一个刊名去拉整篇 XML。
    注意 esummary **没有** 摘要，也没有 MeSH。
    """
    result = payload.get("result")
    if not isinstance(result, dict):
        return []

    papers: list[Paper] = []
    for uid, item in result.items():
        if uid == "uids" or not isinstance(item, dict):
            continue
        articles = item.get("articleids") or []
        doi = ""
        for aid in articles:
            if aid.get("idtype") == "doi":
                doi = aid.get("value", "")
                break

        pubtypes = [p for p in (item.get("pubtype") or []) if p]

        papers.append(
            Paper(
                pmid=str(uid),
                title=(item.get("title") or "").strip(),
                journal=(item.get("source") or "").strip(),
                journal_abbrev=(item.get("source") or "").strip(),
                issn=(item.get("issn") or "").strip(),
                year=_year_from_esummary_date(item.get("pubdate") or ""),
                volume=item.get("volume") or "",
                issue=item.get("issue") or "",
                pages=item.get("pages") or "",
                doi=doi,
                authors=(item.get("authors") or [])[:10],
                pubtypes=pubtypes,
                language=(item.get("lang") or [""])[0] if item.get("lang") else "",
            )
        )
    return papers


def _year_from_esummary_date(date_str: str) -> int | None:
    """esummary 的 pubdate 形如 '2024 Jan-Feb' 或 '2024'。"""
    m = _MEDLINE_DATE_RE.search(date_str or "")
    return int(m.group(1)) if m else None


def dedupe_by_pmid(papers: Iterable[Paper]) -> list[Paper]:
    """同一 PMID 可能因分批抓取重复出现，保留第一条。"""
    seen: set[str] = set()
    out: list[Paper] = []
    for p in papers:
        if p.pmid in seen:
            continue
        seen.add(p.pmid)
        out.append(p)
    return out

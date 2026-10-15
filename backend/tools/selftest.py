#!/usr/bin/env python3
"""离线自测：不联网验证整条数据链路。

为什么需要它：采集要连 PubMed，但**服务器连不上 PubMed**，
所以必须有一份能在纯离线环境下证明代码是对的测试。
面试时这也是加分项 —— 你能说清楚「我怎么保证解析逻辑是对的」。

用法：  python tools/selftest.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm.base import extract_pmids, validate_citations  # noqa: E402
from app.services.analysis import (  # noqa: E402
    build_stats,
    build_wordcloud,
    cluster_directions,
    select_top_papers,
)
from app.services.journal_metrics import JournalMetricStore, attach_metrics  # noqa: E402
from app.services.parser import Paper, dedupe_by_pmid, parse_pubmed_xml  # noqa: E402

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  {PASS}  {name}")
    else:
        print(f"  {FAIL}  {name}" + (f"  -> {detail}" if detail else ""))
        _failures.append(name)


# ---------- 测试数据：贴近真实 PubMed XML 结构 ----------

SAMPLE_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation Status="MEDLINE">
      <PMID Version="1">38123456</PMID>
      <Article PubModel="Print-Electronic">
        <Journal>
          <ISSN IssnType="Electronic">1089-159X</ISSN>
          <JournalIssue CitedMedium="Internet">
            <Volume>25</Volume><Issue>4</Issue>
            <PubDate><Year>2024</Year><Month>Apr</Month></PubDate>
          </JournalIssue>
          <Title>Nature Medicine</Title>
          <ISOAbbreviation>Nat Med</ISOAbbreviation>
        </Journal>
        <ArticleTitle>Base editing <i>in vivo</i> corrects a pathogenic mutation.</ArticleTitle>
        <Pagination><MedlinePgn>401-410</MedlinePgn></Pagination>
        <ELocationID EIdType="doi" ValidYN="Y">10.1038/s41591-024-00000-0</ELocationID>
        <Abstract>
          <AbstractText Label="BACKGROUND" NlmCategory="BACKGROUND">Base editing offers a
            strategy for precise nucleotide conversion without double-strand breaks.</AbstractText>
          <AbstractText Label="RESULTS" NlmCategory="RESULTS">We demonstrate efficient
            correction in a mouse model of sickle cell disease.</AbstractText>
        </Abstract>
        <AuthorList CompleteYN="Y">
          <Author ValidYN="Y"><LastName>Zhang</LastName><ForeName>Wei</ForeName><Initials>W</Initials></Author>
          <Author ValidYN="Y"><LastName>Li</LastName><ForeName>Hua</ForeName><Initials>H</Initials></Author>
        </AuthorList>
        <Language>eng</Language>
        <PublicationTypeList>
          <PublicationType UI="D016428">Journal Article</PublicationType>
          <PublicationType UI="D016430">Research Support</PublicationType>
        </PublicationTypeList>
      </Article>
      <MedlineJournalInfo><MedlineTA>Nat Med</MedlineTA></MedlineJournalInfo>
      <!-- MeSH 是 MedlineCitation 的直接子节点，与 Article 平级，不在 Article 里面 -->
      <MeshHeadingList>
        <MeshHeading><DescriptorName UI="D003081" MajorTopicYN="N">CRISPR-Cas Systems</DescriptorName></MeshHeading>
        <MeshHeading><DescriptorName UI="D016428" MajorTopicYN="N">Base Editing</DescriptorName></MeshHeading>
      </MeshHeadingList>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">38123456</ArticleId>
        <ArticleId IdType="doi">10.1038/s41591-024-00000-0</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation Status="MEDLINE">
      <PMID Version="1">35123457</PMID>
      <Article PubModel="Print">
        <Journal>
          <ISSN IssnType="Print">1932-6203</ISSN>
          <JournalIssue CitedMedium="Print">
            <PubDate><MedlineDate>2018 Nov-Dec</MedlineDate></PubDate>
          </JournalIssue>
          <Title>PLoS ONE</Title>
        </Journal>
        <ArticleTitle>Genome wide screening of CRISPR off target sites.</ArticleTitle>
        <Abstract>Whole genome sequencing was used to identify off-target effects.</Abstract>
        <AuthorList><Author><LastName>Smith</LastName><Initials>J</Initials></Author></AuthorList>
        <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


def test_parser() -> list[Paper]:
    print("\n[1] PubMed XML 解析")
    papers = parse_pubmed_xml(SAMPLE_XML)
    check("解析出 2 篇", len(papers) == 2, f"实际 {len(papers)}")
    if len(papers) < 2:
        return []

    a, b = papers[0], papers[1]

    check("PMID 正确", a.pmid == "38123456", a.pmid)
    check("剥离标题内嵌 HTML 标签",
          "<i>" not in a.title and "in vivo" in a.title, a.title)
    check("结构化摘要保留标签但去噪",
          "BACKGROUND: " in a.abstract and "RESULTS" in a.abstract, a.abstract[:60])
    check("电子版 ISSN 优先", a.issn == "1089-159X", a.issn)
    check("DOI 提取", a.doi == "10.1038/s41591-024-00000-0", a.doi)
    check("作者格式", a.authors == ["Zhang W", "Li H"], str(a.authors))
    check("文献类型", "Journal Article" in a.pubtypes, str(a.pubtypes))
    check("MeSH 词", "CRISPR-Cas Systems" in a.mesh_terms, str(a.mesh_terms))

    check("MedlineDate 回退取年份", b.year == 2018, str(b.year))
    check("无 DOI 时为空串", b.doi == "", repr(b.doi))
    check("引用数恒为 None（PubMed 不提供）", a.citations is None)

    d = dedupe_by_pmid(papers + [papers[0]])
    check("PMID 去重", len(d) == 2, f"实际 {len(d)}")
    return papers


def test_journal_matching() -> None:
    print("\n[2] 期刊指标匹配")
    path = Path(__file__).resolve().parent.parent / "data" / "journals.json"
    store = JournalMetricStore(path)

    r1 = store.match(issn="1089-159X", journal="Nature Medicine", abbrev="Nat Med")
    check("ISSN 精确匹配", r1.reason is None and r1.impact_factor is not None, str(r1))

    # 归一化匹配：大小写、标点、"The" 前缀差异
    r2 = store.match(journal="PLOS ONE.")
    r3 = store.match(journal="plos one")
    check("刊名归一化（大小写/标点）", r2.impact_factor == r3.impact_factor, f"{r2} vs {r3}")
    check("未命中归因为 not_in_seed_table",
          store.match(journal="Journal of Nonexistent Field").reason == "not_in_seed_table")

    r4 = store.match()
    check("无标识归因为 no_identifier", r4.reason == "no_identifier", str(r4))


def test_analysis(papers: list[Paper]) -> list[Paper]:
    print("\n[3] 统计分析")
    store = JournalMetricStore(Path(__file__).resolve().parent.parent / "data" / "journals.json")

    # 造一批数据让统计有意义
    rng = random.Random(42)
    venues = [
        ("Nature Medicine", "1089-159X", 50.0, "Q1", "1区"),
        ("The Lancet", "0140-6736", 77.7, "Q1", "1区"),
        ("PLoS ONE", "1932-6203", 2.3, "Q2", "3区"),
        ("Nature Medicine", "1089-159X", 50.0, "Q1", "1区"),
        ("Some Unindexed Journal", "1234-5678", None, None, None),
    ]
    topics = [
        ("gene editing", "base editing and prime editing correct variants"),
        ("immunotherapy", "checkpoint blockade antibody response in patients"),
        ("metagenomics", "microbiome sequencing reveals bacterial diversity"),
    ]

    synth: list[Paper] = []
    for i in range(150):
        name, issn, ifv, q, cas = venues[i % len(venues)]
        topic, text = topics[i % len(topics)]
        synth.append(Paper(
            pmid=str(20000000 + i),
            title=f"{topic} study number {i} reporting clinical outcomes",
            abstract=f"Background: we investigated {text}. Results: significant improvement "
                     f"was observed across patient groups in this randomized analysis.",
            journal=name, issn=issn, year=2019 + (i % 6),
            pubtypes=["Journal Article"],
            impact_factor=ifv, jcr_quartile=q, cas_partition=cas,
        ))

    cov = attach_metrics(synth, store)
    check("覆盖率计算", 0 < cov["rate"] < 1, f"rate={cov['rate']}")
    check("未匹配期刊被归类", len(cov["unmatched_top"]) > 0)

    stats = build_stats(synth)
    check("年份分布非空", len(stats["by_year"]) > 0)
    check("期刊榜存在", len(stats["by_journal"]) > 0)
    bands = {b["key"] for b in stats["by_if_band"]}
    check("无 IF 的进「无IF/未收录」档而非 IF=0", "无IF/未收录" in bands, str(bands))

    wc = build_wordcloud(synth, top_n=50)
    check("词云非空", len(wc) > 10, f"{len(wc)} 词")
    check("停用词被过滤",
          not any(w["word"] in ("the", "and", "patient", "study") for w in wc))

    top = select_top_papers(synth, top_n=20, recent_years=5)
    check("Top 榜排序正确",
          all(top[i]["if"] >= top[i + 1]["if"] for i in range(len(top) - 1)
              if top[i]["if"] is not None and top[i + 1]["if"] is not None))
    check("无 IF 的排末尾且为 null",
          all(p["if"] is None for p in top if p["rank"] > 0 and p["if"] is None))

    print("\n[4] 方向聚类")
    clusters = cluster_directions(synth, k=4)
    check("聚出多个簇", len(clusters) >= 2, f"{len(clusters)} 簇")
    check("簇按大小降序",
          all(clusters[i]["size"] >= clusters[i + 1]["size"] for i in range(len(clusters) - 1)))
    check("每簇有关键词",
          all(len(c["keywords"]) > 0 for c in clusters))
    total = sum(c["size"] for c in clusters)
    check("簇覆盖全部文献", total == len(synth), f"{total} vs {len(synth)}")
    return synth


def test_citation_guard() -> None:
    print("\n[5] PMID 幻觉防护")
    allowed = {"38123456", "35123457"}

    fake = "研究显示基因编辑有效[38123456]，另有假引用[99999999]和[12345678]。"
    cleaned, valid, bad = validate_citations(fake, allowed)
    check("编造的 PMID 被剔除", set(bad) == {"99999999", "12345678"}, str(bad))
    check("合法引用保留", valid == ["38123456"], str(valid))
    check("正文已清洗", "99999999" not in cleaned and "12345678" not in cleaned)

    multi = "结论一[38123456,35123457]与结论二[38123456]。"
    cleaned2, valid2, bad2 = validate_citations(multi, allowed)
    check("多引用保留", cleaned2.count("38123456") == 2, cleaned2)
    check("无幻觉 PMID", bad2 == [], str(bad2))

    allfake = "纯幻觉内容[55555555]。"
    _, _, bad3 = validate_citations(allfake, allowed)
    check("整段幻觉被标记", bad3 == ["55555555"], str(bad3))

    check("抽取多种写法", extract_pmids("a[38123456] b[35123457,38123456]") ==
          ["38123456", "35123457"])


def main() -> int:
    print("=" * 58)
    print(" PubMed Demo 后端离线自测")
    print("=" * 58)
    papers = test_parser()
    test_journal_matching()
    synth = test_analysis(papers)
    test_citation_guard()

    print("\n" + "=" * 58)
    if _failures:
        print(f" {FAIL}  {len(_failures)} 项失败：")
        for f in _failures:
            print(f"    - {f}")
        return 1
    print(f" {PASS}  全部通过（合成样本 {len(synth)} 篇）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

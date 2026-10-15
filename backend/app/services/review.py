"""AI 能力编排：研究方向命名 + 领域综述生成。

## 这一层要体现的「对 AI 工具的思考」

1. **任务切分**：数据抓取、指标计算、排序、聚类、图表 —— 全部**不交给 AI**，
   它们必须可复现、可审计。AI 只做两件它真正擅长且无法用规则替代的事：
   把聚类结果翻译成人话（中文方向名）、把 100 篇摘要压缩成一篇综述。

2. **幻觉防护（核心）**：模型很爱编造看起来合理的 8 位 PMID。
   所以综述正文里的每一处引用都必须过后端白名单校验，
   不在本次检索结果里的编号一律剔除，并在响应里如实告诉用户剔了几个。
   ⚠️ 这一步必须在服务端做 —— 前端校验等于没有校验。

3. **成本控制**：摘要按字数截断（每篇 600 字符）、Top-N 截断（100 篇）、
同 slug 结果缓存。按 v4-flash 的价格，一次完整综述约 ¥0.04~0.05，
缓存命中率高的场景近乎免费。

4. **失败兜底**：任一环节失败都返回降级结果，页面其余部分照常工作。
   降级不是错误，HTTP 状态码仍是 200。
"""

from __future__ import annotations

import re
from typing import Any

from ..llm.base import LLMProvider, LLMResult, validate_citations
from ..llm.deepseek import get_provider

# ---------- Prompt ----------

_CLUSTER_SYSTEM = (
    "你是一名医学科研方向分析助手。你的任务是根据给定的英文文献聚类，"
    "为每个研究簇起一个**简洁准确的中文方向名称**。"
    "要求：每��名称 4-12 个汉字，不要加书名号，不要加解释。"
)

_CLUSTER_USER = """以下是某个 PubMed 关键词检索结果的自动聚类结果。请为每个簇生成中文名称。

{clusters}

严格只输出 JSON，格式：{{"labels": ["方向一", "方向二", ...]}}
数组长度必须与簇数一致，顺序对应。禁止输出任何其他文字。"""


_REVIEW_SYSTEM = (
    "你是一名医学科研综述撰写助手。你只能依据用户提供的真实文献摘要撰写综述。"
    "\n\n"
    "硬性规则：\n"
    "1. 严禁编造任何未在输入中出现的文献编号、作者、数据或结论。\n"
    "2. 每一句实质性论述后必须用方括号标注依据的 PMID 编号，"
    "可多个，用英文逗号分隔，例：[31234567,29876543]。\n"
    "3. 禁止出现输入中没有的 PMID。宁可少标，不要标错。\n"
    "4. 只输出中文。"
)

_REVIEW_USER = """请根据以下 PubMed 检索统计与高影响力文献，撰写一份该领域的中文综述报告。

## 检索概况
- 检索关键词：{keyword}
- PubMed 返回总量：{total_count} 篇
- 本次分析样本量：{fetched_count} 篇（近 5 年高影响力文献 {top_n} 篇）
- 年份跨度：{year_range}
- 期刊指标覆盖率：{coverage}

## 研究方向分布（由 TF-IDF + KMeans 自动聚类得到）
{direction_hint}

## 高影响力文献（按影响因子降序，含截断摘要）
{papers}

## 输出要求（硬性，逐条遵守）
1. 总字数 {max_words} 字左右，**不得少于 {min_words} 字**
2. 严格分 5 点，每点格式为「一、标题」单独一行，下一行起是正文
   五点依次为：研究背景与热点 / 主要技术路线 / 关键影响因素 / 当前瓶颈与挑战 / 未来趋势
3. 每点正文 80-120 字，结尾用 [PMID] 标注 1-3 篇支撑文献，例：[31234567]
4. 只依据上述文献撰写，不要引入外部知识，不要编造文献编号

现在开始撰写。"""


# ---------- 簇命名 ----------


async def label_clusters(
    clusters: list[dict[str, Any]], provider: LLMProvider | None = None
) -> tuple[list[dict[str, Any]], str | None]:
    """给聚类结果起中文名。失败时退回「方向一/二/三」，不影响其他功能。"""
    if not clusters:
        return [], None

    provider = provider or get_provider()
    if not provider.available:
        return _fallback_labels(clusters), "未配置 LLM，使用默认方向名"

    lines = []
    for c in clusters:
        kw = ", ".join(c.get("keywords", [])[:5])
        lines.append(
            f"簇 {c['id']}（{c['size']} 篇）\n"
            f"  高频词：{kw}\n"
            f"  代表性标题：{c.get('sample_titles', [''])[0] if c.get('sample_titles') else '(无)'}"
        )

    result = await provider.complete(
        _CLUSTER_USER.format(clusters="\n\n".join(lines)),
        system=_CLUSTER_SYSTEM,
        # 512 对推理模型太紧：实测推理本身就要 ~190 token，余量只够输出，
        # 一旦聚类描述长一点 content 就会被截空，标签全回落。放到 2048。
        max_tokens=2048,
    )

    if not result.ok:
        return _fallback_labels(clusters), result.reason

    labels = _parse_json_labels(result.text, expected=len(clusters))
    if labels is None:
        return _fallback_labels(clusters), "模型输出不是合法 JSON，使用默认方向名"

    for c, label in zip(clusters, labels):
        c["label"] = label
        c["label_source"] = "llm"
    return clusters, None


def _fallback_labels(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cn = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    for c in clusters:
        c["label"] = f"方向{cn[c['id']] if c['id'] < len(cn) else c['id'] + 1}"
        c["label_source"] = "fallback"
    return clusters


def _parse_json_labels(text: str, *, expected: int) -> list[str] | None:
    """从模型输出里抠出 JSON 数组。

    模型常常在 JSON 外面裹一层 ```json 或加一句「好的」，所以用括号配平扫描，
    比正则匹配 ```json 块更耐得住脏输出。
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                blob = text[start : i + 1]
                break
    else:
        return None

    import json

    try:
        data = json.loads(blob)
        labels = data.get("labels")
    except Exception:
        return None

    if not isinstance(labels, list) or len(labels) != expected:
        return None
    return [str(x).strip()[:20] for x in labels]


# ---------- 综述生成 ----------

# 单篇摘要送进模型时的截断长度（字符）。
# 100 篇 × 截断是成本控制的主要手段：原始摘要平均 1200 字符，截到 600 大约省一半。
_ABSTRACT_CHARS = 600
_MAX_PAPERS_IN_PROMPT = 100


def build_review_prompt(
    *,
    keyword: str,
    total_count: int,
    fetched_count: int,
    year_range: str,
    coverage: str,
    clusters: list[dict[str, Any]],
    top_papers: list[dict[str, Any]],
    max_words: int = 500,
    abstracts: dict[str, str] | None = None,
    min_words: int = 400,
) -> str:
    """组装综述 prompt。

    abstracts: pmid -> 摘要。题目要求「基于文献摘要生成综述」，
    所以摘要必须进 prompt（按 _ABSTRACT_CHARS 截断控制成本）。
    从调用方传入而不是塞进 top_papers，是为了不改 dataset 的接口契约。
    """
    direction_lines = []
    for c in clusters[:8]:
        kw = ", ".join(c.get("keywords", [])[:4])
        label = c.get("label") or f"方向{c['id'] + 1}"
        direction_lines.append(f"- {label}（{c['size']} 篇）：{kw}")

    abstract_map = abstracts or {}
    paper_lines = []
    for p in top_papers[:_MAX_PAPERS_IN_PROMPT]:
        journal = p.get("journal") or "?"
        if_ = p.get("if")
        if_txt = f"IF={if_}" if if_ is not None else "IF=NA"
        year = p.get("year") or "?"
        line = f"[{p['pmid']}] ({year}, {journal}, {if_txt}) {p.get('title', '')}"
        abstract = (abstract_map.get(str(p.get("pmid"))) or "").strip()
        if abstract:
            line += f" 摘要：{abstract[:_ABSTRACT_CHARS]}"
        paper_lines.append(line)

    return _REVIEW_USER.format(
        keyword=keyword,
        total_count=total_count,
        fetched_count=fetched_count,
        year_range=year_range,
        coverage=coverage,
        direction_hint="\n".join(direction_lines) or "（未生成聚类）",
        papers="\n".join(paper_lines) or "（无）",
        max_words=max_words,
        min_words=min_words,
        top_n=len(top_papers),
    )


def validate_and_split(text: str, allowed_pmids: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """分点 + 逐点白名单校验。返回 (要点列表, 被剔除的幻觉 PMID)。

    这是幻觉防护真正落地的地方：模型输出先整体过一遍白名单，
    把编造的引用从正文里删掉，再按分点拆开。
    """
    cleaned, _valid, hallucinated = validate_citations(text, allowed_pmids)

    head_re = re.compile(r"^\s*(?:[一二三四五六七八九十]+、|\d+[.、)]|[-*•])\s*(.+?)\s*$")
    parts: list[dict[str, Any]] = []
    title: str | None = None
    body: list[str] = []

    for raw in cleaned.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = head_re.match(line)
        if m:
            if title is not None:
                parts.append({"point": title, "text": " ".join(body).strip()})
            title = m.group(1).strip()
            body = []
        elif title is not None:
            body.append(line)
        else:
            title = "综述"
            body = [line]

    if title is not None:
        parts.append({"point": title, "text": " ".join(body).strip()})

    if not parts:
        parts = [{"point": "综述", "text": cleaned.strip()}]

    for p in parts:
        p["text"] = re.sub(r"\s{2,}", " ", p["text"]).strip()
        p["citations"] = [x for x in re.findall(r"\[([\d,\s]+)\]", p["text"])]
        p["citations"] = [
            n for block in p["citations"] for n in re.findall(r"\d{6,9}", block)
        ]
        # 校验后把引用整理成统一格式
        if p["citations"]:
            p["text"] = re.sub(
                r"\[([\d,\s]+)\]", "[" + ",".join(p["citations"]) + "]", p["text"]
            )
    return parts, hallucinated


def count_chinese_words(text: str) -> int:
    """中文字数：汉字按 1 字计，连续的英文单词按 1 个词计。"""
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    english = len(re.findall(r"[A-Za-z]+", text))
    return chinese + english

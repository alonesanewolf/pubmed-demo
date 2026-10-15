"""分析层：统计聚合、词云、研究方向聚类。

## 为什么不用 scikit-learn

服务器只有 2GB 内存，sklearn 装上就吃掉不少。而且这个场景的数据规模很小
（1000 篇文档），TF-IDF 和 KMeans 用 numpy 手写也就一百多行，
**面试时能讲清楚每一步在做什么**，比 `KMeans(n_clusters=6).fit_predict(X)`
有价值得多。

## 算法说明（写在这里，面试直接照着讲）

**TF-IDF 向量化**
- 对每篇文档（标题权重更高，重复一次）分词、过滤停用词、词干化简化为词根
- `tf(t,d) = 计数 / 文档长度`，`idf(t) = ln(总文档数 / 含该词文档数) + 1`
- L2 归一化 → 每个文档变成单位球面上的一个点

**KMeans 聚类**
- 在单位球面上，余弦相似度 = 点积，所以「找最近的簇」等价于「找点积最大的簇」
- 初始化用 k-means++（按距离平方概率采样，避免随机初始化收敛到坏解）
- 迭代：分配 → 用簇内均值当新质心 → 重新归一化质心 → 直到质心不再变化或达到最大轮数
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

import numpy as np

# ---------- 分词 ----------

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")

# 通用英文停用词 + 医学文献高频无意义词。
# 后者是关键：PubMed 摘要里 patient / study / result / method 出现频率极高，
# 不过滤的话词云会被这些词完全淹没。
STOPWORDS: set[str] = {
    # 英文通用
    "the", "and", "for", "that", "with", "from", "this", "that", "these", "those",
    "was", "were", "are", "has", "have", "had", "been", "being", "their", "there",
    "they", "them", "its", "it's", "his", "her", "our", "your", "which", "who",
    "whom", "what", "when", "where", "how", "why", "all", "any", "both", "each",
    "few", "more", "most", "other", "some", "such", "than", "too", "very", "can",
    "will", "just", "should", "now", "also", "into", "than", "then", "thus",
    "using", "used", "use", "based", "however", "although", "because", "between",
    "during", "under", "over", "after", "before", "about", "against", "among",
    "both", "either", "neither", "further", "once", "here", "there", "again",
    "same", "such", "own", "only", "nor", "not", "only", "same", "well",
    # 医学文献通用（真正影响词云质量的那些）
    "patient", "patients", "study", "studies", "result", "results", "method",
    "methods", "analysis", "data", "group", "groups", "case", "cases",
    "clinical", "trial", "trials", "treatment", "treated", "outcomes", "outcome",
    "background", "objective", "objectives", "purpose", "conclusion",
    "conclusions", "aim", "aims", "significant", "significantly", "difference",
    "differences", "compared", "compare", "found", "show", "showed", "shown",
    "include", "includes", "including", "increase", "increased", "decreased",
    "higher", "lower", "associated", "evaluate", "evaluated", "identify",
    "identified", "investigate", "suggest", "suggests", "suggested", "report",
    "reported", "reporting", "level", "levels", "rate", "rates", "risk", "risks",
    "age", "years", "year", "total", "number", "numbers", "health", "disease",
    "diseases", "infection", "cell", "cells", "protein", "expression", "factor",
}

# 极常见的词干后缀，粗暴合并（只做这一步，不引 Porter 之类的完整算法）
_SUFFIX_RULES = (
    ("ational", "ate"), ("ization", "ize"), ("iveness", "ive"), ("fulness", "ful"),
    ("ousness", "ous"), ("ability", "able"), ("ibility", "ible"), ("ation", "ate"),
    ("ities", "ity"), ("ives", "ive"), ("ing", ""), ("edly", ""), ("ies", "y"),
    ("ers", "er"), ("ed", ""), ("ly", ""), ("s", ""), ("es", ""),
)


def _stem(word: str) -> str:
    """极简词干化，把 crps/crispr-editing 这类变体收敛到一起。"""
    if len(word) <= 5:
        return word
    for suffix, repl in _SUFFIX_RULES:
        if word.endswith(suffix) and len(word) - len(suffix) + len(repl) >= 3:
            return word[: -len(suffix)] + repl
    return word


def tokenize(text: str, *, title_boost: int = 0) -> list[str]:
    """英文分词 + 停用词过滤 + 词干化。

    title_boost > 0 时该文本来自标题，需要在词频上加权（调用方重复拼接处理）。
    """
    words = [w.lower() for w in _TOKEN_RE.findall(text or "")]
    out: list[str] = []
    for w in words:
        if w in STOPWORDS or len(w) < 3:
            continue
        # 纯数字或含数字的词不要
        if any(ch.isdigit() for ch in w):
            continue
        out.append(_stem(w))
    return out


# ---------- 词频 ----------

# 复合词保留：crispr-cas、t-cell 这类在摘要里频次很高且很有区分度
_COMPOUND_RE = re.compile(r"^[a-z]+(?:-[a-z]+)+$")


def _is_meaningful(token: str) -> bool:
    if not token or len(token) < 3:
        return False
    if token in STOPWORDS:
        return False
    if any(ch.isdigit() for ch in token):
        return False
    return True


def build_wordcloud(papers: list, top_n: int = 150) -> list[dict[str, Any]]:
    """生成词云权重。标题里的词算 3 次权重（标题信息密度更高）。"""
    counter: Counter[str] = Counter()

    for p in papers:
        title = getattr(p, "title", "") or ""
        abstract = getattr(p, "abstract", "") or ""

        for tok in tokenize(title) * 3:
            if _is_meaningful(tok):
                counter[tok] += 3
        for tok in tokenize(abstract):
            if _is_meaningful(tok):
                counter[tok] += 1

    # 复合词（带连字符）保留完整形态，同时单独统计每个组成部分
    return [{"word": w, "weight": c} for w, c in counter.most_common(top_n)]


# ---------- 统计聚合 ----------

# 影响因子分档，题目要求「影响因子」可视化，分档比裸数值直观
IF_BANDS: list[tuple[str, float, float]] = [
    ("IF≥20", 20.0, math.inf),
    ("10≤IF<20", 10.0, 20.0),
    ("5≤IF<10", 5.0, 10.0),
    ("3≤IF<5", 3.0, 5.0),
    ("1≤IF<3", 1.0, 3.0),
    ("IF<1", 0.0, 1.0),
    ("无IF/未收录", math.inf, math.inf),
]


def _if_band_label(value: float | None) -> str:
    if value is None:
        return "无IF/未收录"
    for label, lo, hi in IF_BANDS[:-1]:
        if lo <= value < hi:
            return label
    return "IF≥20"


def build_stats(papers: list, *, recent_years: int = 5) -> dict[str, Any]:
    """按年、刊、分区、影响因子、文献类型聚合。

    ⚠️ 没有影响因子的记录归入「无IF/未收录」档，**不能算作 IF=0**。
    那是两种完全不同的含义。
    """
    years: Counter[str] = Counter()
    journals: Counter[str] = Counter()
    jcr: Counter[str] = Counter()
    cas: Counter[str] = Counter()
    if_band: Counter[str] = Counter()
    pubtypes: Counter[str] = Counter()

    # 期刊 → 该刊指标（用于画刊榜时显示 IF）
    journal_metric: dict[str, dict[str, Any]] = {}

    for p in papers:
        y = getattr(p, "year", None)
        years[str(y) if y else "未知"] += 1

        jname = (getattr(p, "journal", "") or "未知期刊").strip() or "未知期刊"
        journals[jname] += 1
        if jname not in journal_metric:
            journal_metric[jname] = {
                "if": getattr(p, "impact_factor", None),
                "jcr": getattr(p, "jcr_quartile", None),
                "cas": getattr(p, "cas_partition", None),
            }

        q = getattr(p, "jcr_quartile", None)
        jcr[q or "NA"] += 1

        c = getattr(p, "cas_partition", None)
        cas[c or "NA"] += 1

        if_band[_if_band_label(getattr(p, "impact_factor", None))] += 1

        for pt in (getattr(p, "pubtypes", None) or ["未知类型"])[:1]:
            pubtypes[pt] += 1

    return {
        "by_year": [{"key": k, "count": v} for k, v in sorted(years.items())],
        "by_journal": [
            {
                "key": j,
                "count": c,
                "if": journal_metric[j]["if"],
                "jcr": journal_metric[j]["jcr"],
                "cas": journal_metric[j]["cas"],
            }
            for j, c in journals.most_common(30)
        ],
        "by_jcr": [{"key": k, "count": v} for k, v in jcr.most_common()],
        "by_cas": [{"key": k, "count": v} for k, v in cas.most_common()],
        "by_if_band": [{"key": k, "count": v} for k, v in if_band.most_common()],
        "by_pubtype": [{"key": k, "count": v} for k, v in pubtypes.most_common(10)],
    }


def select_top_papers(papers: list, *, top_n: int = 100, recent_years: int = 5) -> list[dict[str, Any]]:
    """影响力排序：近 N 年内按影响因子降序取前 N。

    规则（契约已固定，前端依赖这个行为）：
    - 窗口是「含最大年份在内的最近 N 个自然年」
    - 窗口内按 IF 降序；窗口内不足 top_n 篇时，用窗口外同规则补齐，
      但**窗口内永远排在窗口外前面**（新鲜度优先于 IF）
    - 无影响因子的记录统一排在末尾，且 if 为 null（不是 0）

    ⚠️ 这里有个坑：早先的实现是「窗口内排序 + 窗口外排序」再拼接，
    结果窗口内那些无 IF 的记录会夹在中间，窗口外有 IF 的补到它们后面 ——
    违反「无 IF 沉底」的契约。正确做法是先按有无 IF 分四组，再拼接：
    窗口内有 IF → 窗口外有 IF → 窗口内无 IF → 窗口外无 IF。
    """
    known_years = [p.year for p in papers if getattr(p, "year", None)]
    max_year = max(known_years) if known_years else None

    def by_if_desc(group: list) -> list:
        return sorted(group, key=lambda p: -(p.impact_factor or 0))

    if max_year is None:
        has_if = by_if_desc([p for p in papers if p.impact_factor is not None])
        no_if = [p for p in papers if p.impact_factor is None]
        pool = has_if + no_if
    else:
        lo = max_year - recent_years + 1
        in_window = [p for p in papers if p.year and p.year >= lo]
        out_window = [p for p in papers if not (p.year and p.year >= lo)]
        pool = (
            by_if_desc([p for p in in_window if p.impact_factor is not None])
            + by_if_desc([p for p in out_window if p.impact_factor is not None])
            + [p for p in in_window if p.impact_factor is None]
            + [p for p in out_window if p.impact_factor is None]
        )

    result: list[dict[str, Any]] = []
    for i, p in enumerate(pool[:top_n], start=1):
        result.append({
            "rank": i,
            "pmid": p.pmid,
            "title": p.title,
            "journal": p.journal,
            "issn": p.issn,
            "if": p.impact_factor,
            "jcr": p.jcr_quartile,
            "cas": p.cas_partition,
            "year": p.year,
            # PubMed 不提供被引次数，一律 None，前端显示 NA
            "citations": p.citations,
            "doi": p.doi,
            "pubtypes": p.pubtypes,
            "has_abstract": bool(p.abstract),
        })
    return result


# ---------- 方向聚类 ----------

_MIN_DF = 2          # 文档频次下限，滤掉只出现一次的噪声词
_MAX_FEATURES = 3000
_MAX_ITER = 40


def _build_tfidf(docs: list[str]) -> tuple[np.ndarray, list[str]]:
    """返回 (稠密矩阵 [n_docs × n_features]，词表)。

    文档规模在 1000 以内，稠密矩阵完全放得下
    （1000 × 3000 × 8 bytes ≈ 24 MB），不需要上稀疏矩阵，省一堆依赖。
    """
    tokenized = [tokenize(d) for d in docs]
    vocab_set: set[str] = set()
    for toks in tokenized:
        vocab_set.update(toks)

    df: Counter[str] = Counter()
    for toks in tokenized:
        df.update(set(toks))

    # 过滤文档频次
    kept = [w for w, c in df.most_common() if c >= _MIN_DF][:_MAX_FEATURES]
    vocab = sorted(kept)
    index = {w: i for i, w in enumerate(vocab)}

    n_docs = len(tokenized)
    if n_docs == 0 or not vocab:
        return np.zeros((n_docs, 0), dtype=np.float32), vocab

    tf = np.zeros((n_docs, len(vocab)), dtype=np.float32)
    for row, toks in enumerate(tokenized):
        if not toks:
            continue
        counts = Counter(t for t in toks if t in index)
        total = sum(counts.values())
        for w, c in counts.items():
            tf[row, index[w]] = c / total

    idf = np.zeros(len(vocab), dtype=np.float32)
    for w, i in index.items():
        idf[i] = math.log(n_docs / df[w]) + 1.0

    matrix = tf * idf
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    matrix /= norms
    return matrix, vocab


def _kmeans(matrix: np.ndarray, k: int, *, seed: int = 42) -> np.ndarray:
    """单位球面上的 KMeans（余弦相似度 = 点积）。返回每个文档的簇号。"""
    n = matrix.shape[0]
    if n == 0:
        return np.zeros(0, dtype=int)
    k = max(1, min(k, n))

    rng = np.random.default_rng(seed)

    # ---- k-means++ 初始化：按与最近已选质心的距离平方做概率采样 ----
    centroids = np.zeros((k, matrix.shape[1]), dtype=np.float32)
    centroids[0] = matrix[rng.integers(n)]
    if k > 1:
        closest = 1.0 - matrix @ centroids[0]
        closest = np.maximum(closest, 0) ** 2
        for i in range(1, k):
            total = closest.sum()
            if total <= 0:
                centroids[i] = matrix[rng.integers(n)]
            else:
                probs = closest / total
                centroids[i] = matrix[rng.choice(n, p=probs)]
            d = 1.0 - matrix @ centroids[i]
            closest = np.minimum(closest, np.maximum(d, 0) ** 2)

    labels = np.zeros(n, dtype=int)

    for _ in range(_MAX_ITER):
        # ---- 分配：找点积最大的质心 ----
        sims = matrix @ centroids.T
        new_labels = np.argmax(sims, axis=1)

        if np.array_equal(new_labels, labels):
            break  # 收敛
        labels = new_labels

        # ---- 更新：簇内均值并重新归一化 ----
        for i in range(k):
            members = matrix[labels == i]
            if members.shape[0] == 0:
                # 空簇：重新随机播种，避免簇消失导致簇数不稳定
                centroids[i] = matrix[rng.integers(n)]
                continue
            c = members.mean(axis=0)
            norm = np.linalg.norm(c)
            centroids[i] = c / norm if norm > 0 else c

    return labels


def cluster_directions(
    papers: list, *, k: int = 6
) -> list[dict[str, Any]]:
    """把文献聚成若干研究方向。

    label 字段先留空 —— 中文化方向名需要调 LLM，放在 review 模块做，
    这里只负责给出稳定的簇结构。这样即使 AI 不可用，聚类和图表照样能工作。
    """
    if not papers:
        return []

    docs = [f"{(p.title or '')} {(p.title or '')} {p.abstract or ''}" for p in papers]
    matrix, vocab = _build_tfidf(docs)
    if matrix.shape[1] == 0:
        return []

    # 簇数自适应：文献太少时聚太多簇没意义
    k = max(2, min(k, len(papers) // 20 or 2))
    labels = _kmeans(matrix, k)

    clusters: list[dict[str, Any]] = []
    for cid in range(k):
        members_idx = np.where(labels == cid)[0]
        if members_idx.size == 0:
            continue

        # 该簇最具代表性的词：簇内 TF-IDF 均值最高的若干个
        sub = matrix[members_idx]
        mean_vec = sub.mean(axis=0)
        top_idx = np.argsort(mean_vec)[::-1][:8]
        keywords = [
            w for w in (vocab[i] for i in top_idx) if mean_vec[vocab.index(w)] > 0
        ][:6]

        titles = [papers[i].title for i in members_idx[:3] if papers[i].title]
        pmids = [papers[i].pmid for i in members_idx[:50]]

        clusters.append({
            "id": int(cid),
            "label": "",          # 由 LLM 填；不可用时前端显示「方向 C{cid+1}」
            "label_source": "pending",
            "size": int(members_idx.size),
            "keywords": keywords,
            "sample_titles": titles,
            "pmids": pmids,
        })

    clusters.sort(key=lambda c: -c["size"])
    for new_id, c in enumerate(clusters):
        c["id"] = new_id
    return clusters

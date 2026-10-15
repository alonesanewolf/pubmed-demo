"""期刊指标映射：影响因子 / JCR 分区 / 中科院分区。

## 为什么需要这一层

**PubMed 官方 API（E-utilities）不提供影响因子，也不提供任何分区。**
efetch 返回的 XML 里根本没有这两个字段，esummary 也没有。
这是数据源的事实，不是实现问题。

题目要求「统计相关研究数量、年份、分区、影响因子」，所以只能自建映射：
把每篇文献的期刊标识（ISSN / 刊名）映射到一条指标记录。

## 匹配策略（按优先级）

1. **ISSN 精确匹配** —— 最可靠。PubMed 多数记录带 ISSN。
2. **刊名归一化后精确匹配** —— 归一化规则见 `_normalize`。
3. **刊名缩写匹配** —— 应对 PubMed 只返回 ISOAbbreviation 的情况。
4. 都没命中 → NA，并记录原因。

## 关于 NA 的诚实处理

NA 不是「失败」，是「我们的种子表没覆盖到」。必须区分原因，否则用户
看到一片 NA 会以为数据错了：

- `not_in_seed_table` —— 期刊不在种子表里（多数情况，可手动补充）
- `no_identifier` —— PubMed 没给 ISSN 也没给刊名，无法匹配
- `no_metric` —— 种子表里有这条记录，但该刊当期没有 IF（如未被 JCR 收录）

页面上要展示**指标覆盖率**，这是「数据来源」这项交物的核心内容。
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# 刊名归一化时要丢掉的噪声词与符号
_NOISE_WORDS = {"the", "of", "and", "for", "in", "on", "a", "an", "journal", "j"}
_PUNCT_RE = re.compile(r"[^\w\s]")


@dataclass(slots=True)
class JournalMetric:
    journal: str
    issn: str = ""
    if_value: float | None = None
    jcr_quartile: str | None = None
    cas_partition: str | None = None
    year: int | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal": self.journal,
            "issn": self.issn,
            "if": self.if_value,
            "jcr": self.jcr_quartile,
            "cas": self.cas_partition,
            "year": self.year,
        }


@dataclass
class MatchResult:
    impact_factor: float | None
    jcr_quartile: str | None
    cas_partition: str | None
    reason: str | None  # None 表示匹配成功


def _normalize(name: str) -> str:
    """刊名归一化：全角转半角、去标点、丢噪声词、小写、压缩空白。

    例：
      "The Journal of Clinical Oncology." → "j clinical oncology"
      "JOURNAL OF CLINICAL ONCOLOGY"      → "j clinical oncology"
    两者归一化后相同，可以互相匹配。
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name).lower()
    s = _PUNCT_RE.sub(" ", s)
    tokens = [t for t in s.split() if t and t not in _NOISE_WORDS]
    return " ".join(tokens)


class JournalMetricStore:
    """线程安全的期刊指标仓库。

    只读为主，写入只发生在手动导入时，所以用一把粗粒度锁就够，
    不需要引入更重的东西。
    """

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.RLock()
        self._by_issn: dict[str, JournalMetric] = {}
        self._by_name: dict[str, JournalMetric] = {}
        self._by_abbrev: dict[str, JournalMetric] = {}
        self._meta: dict[str, Any] = {}
        self._load()

    # ---------- 加载 / 保存 ----------

    def _load(self) -> None:
        if not self._path.exists():
            self._meta = {
                "total_journals": 0,
                "metric_year": None,
                "source": "（种子表尚未初始化）",
                "last_updated": None,
            }
            return

        with self._lock:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                entries = raw.get("journals", [])
                # meta 在 "meta" 子对象里（本项目格式）；同时兼容平铺旧格式。
                # 曾经直接读 raw.get("metric_year")，永远拿到 None ——
                # 「数据来源」这项交物的指标年份/出处会显示为空。
                meta_src = raw.get("meta") or raw
            else:
                entries = raw
                meta_src = {}
            self._meta = {
                "total_journals": len(entries),
                "metric_year": meta_src.get("metric_year"),
                "source": meta_src.get("source"),
                "last_updated": meta_src.get("last_updated"),
            }
            for e in entries:
                self._index(JournalMetric(
                    journal=e.get("journal", ""),
                    issn=(e.get("issn") or "").strip(),
                    if_value=_to_float(e.get("if")),
                    jcr_quartile=(e.get("jcr") or None),
                    cas_partition=(e.get("cas") or None),
                    year=e.get("year"),
                    note=e.get("note", ""),
                ))

    def _index(self, m: JournalMetric) -> None:
        if m.issn:
            self._by_issn.setdefault(m.issn, m)
        key = _normalize(m.journal)
        if key:
            self._by_name.setdefault(key, m)

    def save(self, entries: Iterable[dict[str, Any]], meta: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._by_issn.clear()
            self._by_name.clear()
            self._by_abbrev.clear()
            merged = list(entries)
            self._meta.update(meta or {})
            self._meta["total_journals"] = len(merged)
            payload = {"meta": self._meta, "journals": merged}
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            # 文件刚被改写，缓存里的旧实例作废，否则导入后读到旧数据
            _STORE_CACHE.pop(str(self._path), None)
            # 重新建立索引（save 已持锁，直接调用无死锁风险，因为 _index 不加锁）
            self._by_issn.clear()
            self._by_name.clear()
            self._by_abbrev.clear()
            self._meta = {}
            self._load()

    # ---------- 查询 ----------

    def match(self, *, issn: str = "", journal: str = "", abbrev: str = "") -> MatchResult:
        with self._lock:
            hit: JournalMetric | None = None

            if issn and issn in self._by_issn:
                hit = self._by_issn[issn]

            if hit is None and journal:
                hit = self._by_name.get(_normalize(journal))

            if hit is None and abbrev:
                hit = self._by_abbrev.get(_normalize(abbrev)) or self._by_name.get(
                    _normalize(abbrev)
                )

            if hit is None:
                if not journal and not issn:
                    return MatchResult(None, None, None, "no_identifier")
                return MatchResult(None, None, None, "not_in_seed_table")

            # 命中了但没有 IF —— 说明该刊当期未被 JCR 收录，是另一种 NA
            reason = None if hit.if_value is not None else "no_metric"
            return MatchResult(hit.if_value, hit.jcr_quartile, hit.cas_partition, reason)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._meta)

    def all_entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return [m.to_dict() for m in self._by_name.values()]


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------- 仓库单例（带 mtime 缓存） ----------
# 每个请求都新建 JournalMetricStore 会重复读+解析 journals.json，
# 列表接口里每个 preset 建一次更是浪费。按 (mtime, size) 缓存，
# 导入接口改写文件后自动失效。
_STORE_CACHE: dict[str, tuple[tuple[int, int], "JournalMetricStore"]] = {}


def get_journal_store(path: Path) -> "JournalMetricStore":
    try:
        st = path.stat()
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        return JournalMetricStore(path)
    key = str(path)
    hit = _STORE_CACHE.get(key)
    if hit is not None and hit[0] == sig:
        return hit[1]
    store = JournalMetricStore(path)
    _STORE_CACHE[key] = (sig, store)
    return store


# ---------- 覆盖率统计 ----------


def attach_metrics(papers: list, store: JournalMetricStore) -> dict[str, Any]:
    """给一批 Paper 回填指标，并统计覆盖率与未匹配原因分布。

    就地修改 papers，同时返回一个覆盖率摘要供前端展示。
    """
    total = len(papers)
    matched = 0
    reason_counts: dict[str, int] = {}
    unmatched_journals: dict[str, int] = {}

    for p in papers:
        res = store.match(
            issn=(p.issn or "").strip(),
            journal=(p.journal or "").strip(),
            abbrev=(p.journal_abbrev or "").strip(),
        )
        p.impact_factor = res.impact_factor
        p.jcr_quartile = res.jcr_quartile
        p.cas_partition = res.cas_partition
        p.metrics_reason = res.reason

        if res.reason is None:
            matched += 1
        else:
            reason_counts[res.reason] = reason_counts.get(res.reason, 0) + 1
            name = p.journal or p.journal_abbrev or "(未知期刊)"
            unmatched_journals[name] = unmatched_journals.get(name, 0) + 1

    top_unmatched = [
        {"journal": k, "count": v, "reason": "not_in_seed_table"}
        for k, v in sorted(unmatched_journals.items(), key=lambda kv: -kv[1])[:10]
    ]

    return {
        "total_papers": total,
        "matched": matched,
        "rate": round(matched / total, 4) if total else 0.0,
        "unmatched_top": top_unmatched,
        "reason_counts": reason_counts,
    }

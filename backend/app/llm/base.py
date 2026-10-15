"""LLM 抽象层。

## 设计取舍

只做**一个接口 + 一个默认实现 + 一个环境变量开关**，不做多供应商智能路由、
不做自动降级链路。理由：

1. 题目有「现场演示及功能测试」的硬要求，DeepSeek 高峰期会排队变慢，
   留一个切换口子是真需求；
2. 再往上堆自动降级、熔断、路由，在笔试场景里是过度设计，
   面试官会读成「在堆概念」而不是「在解决问题」。

但**降级本身必须实现**（key 缺失 / 调用失败 / 超时）：降级不是错误，
页面其余部分照常工作，这是「失败兜底」那条要求的落点。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResult:
    """一次 LLM 调用的结果。

    ok=False 时 text 为空，reason 说明降级原因，前端据此显示提示条。
    """

    ok: bool
    text: str = ""
    model: str = ""
    reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    cost_estimate_cny: float = 0.0

    @classmethod
    def degraded(cls, reason: str, model: str = "") -> "LLMResult":
        return cls(ok=False, reason=reason, model=model)


class LLMProvider(ABC):
    """所有 LLM 后端都实现这个接口。"""

    name: str = "unknown"
    model: str = ""

    @property
    @abstractmethod
    def available(self) -> bool:
        """是否具备调用条件（key 存在等）。"""

    @abstractmethod
    async def complete(
        self, prompt: str, *, system: str = "", max_tokens: int = 2048
    ) -> LLMResult:
        """单轮补全。任何失败都应该返回 ok=False 的 LLMResult，而不是抛异常。"""


# ---------- PMID 溯源校验 ----------

# 综述正文里引用文献的两种写法都要认：
#   [38123456]          纯方括号
#   [38123456,38123457] 逗号分隔
_PMID_RE = re.compile(r"\[\s*(\d{6,9})\s*(?:[,，]\s*\d{6,9}\s*)*\]")


def extract_pmids(text: str) -> list[str]:
    """从文本中抽取所有方括号里的 PMID。"""
    found: list[str] = []
    for block in _PMID_RE.findall(text or ""):
        found.append(block)
    # 上面只抓到每个块的第一段，逗号后的需要单独再扫一遍
    for m in re.finditer(r"\[([^\[\]]+)\]", text or ""):
        for num in re.findall(r"\d{6,9}", m.group(1)):
            found.append(num)
    # 去重但保持出现顺序
    seen: set[str] = set()
    ordered: list[str] = []
    for p in found:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def validate_citations(
    text: str, allowed: set[str]
) -> tuple[str, list[str], list[str]]:
    """校验 AI 生成的引用编号是否真实存在。

    这是**幻觉防护的核心**：模型很爱编造看起来合理的 8 位数字。
    把不在检索结果集合里的引用整段标出来剔除，页面上显式告诉用户
    「模型引用了 N 个不存在的文献，已剔除」。

    返回 (清洗后的文本, 合法 PMID, 被剔除的幻觉 PMID)
    """
    hallucinated: list[str] = []

    def _repl(m: re.Match) -> str:
        nums = re.findall(r"\d{6,9}", m.group(1))
        keep = [n for n in nums if n in allowed]
        bad = [n for n in nums if n not in allowed]
        hallucinated.extend(bad)
        if not keep:
            return ""  # 整段引用都是编的，整个括号删掉
        return "[" + ",".join(keep) + "]"

    cleaned = re.sub(r"\[([^\[\]]+)\]", _repl, text or "")

    valid = [p for p in extract_pmids(cleaned) if p in allowed]
    return cleaned, valid, sorted(set(hallucinated))

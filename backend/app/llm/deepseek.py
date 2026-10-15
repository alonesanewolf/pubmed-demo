"""DeepSeek 客户端。

## 模型名的坑

`deepseek-chat` / `deepseek-reasoner` 已于 **2026-07-24 23:59 弃用**。
当前可用的是 `deepseek-v4-flash`（快、便宜）和 `deepseek-v4-pro`（强、贵）。
网上大量 2025 年的教程还在用旧名字，照抄会 400。

## 价格（deepseek-v4-flash，单位：元 / 百万 token）

| 项 | 单价 |
|---|---|
| 输入（缓存命中） | 0.02 |
| 输入（未命中） | 1.00 |
| 输出 | 2.00 |

按 Top100 摘要估算：约 35,000 输入 token + 3,500 输出 token
（其中推理 token 占大头，按输出价计费）≈ **¥0.042 / 次**。
便宜到可以放心多次重试，不用为省钱牺牲质量。

## 失败一律降级，不抛异常

现场演示是硬要求。AI 挂了不该让整个页面报错 —— 返回
`LLMResult(ok=False, reason=...)`，由上层决定怎么提示用户。
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from ..settings import get_settings
from .base import LLMProvider, LLMResult

# 单价（元 / 百万 token），用于给用户展示成本估算
_PRICE_IN_CACHED = 0.02
_PRICE_IN_FRESH = 1.00
_PRICE_OUT = 2.00


def estimate_cost(usage: dict[str, int]) -> float:
    """按实际 usage 算钱。

    ⚠️ 只用 API 返回的真实 usage，绝不用 len(text.split()) * 1.3 之类的估算式 ——
    那种启发式在中英混排文本上误差能到 30% 以上。
    """
    cached = int(usage.get("prompt_cache_hit_tokens") or 0)
    fresh = max(0, int(usage.get("prompt_tokens") or 0) - cached)
    out = int(usage.get("completion_tokens") or 0)
    cost = (
        cached / 1e6 * _PRICE_IN_CACHED
        + fresh / 1e6 * _PRICE_IN_FRESH
        + out / 1e6 * _PRICE_OUT
    )
    return round(cost, 6)


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def __init__(self) -> None:
        self._settings = get_settings()
        self.model = self._settings.deepseek_model

    @property
    def available(self) -> bool:
        return self._settings.has_llm_key

    async def complete(
        self, prompt: str, *, system: str = "", max_tokens: int = 2048
    ) -> LLMResult:
        if not self.available:
            return LLMResult.degraded("未配置 DEEPSEEK_API_KEY", self.model)

        s = self._settings
        url = f"{s.deepseek_base_url.rstrip('/')}/chat/completions"

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,      # 综述类任务要稳，不要发挥
            "max_tokens": max_tokens,
            "stream": False,
        }

        last_error: str = ""
        for attempt in range(s.llm_max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=s.deepseek_timeout) as client:
                    resp = await client.post(
                        url,
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {s.deepseek_api_key}",
                            "Content-Type": "application/json",
                        },
                    )

                if resp.status_code == 200:
                    data: dict[str, Any] = resp.json()
                    choice = (data.get("choices") or [{}])[0]
                    text = ((choice.get("message") or {}).get("content") or "").strip()
                    if not text:
                        # deepseek-v4 系是推理模型：prompt 一长，推理阶段先把
                        # max_tokens 预算烧光，content 被截成空（finish_reason=length）。
                        # 这个症状必须能在降级原因里自我解释，否则现场只能干瞪眼。
                        finish = choice.get("finish_reason")
                        hint = (
                            "（输出达到 max_tokens 上限被截断——推理模型先花预算，"
                            "请调大 max_tokens）"
                            if finish == "length" else ""
                        )
                        return LLMResult.degraded(f"模型返回空内容{hint}", self.model)
                    usage = data.get("usage") or {}
                    return LLMResult(
                        ok=True,
                        text=text,
                        model=data.get("model", self.model),
                        usage=usage,
                        cost_estimate_cny=estimate_cost(usage),
                    )

                # 429 是限流，值得退避重试；4xx 其他错误是请求本身有问题，重试没意义
                if resp.status_code == 429:
                    last_error = f"触发限流 HTTP 429"
                    if attempt < s.llm_max_retries:
                        await asyncio.sleep(2 ** attempt + random.uniform(0, 1))
                        continue
                    return LLMResult.degraded(last_error, self.model)

                if resp.status_code >= 500:
                    last_error = f"DeepSeek 服务端错误 HTTP {resp.status_code}"
                    if attempt < s.llm_max_retries:
                        await asyncio.sleep(2 ** attempt + random.uniform(0, 1))
                        continue
                    return LLMResult.degraded(last_error, self.model)

                # 400 之类：多半是模型名错了或参数不兼容，直接降级并把原文带出去便于排查
                return LLMResult.degraded(
                    f"DeepSeek 请求被拒绝 HTTP {resp.status_code}: {resp.text[:200]}",
                    self.model,
                )

            except httpx.TimeoutException:
                last_error = f"请求超时（>{s.deepseek_timeout}s）"
            except httpx.HTTPError as e:
                last_error = f"网络错误: {type(e).__name__}"
            except Exception as e:  # 兜底，绝不让异常冒到 API 层
                last_error = f"未预期错误: {type(e).__name__}: {e}"

            if attempt < s.llm_max_retries:
                await asyncio.sleep(2 ** attempt + random.uniform(0, 1))

        return LLMResult.degraded(last_error or "调用失败", self.model)


_provider: DeepSeekProvider | None = None


def get_provider() -> DeepSeekProvider:
    global _provider
    if _provider is None:
        _provider = DeepSeekProvider()
    return _provider

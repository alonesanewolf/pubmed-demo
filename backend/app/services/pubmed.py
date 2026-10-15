"""NCBI E-utilities 客户端。

## E-utilities 的几个静默行为（都踩过才知道）

1. **`retmax` 上限 9999**，传更大的值会被静默截断，**不报错**。
   只改 URL 里的 retmax 不会报错，所以千万别用 URL 传大参数。

2. **错误标签被静默忽略**。`&field=zzz` 这种拼错的检索字段，
   NCBI 不报错、直接忽略，结果跟没传一样 —— 只看 HTTP 200 会以为一切正常。

3. **`efetch` 的 `retmode=json` 不返回记录内容**，只回一串裸 PMID。
   要完整记录必须用 XML。要轻量元数据应该用 `esummary`。

4. **PubMed 不提供被引次数**。不是没做，是数据源没有。
   任何「引用数」字段都必须诚实地是 null。

## 限流

- 无 API Key：3 请求/秒
- 有 API Key：10 请求/秒

我们用一把时间锁把请求间隔钳在 `ncbi_min_interval`（默认 0.12s ≈ 8 req/s），
留了一点余量，避免被 NCBI 掐。

## ⚠️ 境内服务器的连通性

国内云服务器直连 eutils.ncbi.nlm.nih.gov **很可能不通**（TCP 层就被拦）。
所以这个模块只在 `DATA_MODE=remote/hybrid` 时才会被调用，
默认的 `local` 模式完全走预生成数据集，不碰外网。
"""

from __future__ import annotations

import asyncio
import random
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from ..settings import get_settings
from .parser import Paper, dedupe_by_pmid, parse_pubmed_xml

# efetch 单次最多带多少个 PMID。
# 官方建议分批，且单批 XML 体积可控（100 篇约 2MB）。
_FETCH_BATCH = 100
# esummary 单次最多多少个（超了会返回 "Too many UIDs in request" 错误）
_SUMMARY_BATCH = 500


class PubMedError(RuntimeError):
    """PubMed 上游错误。携带一个稳定的 code 供 API 层转成 JSON。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class PubMedClient:
    """线程/协程安全的 E-utilities 客户端（用一把 asyncio 锁串行化请求节奏）。"""

    def __init__(self) -> None:
        self._s = get_settings()
        self._lock = asyncio.Lock()
        self._last_call = 0.0
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "PubMedClient":
        self._client = httpx.AsyncClient(
            timeout=self._s.ncbi_timeout,
            headers={"User-Agent": f"{self._s.ncbi_tool} (+{self._s.ncbi_email})"}
            if self._s.ncbi_email
            else {"User-Agent": self._s.ncbi_tool},
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---------- 内部 ----------

    async def _get(self, endpoint: str, params: dict[str, Any]) -> httpx.Response:
        if self._client is None:
            raise PubMedError("INTERNAL", "PubMedClient 未初始化，请用 async with")

        params = {k: v for k, v in params.items() if v not in (None, "")}
        params.setdefault("tool", self._s.ncbi_tool)
        if self._s.ncbi_email:
            params.setdefault("email", self._s.ncbi_email)
        if self._s.has_ncbi_key:
            params.setdefault("api_key", self._s.ncbi_api_key)

        url = f"{self._s.ncbi_base_url.rstrip('/')}/{endpoint}"

        last_err = ""
        for attempt in range(3):
            # 节流：保证两次请求之间的最小间隔
            async with self._lock:
                wait = self._s.ncbi_min_interval - (asyncio.get_event_loop().time() - self._last_call)
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    resp = await self._client.get(url, params=params)
                    self._last_call = asyncio.get_event_loop().time()
                except httpx.TimeoutException:
                    last_err = f"请求 {endpoint} 超时"
                    resp = None
                except httpx.HTTPError as e:
                    last_err = f"请求 {endpoint} 网络错误: {type(e).__name__}"
                    resp = None

            if resp is not None:
                if resp.status_code == 200:
                    return resp
                # 429/5xx 值得重试；4xx 其他的不值得
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = f"{endpoint} 返回 HTTP {resp.status_code}"
                else:
                    raise PubMedError(
                        "UPSTREAM_ERROR",
                        f"PubMed 拒绝请求（HTTP {resp.status_code}）：{resp.text[:200]}",
                    )

            if attempt < 2:
                await asyncio.sleep(2 ** attempt + random.uniform(0, 1))

        raise PubMedError("UPSTREAM_TIMEOUT", last_err or "PubMed 请求失败")

    # ---------- esearch ----------

    async def esearch(
        self, term: str, *, retmax: int = 0, use_history: bool = False
    ) -> dict[str, Any]:
        """检索，返回命中总数与 PMID 列表。

        retmax=0 表示只要 count 和 History Server 句柄，不要结果页 ——
        大结果集必须走这个模式，否则 URL 会长到被拒。
        """
        capped = min(retmax, 9999)  # 超过 9999 会被静默截断，这里主动钳住
        resp = await self._get(
            "esearch.fcgi",
            {
                "db": "pubmed",
                "term": term,
                "retmode": "json",
                "retmax": capped,
                "usehistory": "y" if use_history else None,
            },
        )
        try:
            data = resp.json()
        except Exception as e:
            raise PubMedError("UPSTREAM_ERROR", f"esearch 返回的不是合法 JSON: {e}") from e

        result = data.get("esearchresult")
        if not isinstance(result, dict):
            raise PubMedError("UPSTREAM_ERROR", f"esearch 返回结构异常: {str(data)[:200]}")

        # NCBI 对拼错的检索字段只会在 errorlist 里留痕，count 仍会返回，
        # 不检查就会静默拿到一个「看起来对但过滤没生效」的结果集。
        errorlist = result.get("errorlist") or {}
        if errorlist.get("fieldsnotfound"):
            raise PubMedError(
                "INVALID_QUERY",
                f"检索字段无效：{errorlist['fieldsnotfound']}",
            )

        try:
            count = int(result.get("count") or 0)
        except (TypeError, ValueError):
            count = 0

        return {
            "count": count,
            "ids": result.get("idlist") or [],
            "webenv": result.get("webenv"),
            "querykey": result.get("querykey"),
        }

    # ---------- efetch ----------

    async def efetch_by_ids(self, pmids: list[str]) -> list[Paper]:
        """按 PMID 列表批量取全文记录（XML）。"""
        papers: list[Paper] = []
        for i in range(0, len(pmids), _FETCH_BATCH):
            batch = pmids[i : i + _FETCH_BATCH]
            resp = await self._get(
                "efetch.fcgi",
                {
                    "db": "pubmed",
                    "id": ",".join(batch),
                    "retmode": "xml",  # ⚠️ retmode=json 只会回裸 PMID 列表
                    "rettype": "abstract",
                },
            )
            papers.extend(parse_pubmed_xml(resp.text))
        return dedupe_by_pmid(papers)

    async def efetch_by_history(
        self, webenv: str, query_key: str, *, total: int, batch: int = _FETCH_BATCH
    ) -> list[Paper]:
        """用 History Server 句柄翻页取全量记录。

        比把上万个 PMID 塞进 URL 稳得多 —— URL 长度是有上限的。
        """
        papers: list[Paper] = []
        for start in range(0, min(total, 9999), batch):
            resp = await self._get(
                "efetch.fcgi",
                {
                    "db": "pubmed",
                    "query_key": query_key,
                    "WebEnv": webenv,
                    "retstart": start,
                    "retmax": batch,
                    "retmode": "xml",
                    "rettype": "abstract",
                },
            )
            chunk = parse_pubmed_xml(resp.text)
            if not chunk:
                break  # 没有更多了
            papers.extend(chunk)
        return dedupe_by_pmid(papers)

    # ---------- esummary ----------

    async def esummary(self, pmids: list[str]) -> dict[str, dict[str, Any]]:
        """批量取轻量元数据。

        用途：某些记录 efetch 拿不到期刊全称，用 esummary 补齐，
        比为了一个刊名去拉整篇 XML 便宜得多。
        """
        out: dict[str, dict[str, Any]] = {}
        for i in range(0, len(pmids), _SUMMARY_BATCH):
            batch = pmids[i : i + _SUMMARY_BATCH]
            resp = await self._get(
                "esummary.fcgi",
                {"db": "pubmed", "id": ",".join(batch), "retmode": "json"},
            )
            try:
                result = resp.json().get("result") or {}
            except Exception:
                continue
            uids = result.get("uids") or []
            for uid in uids:
                item = result.get(str(uid))
                if isinstance(item, dict):
                    out[str(uid)] = item
        return out

    # ---------- 组合操作 ----------

    async def search_and_fetch(
        self, term: str, *, limit: int
    ) -> tuple[int, list[Paper]]:
        """一步到位：检索 + 取前 limit 篇。返回 (命中总数, 文献列表)。

        大结果集走 History Server；小结果集直接按 id 取。
        """
        limit = min(limit, self._s.max_fetch_count)

        meta = await self.esearch(term, retmax=min(limit, 9999))
        total = meta["count"]

        if total == 0:
            return 0, []

        if meta.get("webenv") and limit > 9999:
            papers = await self.efetch_by_history(
                meta["webenv"], meta["querykey"], total=limit
            )
        else:
            papers = await self.efetch_by_ids(meta["ids"][:limit])

        return total, papers


async def probe_connectivity() -> dict[str, Any]:
    """连通性自检。部署后先跑这个，不要等演示当天才发现连不上。"""
    s = get_settings()
    url = f"{s.ncbi_base_url.rstrip('/')}/esearch.fcgi"
    params: dict[str, Any] = {
        "db": "pubmed",
        "term": "crispr",
        "retmode": "json",
        "retmax": 1,
        "tool": s.ncbi_tool,
    }
    if s.has_ncbi_key:
        params["api_key"] = s.ncbi_api_key

    import time

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
        elapsed = round(time.perf_counter() - started, 3)
        if resp.status_code != 200:
            return {"reachable": False, "elapsed": elapsed,
                    "error": f"HTTP {resp.status_code}"}
        count = resp.json().get("esearchresult", {}).get("count")
        return {
            "reachable": True,
            "elapsed": elapsed,
            "has_api_key": s.has_ncbi_key,
            "probe_count": count,
        }
    except Exception as e:
        return {
            "reachable": False,
            "elapsed": round(time.perf_counter() - started, 3),
            "error": f"{type(e).__name__}: {e}",
        }

"""FastAPI 应用入口。

路由严格对齐 docs/API_CONTRACT.md。改动前先改契约。
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .llm.deepseek import get_provider
from .services.dataset import (
    build_payload,
    generate_review,
    get_dataset,
    get_paper,
    list_presets,
    save_preset,
    slugify,
)
from .services.journal_metrics import get_journal_store
from .services.pubmed import PubMedClient, PubMedError, probe_connectivity
from .settings import get_settings

s = get_settings()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """启动预热：把预置数据集读进内存缓存和操作系统页面缓存。

    预置数据共约 13MB，首次全量解析在云盘上要十几秒。不预热的话，
    服务每次重启后，第一个打开页面的人（可能是面试官）直接撞上
    冷启动黑屏。预热失败不阻塞启动 —— 真实请求会自己再建缓存。
    """
    try:
        n = len(list_presets())
        print(f"[startup] preset cache warmed: {n} datasets")
    except Exception as e:  # noqa: BLE001 - 预热绝不能阻止服务起来
        print(f"[startup] warmup skipped: {type(e).__name__}: {e}")
    yield


app = FastAPI(
    title=s.app_name,
    version=s.version,
    description="PubMed 领域分析 Demo —— 笔试作业",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=s.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 统一错误处理 ----------

class ApiError(HTTPException):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(status_code=status, detail={"code": code, "message": message})


@app.exception_handler(PubMedError)
async def _pubmed_error_handler(_request, exc: PubMedError):
    """PubMed 上游错误 → 契约里的标准错误结构。"""
    return JSONResponse(
        status_code=502,
        content={"error": {"code": exc.code, "message": exc.message, "detail": None}},
    )


def _err(code: str, message: str, status: int = 404) -> HTTPException:
    return HTTPException(
        status_code=status, detail={"code": code, "message": message}
    )


# ---------- 请求模型 ----------

class ReviewRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=80)
    max_words: int = Field(500, ge=200, le=1500)
    language: str = "zh"


class SearchRequest(BaseModel):
    keyword: str = Field(..., min_length=2, max_length=200)
    limit: int = Field(1000, ge=10, le=5000)
    save_as: str | None = Field(
        None, description="给定则把结果保存为预置数据集，供后续离线使用"
    )


# ---------- 1. 健康检查 ----------

@app.get("/api/health")
async def health() -> dict[str, Any]:
    provider = get_provider()
    return {
        "status": "ok",
        "app": s.app_name,
        "data_mode": s.data_mode,
        "llm": {
            "available": provider.available,
            "provider": provider.name,
            "model": provider.model,
        },
        "preset_count": len(list_presets()),
        "version": s.version,
    }


# ---------- 2. 预置数据集列表 ----------

@app.get("/api/presets")
async def presets() -> dict[str, Any]:
    return {"items": list_presets()}


# ---------- 3. 数据集详情 ----------

@app.get("/api/datasets/{slug}")
async def dataset(slug: str) -> dict[str, Any]:
    payload = get_dataset(slug)
    if payload is None:
        raise _err("NOT_FOUND", f"数据集 {slug} 不存在或为空")
    return payload


# ---------- 4. 单篇文献详情 ----------

@app.get("/api/datasets/{slug}/papers/{pmid}")
async def paper_detail(slug: str, pmid: str) -> dict[str, Any]:
    if not pmid.isdigit():
        raise _err("INVALID_QUERY", "pmid 必须是纯数字", 400)
    detail = get_paper(slug, pmid)
    if detail is None:
        raise _err("NOT_FOUND", f"文献 {pmid} 不在数据集 {slug} 中")
    return detail


# ---------- 5. AI 综述 ----------

@app.post("/api/reviews")
async def reviews(req: ReviewRequest) -> dict[str, Any]:
    # ⚠️ 降级不是错误：AI 不可用时仍然返回 200，degraded=true，
    #    前端据此显示提示条，页面其余部分照常工作。
    return await generate_review(req.slug, max_words=req.max_words)


# ---------- 6. 期刊指标表 ----------

@app.get("/api/journals/stats")
async def journals_stats() -> dict[str, Any]:
    return get_journal_store(s.journals_file).stats()


@app.post("/api/journals/import")
async def journals_import(file: UploadFile = File(...)) -> dict[str, Any]:
    """导入期刊指标表。

    接受两种形态：
      A) 顶层是数组：  [ {journal, issn, if, jcr, cas}, ... ]
      B) 顶层是对象：  { "meta": {...}, "journals": [...] }   ← 本项目自身的格式
    """
    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise _err("INVALID_QUERY", f"文件不是合法 UTF-8 JSON：{e}", 400)

    if isinstance(payload, dict):
        entries = payload.get("journals") or []
        meta = payload.get("meta") or {}
    elif isinstance(payload, list):
        entries = payload
        meta = {}
    else:
        raise _err("INVALID_QUERY", "顶层必须是数组或对象", 400)

    store = get_journal_store(s.journals_file)
    existing = store.all_entries()
    by_key = {(e["journal"], e.get("issn", "")): e for e in existing}

    imported = skipped = 0
    errors: list[str] = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or not e.get("journal"):
            errors.append(f"第 {i + 1} 条缺少 journal 字段")
            continue
        key = (e["journal"], e.get("issn", ""))
        if key in by_key:
            skipped += 1
        by_key[key] = {
            "journal": e["journal"],
            "issn": e.get("issn", "") or "",
            "if": e.get("if"),
            "jcr": e.get("jcr"),
            "cas": e.get("cas"),
            "year": e.get("year"),
        }
        imported += 1

    merged = list(by_key.values())
    store.save(merged, {**meta, "last_updated": meta.get("last_updated")})

    return {
        "imported": imported,
        "skipped": skipped,
        "total": len(merged),
        "errors": errors[:20],
    }


# ---------- 7. 实时检索（仅 remote/hybrid 模式可用） ----------

@app.post("/api/search")
async def search(req: SearchRequest) -> dict[str, Any]:
    if not s.remote_enabled:
        raise _err(
            "INVALID_QUERY",
            f"当前为 {s.data_mode} 模式，未启用实时检索。"
            "境内服务器直连 PubMed 可能不通，如需实时检索请在 .env 中设 DATA_MODE=remote",
            400,
        )

    slug = slugify(req.save_as or req.keyword)
    try:
        async with PubMedClient() as client:
            total, papers = await client.search_and_fetch(req.keyword, limit=req.limit)
    except PubMedError as e:
        raise ApiError(e.code, e.message)

    if not papers:
        raise _err("NOT_FOUND", f"关键词「{req.keyword}」没有检索到结果", 404)

    store = get_journal_store(s.journals_file)
    from .services.journal_metrics import attach_metrics
    attach_metrics(papers, store)

    if req.save_as:
        save_preset(slug, keyword=req.keyword, label=req.keyword,
                    total_count=total, papers=papers)

    payload = build_payload(
        slug, papers=papers, keyword=req.keyword, label=req.keyword,
        total_count=total, generated_at="", source="NCBI E-utilities（实时）",
    )
    return payload


# ---------- 8. 连通性自检 ----------

@app.get("/api/admin/connectivity")
async def connectivity() -> dict[str, Any]:
    """部署后先跑这个，别等演示当天才发现连不上。"""
    return await probe_connectivity()


# ---------- 9. 关于页数据 ----------

_ABOUT_PATH = s.presets_dir.parent.parent / "app" / "content" / "about.json"


@app.get("/api/about")
async def about() -> dict[str, Any]:
    if not _ABOUT_PATH.exists():
        return {"competitors": [], "ai_approach": [], "data_sources": []}
    return json.loads(_ABOUT_PATH.read_text(encoding="utf-8"))


# ---------- 前端静态托管（生产，可选模式） ----------

# 开发期前端跑 Vite dev server，通过 proxy 转发到这里。
# 生产部署默认由 nginx 直接托管 frontend/dist（见 deploy/pubmed-demo.conf），
# 这里提供的是「不依赖 nginx」的裸 FastAPI 模式：
# 把 Vite build 产物拷到 backend/static/ 即可生效。
#
# 这个模式有两个坑，在这里处理掉：
#   1) 不能把 StaticFiles 挂在 "/" —— 它会吞掉 /about 这类前端路由并直接 404。
#      SPA 需要的是「未命中就回 index.html，交给 react-router」。
#   2) 回退前必须防目录穿越：full_path 里可能出现 ..，resolve 后必须仍在
#      static 目录内，否则等于开了一个任意文件读取的口子。

# backend/data/journals.json 上溯两级 = backend/，静态产物放 backend/static/
_STATIC_DIR = s.journals_file.parent.parent / "static"

if _STATIC_DIR.exists() and (_STATIC_DIR / "index.html").exists():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    _STATIC_ROOT = _STATIC_DIR.resolve()

    def _static_file_or_none(rel: str):
        """rel 存在且不穿越 static 目录时返回 FileResponse，否则 None。"""
        candidate = (_STATIC_ROOT / rel).resolve()
        if candidate.is_file() and candidate.is_relative_to(_STATIC_ROOT):
            return FileResponse(candidate)
        return None

    # Vite 产物里所有带内容哈希的资源都在 /assets 下，只挂这个前缀，
    # 根路径留给下面的 SPA 路由处理。
    if (_STATIC_DIR / "assets").is_dir():
        app.mount(
            "/assets", StaticFiles(directory=str(_STATIC_DIR / "assets")), name="assets"
        )

    @app.get("/")
    async def index_page() -> Any:
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> Any:
        """SPA 回退：任何未命中的 GET 都回 index.html。

        /api 前缀除外 —— 接口 404 必须返回契约里的 JSON 错误体，
        不能返回 HTML（否则前端解析直接崩，而且掩盖真实错误）。
        """
        if full_path == "api" or full_path.startswith("api/"):
            raise _err("NOT_FOUND", f"路径 /{full_path} 不存在")
        resp = _static_file_or_none(full_path)
        return resp if resp is not None else FileResponse(_STATIC_DIR / "index.html")

else:

    @app.get("/")
    async def root() -> Any:
        return {
            "service": s.app_name,
            "version": s.version,
            "docs": "/docs",
            "note": "前端静态产物未部署到 static/，API 可用",
        }

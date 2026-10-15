# PubMed 领域分析 Demo — 前后端 API 契约

> 这是前后端并行开发的**唯一事实源**。任何一方改动接口前，必须先改这份文档。
> 后端基址：`http://<host>:<port>`，前端开发期通过 Vite proxy 转发 `/api`。

---

## 通用约定

- 所有响应 `Content-Type: application/json; charset=utf-8`
- 时间字段统一 ISO 8601 UTC 字符串，例：`"2026-10-15T12:00:00Z"`
- 错误统一格式：

```json
{
  "error": {
    "code": "UPSTREAM_TIMEOUT",
    "message": "PubMed 检索超时，请重试",
    "detail": "upstream eutils.ncbi.nlm.nih.gov did not respond in 30s"
  }
}
```

错误码枚举：`UPSTREAM_TIMEOUT` / `UPSTREAM_ERROR` / `INVALID_QUERY` / `NOT_FOUND` / `LLM_UNAVAILABLE` / `INTERNAL`

---

## 1. 健康检查

`GET /api/health`

```json
{
  "status": "ok",
  "app": "pubmed-domain-analytics",
  "data_mode": "local",
  "llm": { "available": true, "provider": "deepseek", "model": "deepseek-v4-flash" },
  "preset_count": 5,
  "version": "1.0.0"
}
```

`data_mode` 取值：`local`（只读预置数据集）、`remote`（直连 NCBI）、`hybrid`（优先本地，回落远程）。

---

## 2. 预置数据集列表

`GET /api/presets`

```json
{
  "items": [
    {
      "slug": "crispr-gene-editing",
      "label": "CRISPR 基因编辑",
      "keyword": "CRISPR gene editing",
      "total_count": 64320,
      "fetched_count": 1000,
      "generated_at": "2026-10-15T12:00:00Z",
      "metrics_rate": 0.873
    }
  ]
}
```

---

## 3. 获取数据集（全量聚合结果）

`GET /api/datasets/{slug}`

这是页面首屏的**唯一**大接口。后端必须做服务端聚合，**不得**返回逐篇原始记录。
响应体目标 < 300 KB。

```json
{
  "slug": "crispr-gene-editing",
  "label": "CRISPR 基因编辑",
  "keyword": "CRISPR gene editing",
  "total_count": 64320,
  "fetched_count": 1000,
  "year_range": { "min": 1993, "max": 2026 },
  "generated_at": "2026-10-15T12:00:00Z",
  "source": "NCBI E-utilities (esearch + efetch)",
  "metrics_coverage": {
    "total_papers": 1000,
    "matched": 873,
    "rate": 0.873,
    "unmatched_top": [
      { "journal": "J Foo Bar", "count": 12, "reason": "not_in_seed_table" }
    ]
  },
  "stats": {
    "by_year":    [ { "key": "2020", "count": 120 } ],
    "by_journal": [ { "key": "Nature", "count": 45, "if": 58.7, "jcr": "Q1", "cas": "1区" } ],
    "by_jcr":     [ { "key": "Q1", "count": 150 } ],
    "by_cas":     [ { "key": "1区", "count": 80 } ],
    "by_if_band": [ { "key": "IF>=10", "count": 120 } ],
    "by_pubtype": [ { "key": "Journal Article", "count": 900 } ]
  },
  "wordcloud": [ { "word": "crispr", "weight": 1200 } ],
  "clusters": [
    {
      "id": 0,
      "label": "基因编辑机制",
      "label_source": "llm" ,
      "size": 230,
      "keywords": ["cas9", "guide-rna", "off-target"],
      "sample_titles": ["...", "..."]
    }
  ],
  "top_papers": [
    {
      "rank": 1,
      "pmid": "38123456",
      "title": "Base editing ...",
      "journal": "Nature",
      "issn": "0028-0836",
      "if": 58.7,
      "jcr": "Q1",
      "cas": "1区",
      "year": 2024,
      "citations": 210,
      "doi": "10.1038/s41586-024-07000-0",
      "pubtypes": ["Journal Article"],
      "has_abstract": true
    }
  ],
  "data_quality_note": "影响因子来自内置期刊指标表（2024 JCR），未收录期刊显示为 NA。"
}
```

**排序规则（后端保证）**：`top_papers` = 近 5 年（`max_year - 4` 起）内按影响因子降序，取前 100。
无影响因子的记录**排在末尾**，且 `if` 为 `null`（不是 0）。

---

## 4. 单篇文献详情（点开时才拉摘要）

`GET /api/datasets/{slug}/papers/{pmid}`

```json
{
  "pmid": "38123456",
  "title": "...",
  "abstract": "...",
  "authors": ["Zhang W", "Li H"],
  "journal": "Nature",
  "if": 58.7,
  "jcr": "Q1",
  "cas": "1区",
  "year": 2024,
  "doi": "10.1038/...",
  "pubtypes": ["Journal Article"],
  "mesh_terms": ["CRISPR-Cas Systems", "Gene Editing"],
  "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/38123456/"
}
```

---

## 5. AI 综述生成

`POST /api/reviews`

请求：

```json
{ "slug": "crispr-gene-editing", "max_words": 500, "language": "zh" }
```

响应：

```json
{
  "slug": "crispr-gene-editing",
  "model": "deepseek-v4-flash",
  "degraded": false,
  "degraded_reason": null,
  "word_count": 512,
  "sections": [
    {
      "point": "一、研究背景与整体格局",
      "text": "近五年该领域共发表 1,000 篇文献……",
      "citations": ["38123456", "37123456"]
    }
  ],
  "citations": [
    { "pmid": "38123456", "rank": 1, "title": "...", "journal": "Nature", "if": 58.7 }
  ],
  "generated_at": "2026-10-15T12:30:00Z",
  "cost_estimate_cny": 0.037
}
```

**降级约定（必须实现）**：`degraded: true` 时，`sections` 为空数组，
前端必须显示「AI 服务暂不可用，已降级为纯统计模式」提示，**页面其余部分照常工作**。
HTTP 状态码仍是 200 —— 降级不是错误。

---

## 6. 期刊指标表

`GET /api/journals/stats`

```json
{
  "total_journals": 412,
  "metric_year": 2024,
  "source": "内置种子表（手工整理自 JCR 2024）",
  "last_updated": "2026-10-01"
}
```

`POST /api/journals/import` — `multipart/form-data`，字段名 `file`，UTF-8 JSON 数组：

```json
[
  { "journal": "Nature", "issn": "0028-0836", "if": 58.7, "jcr": "Q1", "cas": "1区" }
]
```

成功返回 `{ "imported": 120, "skipped": 3, "errors": [...] }`。

---

## 7. 设计说明页数据

`GET /api/about` — 返回项目说明、AI 使用思路、数据来源声明，供前端"关于"页展示。
文案以仓库内 `backend/app/content/about.json` 为准。

---

## 前端路由约定

| 路由 | 内容 |
|---|---|
| `/` | 主分析页（搜索/预设选择 → 图表 → 词云 → Top100 → 综述） |
| `/about` | 竞品分析 + AI 使用说明 + 数据来源声明 |

# PubMed 领域分析 · 前端

React 18 + Vite 5 + TypeScript + ECharts 5（含 `echarts-wordcloud`）+ React Router 6。
不引状态管理库（用 React 内置 hook），不引 UI 组件库（样式全部手写）。

**接口字段一律以 [`docs/API_CONTRACT.md`](../docs/API_CONTRACT.md) 为准**，前端不自行发明字段名，
代码里也不出现任何域名或 API Key。

---

## 1. 安装与运行

```bash
cd frontend
npm install

# 方式 A：mock 模式（推荐，后端不启动也能看全部页面）
cp .env.example .env        # .env.example 默认就是 VITE_USE_MOCK=true
npm run dev                 # http://localhost:5173

# 方式 B：接真实后端（后端默认 http://127.0.0.1:8000）
npm run dev
```

后端没起时，若 `.env` 里 `VITE_MOCK_FALLBACK=true`，页面会在网络层失败后自动回落到 mock，
顶栏出现「数据来源：Mock」提示条，**不会出现白屏**。

## 2. 构建

```bash
npm run build        # = tsc --noEmit && vite build
npx tsc --noEmit     # 单独类型检查
npm run preview      # 本地预览产物，端口 4173
```

产物在 `dist/`。把它整个拷到 `backend/static/`，后端 `main.py` 检测到该目录就会用 FastAPI 托管，
无需额外 nginx。前后端同源，所以代码里所有请求都是相对路径 `/api/xxx`。

### 体积控制

首屏 JS gzip 约 **70 KB**（ECharts 被拆到独立 chunk，图表区块用 `React.lazy` 异步加载，
进入分析页才下载）。ECharts 采用 `echarts/core` 按需注册（只用 Bar/Pie + wordcloud），
没有使用 `import * as echarts` 的全量包。

## 3. Mock 开关

全部在 `frontend/.env`（模板见 `.env.example`）：

| 变量 | 默认 | 作用 |
|---|---|---|
| `VITE_PROXY_TARGET` | `http://127.0.0.1:8000` | 开发期 Vite proxy 的后端地址 |
| `VITE_PORT` | `5173` | dev server 端口 |
| `VITE_USE_MOCK` | `true` | `true` = 全程离线假数据，完全不请求后端 |
| `VITE_MOCK_FALLBACK` | `true` | 走真实后端时，网络层失败是否自动回落 mock |
| `VITE_MOCK_REVIEW_DEGRADED` | `false` | `true` = 让 mock 的 AI 综述返回 `degraded:true`，用于演示降级路径 |

演示「降级」效果：

```bash
# PowerShell
$env:VITE_MOCK_REVIEW_DEGRADED="true"; npx vite --port 5199
```

Mock 数据在 `src/api/mock/data.ts`，结构严格照契约生成，并刻意保留了几处真实世界的"坑"，
用来验证前端不会说谎：

- 约 6% 的文献落在未收录期刊上，`if`/`jcr`/`cas` 为 `null` → 前端必须显示 `NA` 而不是 `0`；
- `citations` 恒为 `null`（PubMed 不提供被引数）→ 表格显示 `NA` 并带说明 tooltip；
- `metrics_coverage.rate = 0.873`，覆盖率低是已知情况 → 进度条如实展示，附 `data_quality_note`；
- IF 分档标签与后端 `analysis.py` 的 `IF_BANDS` 完全一致（`IF≥20 / 10≤IF<20 / … / 无IF/未收录`）。

> 回落策略只对**网络层失败**（连接被拒、代理不通）生效；后端返回的业务错误
> （`NOT_FOUND` / `UPSTREAM_TIMEOUT` 等）会如实报错，不会被 mock 掩盖。

## 4. 目录结构

```
src/
  api/
    http.ts          fetch 封装 + 错误码中文化（沿用前一个 worker 的实现）
    types.ts         契约类型（沿用，仅把 citations 修正为 number | null，与后端一致）
    client.ts        唯一数据入口；mock 开关与回落逻辑都在这里
    mock/data.ts     契约一致的假数据
  components/        Layout / SearchBar / OverviewCards / ChartsSection /
                     WordCloudPanel / ClusterPanel / TopPapersTable /
                     PaperDrawer / ReviewPanel / ui(通用骨架、空态、错误态)
  hooks/             useAsync（区块级 loading/error）、useChart（ECharts 实例）
  lib/               echarts.ts（按需注册）、palette.ts（色板，刻意不引 echarts）
  pages/             AnalysisPage、AboutPage
  theme/             ThemeProvider（深浅色，走 CSS 变量 + localStorage）
```

### 几个刻意的设计取舍

- **摘要不在列表预加载**：契约里列表接口本就不含 `abstract`，点行时才
  `GET /api/datasets/{slug}/papers/{pmid}`（服务器只有 4Mbps 带宽）。
- **排序时 `null` 沉底**：IF 为 `null` 的记录固定排在末尾，与后端 `select_top_papers` 一致，
  不参与数值比较。
- **词云按聚类上色**：颜色取自 `clusters[].id`，与下方聚类卡片一一对应；未归类词走灰色，
  避免"看起来有含义其实没有"。
- **`degraded` 不是错误**：`POST /api/reviews` 降级时 HTTP 仍是 200，前端显示提示条，
  页面其余区块照常工作，不弹对话框、不清空页面。
- **每个区块独立骨架**：数据分别用 `useAsync` 拉取，一个区块慢不会拖住整页。

## 5. `/api/about` 的示例结构

文案由后端 `backend/app/content/about.json` 提供（**内容放在 backend 侧，前端不创建**）。
该文件不存在时 `GET /api/about` 退化为
`{"competitors": [], "ai_approach": [], "data_sources": []}`，页面显示占位文案而不是白屏 ——
所以前端不依赖这份文件是否存在，两边可以各自独立演进。

当前仓库已填入 6 个竞品 / 3 段 AI 思路 / 3 段数据来源 / 1 段边界说明，结构如下：

```json
{
  "competitors": [
    {
      "name": "PubMed 官网检索",
      "tagline": "官方数据源，覆盖最全",
      "strengths": ["数据权威", "MeSH 主题词规范"],
      "weaknesses": ["只有检索，没有领域分析与综述", "影响因子需另行订阅"],
      "our_approach": "在官方检索之上补齐聚合统计、影响力排序与 AI 综述。"
    },
    {
      "name": "Semantic Scholar",
      "tagline": "引用关系与影响力可视化强",
      "strengths": ["被引数据完整", "论文间关系图谱"],
      "weaknesses": ["中文综述缺失", "中文期刊覆盖一般"],
      "our_approach": "取其影响力排序思路，但被引数据受 PubMed API 限制时如实标注 NA。"
    }
  ],
  "ai_approach": [
    {
      "title": "AI 承担的部分",
      "body": "研究方向的聚类命名与中文综述撰写，全部由后端调用大模型完成。",
      "items": ["为聚类生成中文标签", "撰写分点综述并挂引用角标"]
    },
    {
      "title": "AI 不承担的部分",
      "body": "所有统计数字（年份、期刊、分区、影响因子分布）均由后端确定性计算，AI 不参与，避免出现「看起来很具体但无法复算」的数字。",
      "items": ["图表数据 100% 来自聚合接口", "引用 PMID 经白名单校验，编造的会被剔除"]
    }
  ],
  "data_sources": [
    {
      "title": "文献数据",
      "body": "NCBI E-utilities（esearch + efetch）检索 PubMed。"
    },
    {
      "title": "影响因子与分区",
      "body": "来自后端内置的期刊指标种子表（手工整理自 JCR / 中科院分区），非 PubMed 官方数据，覆盖率有限，未收录期刊一律显示 NA。"
    }
  ]
}
```

字段名说明：

| 字段 | 类型 | 前端渲染位置 |
|---|---|---|
| `competitors[]` | `{name, tagline?, strengths?[], weaknesses?[], our_approach?}` | 竞品分析卡片网格 |
| `ai_approach[]` / `ai_usage[]` | `{title?, body?, items?[]}` | AI 使用思路列表 |
| `data_sources[]` | 同上 | 数据来源声明 |
| `sections[]` | 同上 | 兜底渲染区（上述数组都没有时） |

空数组、空字段都会被渲染成带引导的占位文案，所以后端这份文件什么时候补都不影响前端可用性。

⚠️ `src/api/mock/data.ts` 里的 `mockAbout` **故意保持空数组**：文案是单一事实源
（`backend/app/content/about.json`），复制一份到 mock 会变成两处维护。
因此 `VITE_USE_MOCK=true` 的本地开发模式下，设计说明页会显示占位文案 —— 那是预期的，
要看真实文案请起后端并用 `VITE_USE_MOCK=false`。

## 6. 深浅色

点右上角按钮切换，写入 `<html data-theme>` 并持久化到 `localStorage`。
图表配色不注册 ECharts 全局 theme，而是按当前主题重算 option（`src/lib/palette.ts`），
这样 CSS 变量与画布颜色始终一致。

`src/lib/palette.ts` 被刻意独立于 `echarts.ts` —— 概览卡片和聚类卡片要用同一套色板，
但不该因此把整个 ECharts 拖进首屏 chunk。

## 7. 响应式

1366×768（笔记本投屏）与 1920×1080 均已实测无横向滚动条；`≤1080px` 图表与聚类降为单列，
`≤900px` 顶栏换行。表格区域独立滚动，不撑破页面。

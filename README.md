# PubMed 领域分析 Demo

> **Scholarscope 解决「这篇文章值不值得看」，这个 Demo 解决「这个领域正在发生什么」。**
> 输入一个关键词，几秒钟内给出：研究数量与年份趋势、期刊影响因子/分区分布、研究方向词云与聚类、近 5 年影响力 Top100 榜单，以及一篇带文献溯源的 AI 中文综述。

**在线演示**：http://122.51.97.86:5300/ ｜ **接口文档**：http://122.51.97.86:5300/docs

![demo 截图占位](./docs/screenshot-home.png)
<!-- TODO: 替换为真实截图。交件要求「每个功能模块的完整页面」，建议至少 6 张：
     首页全景 / 图表区 / 词云 / Top100 榜单 / AI 综述（含溯源）/ 设计说明页 -->

---

## 功能（对应笔试四项核心要求）

| # | 要求 | 实现 |
|---|---|---|
| 1 | 统计研究数量、年份、分区、影响因子 | 年份趋势、期刊 Top30、JCR/中科院分区分布、IF 分档直方图，全部服务端聚合 |
| 2 | 词云 + 研究方向总结 + 可视化图表 | ECharts 词云 + TF-IDF/KMeans 方向聚类（中文命名）+ 5 类统计图 |
| 3 | 影响力排序：近 5 年 IF 前 100 | 窗口内 IF 降序，无 IF 沉底且显示 NA（不是 0） |
| 4 | 基于摘要生成 500 字中文综述 | DeepSeek 生成，分点呈现，**每点挂 PMID 溯源，编造的编号服务端剔除** |

额外：预置 5 个领域的离线数据集（现场断网可完整演示）、AI 服务不可用时自动降级为纯统计模式（页面其余部分照常工作）、期刊指标表 JSON 导入入口。

## 快速开始

```bash
# 后端（Python 3.10+）
cd backend
python -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env          # 按需填 DEEPSEEK_API_KEY，留空则 AI 功能自动降级
venv/bin/python -m uvicorn app.main:app --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev                   # http://localhost:5173，/api 自动代理到 8000

# 离线自测（不联网，41 项断言）
cd backend && python tools/selftest.py
```

`data/presets/` 已内置 5 个真实数据集（各 1000 篇），后端启动即可演示，**不需要 API Key、不需要联网**。

## 架构

```
浏览器 ──> nginx :5300 ──┬─/assets/*  静态产物（Vite build，一年长缓存）
                         ├─/          SPA（react-router，try_files 回退）
                         └─/api/*  ──> uvicorn 127.0.0.1:8000（FastAPI，单 worker）
                                        │
                                        ├─ data/presets/*.json   预置数据集（只读）
                                        ├─ data/journals.json    期刊指标种子表
                                        ├─ analysis.py           TF-IDF + KMeans（纯 numpy）
                                        └─ llm/                  DeepSeek（失败即降级）
```

- **前后端分离 + 同源部署**：前端只走相对路径 `/api`，代码里不出现任何域名；密钥全部留在后端。
- **双数据源**：`DATA_MODE=local`（默认，只读预置数据）/ `remote`（实时检索 PubMed）/ `hybrid`（优先本地，缺失回落远程）。
- **部署即文档**：`deploy/` 下一键脚本 + systemd + nginx 模板 + 排障手册，对同机现有服务零改动（详见 [deploy/DEPLOY.md](./deploy/DEPLOY.md)）。

## 工程决策（都是被现实逼出来的，不是堆概念）

**1. 为什么「采集」和「服务」分开，以及为什么有两条采集通道**
境内网络直连 NCBI 的 TLS 握手会被阻断（TCP 能连、curl exit 35）。数据采集因此在能连通的机器上完成，服务器只读 JSON。两条通道都留了：NCBI E-utilities（协议原生）和 Europe PMC（EMBL-EBI 的 MEDLINE 镜像）。实测腾讯云上海 → NCBI 国际带宽 ~187KB/s，抓 1000 篇要 10 次请求约 2 分钟；Europe PMC 单次请求可取 1000 条，**5 个关键词 75 秒抓完**。预置数据的 `source` 字段如实标注采集通道。

**2. 采集排序不是小事**
Europe PMC 默认按「最新」排序，1000 篇全挤在最近 3 个年份——「统计年份」这张图直接没有信息量。改成按被引降序后，年份跨度 1978–2024；同时高被引文献集中在大刊，**期刊指标覆盖率从 10.7% 提升到 52.8%**（一个参数同时修好了两个指标）。

**3. 推理模型的 token 预算坑（实测，且踩了两次）**
`deepseek-v4-flash` 是推理模型，响应分 `reasoning_content` 和 `content` 两段，两者共用同一个 `max_tokens` 预算——推理阶段吃光预算，正文就整段为空（`finish_reason=length`），页面降级为纯统计模式。

第一次踩：综述 prompt 较长，`max_tokens=2000` 时正文为空；放大到 `4096` 后"稳定产出"，于是把 4096 写死进了代码。
第二次踩（线上实测）：那份"4096 稳定"的结论是在**输入很小**的时候测的。后来综述 prompt 变成 100 篇 × 600 字符摘要 = **73,172 字符 ≈ 4.5 万 token**，推理阶段把 4096 照旧烧光，综述在演示现场稳定降级。**参数没变，但它依赖的输入规模变了，结论就作废了。**

现在两层一起修：
- **压输入**：综述只要 500 字，没必要喂 99 篇摘要。改为 30 篇 × 300 字符，prompt 降到 **13,177 字符（-82%）**，输入成本和推理难度同时下降；
- **留余量 + 自动重试**：`max_tokens` 提到 8192 并暴露为 `LLM_REVIEW_MAX_TOKENS`（降级提示里写着"请调大 max_tokens"，运营侧改不动代码的话这句话就是假的）；预算不足时自动翻倍重试一轮再判降级。

✅ 修复后真机复测（`crispr-gene-editing`，1000 篇样本，`deepseek-v4-flash`）：两次调用均未降级——559 字 / 5 个分点 / 50.7s / ¥0.0097，以及 445 字 / 66.1s / ¥0.0151，`hallucinated_filtered=[]`。空 content 时降级原因仍带 `finish_reason` 自解释，现场可自诊断。

**4. 幻觉防护必须在服务端**
模型很爱编造看起来合理的 8 位 PMID。综述正文先整体过白名单校验，不在本次检索结果里的编号一律剔除并计数（`hallucinated_filtered`），再按分点拆条。前端校验等于没有校验。

**5. 2G 内存的取舍**
聚类用纯 numpy 手写 TF-IDF + KMeans++（1000 篇 × 3000 维稠密矩阵约 24MB），不引 sklearn；XML 解析用标准库 `ElementTree`，不装 lxml；分词用自带正则，不装 nltk（省掉语料下载）。服务以非 root 用户运行，`MemoryMax=512M` 硬上限，实测占用 ~40MB，同机的 MySQL/Redis 不受影响。

**6. 降级是默认设计，不是补丁**
AI 超时/限流/未配 Key → 综述接口返回 `degraded:true` 且 HTTP 200，页面其余部分照常工作。现场演示网络不稳时这一手能救命，所以它被做成了契约的一部分（见 [docs/API_CONTRACT.md](./docs/API_CONTRACT.md)）。

**7. 离线可证正确**
服务器连不上 PubMed 不等于代码没法验证：`tools/selftest.py` 用贴近真实结构的合成 XML 跑 41 项断言，覆盖解析、指标匹配、统计、聚类、PMID 幻觉防护、引用角标去重，不联网可复现（实际执行条数以 selftest 自己的输出为准）。

## 数据来源（笔试交件项）

- **文献数据**：PubMed/MEDLINE，经 Europe PMC REST API 采集（`resultType=core`，含摘要/MeSH/文献类型），采集脚本 `backend/tools/fetch_epmc.py`。预置 5 个领域各 1000 篇。
- **期刊指标**：内置种子表 `backend/data/journals.json`（影响因子整理自 JCR 2024，中科院分区 2024 版）。**表内数值为待逐条核对版本**，页面对未收录期刊显示 NA 并区分三种原因（不在种子表 / 无标识 / 无当期指标），同时公示本次检索的指标覆盖率（当前 32.6%–54.7%，种子表覆盖 60 本常用期刊，扩充中）。
- **AI 综述**：DeepSeek `deepseek-v4-flash`。成本按 API 返回的真实 `usage` 计费，不用估算式。实测两次调用 **¥0.0097 / ¥0.0151**（prompt 已从 ~4.5 万 token 压到 ~8 千 token）。⚠️ 早期 README 标的「单次 ¥0.02–0.04」是在输入还很大时测的，与当前实现不符，已按实测回填。

## 目录结构

```
pubmed-demo/
├── backend/
│   ├── app/
│   │   ├── main.py               FastAPI 入口（路由严格对齐 API 契约）
│   │   ├── settings.py           全部配置走环境变量，密钥不进前端不进日志
│   │   ├── services/
│   │   │   ├── parser.py         PubMed XML 解析（剥标题内嵌 HTML、MedlineDate 回退）
│   │   │   ├── journal_metrics.py ISSN→刊名→缩写 三级匹配 + NA 归因
│   │   │   ├── analysis.py       TF-IDF + KMeans++ + 统计聚合（纯 numpy）
│   │   │   ├── dataset.py        预置数据读写（mtime 缓存）+ 聚合出口
│   │   │   ├── pubmed.py         E-utilities 客户端（限流/重试/History Server）
│   │   │   └── review.py         AI 编排：聚类命名 + 综述 + 白名单校验
│   │   ├── llm/                  LLM 抽象接口 + DeepSeek 实现
│   │   └── content/about.json    设计说明页文案的唯一事实源（竞品分析 / AI 思路 / 数据来源）
│   ├── tools/
│   │   ├── selftest.py           41 项离线自测
│   │   ├── fetch_epmc.py         Europe PMC 采集器（首选通道）
│   │   └── fetch_dataset.py      NCBI E-utilities 采集器
│   └── data/                     presets/（5 个真实数据集）+ journals.json
├── frontend/                     React + Vite + ECharts（含词云扩展）
├── docs/API_CONTRACT.md          前后端唯一事实源
└── deploy/                       一键部署脚本 + nginx/systemd 模板 + DEPLOY.md
```

## 已知限制（诚实清单）

- 期刊种子表现覆盖 60 本，指标覆盖率 32.6%–54.7%；扩充种子表是纯数据工作，代码零改动
- 种子表 IF 数值待按 JCR 2024 逐条核对后提交
- `DATA_MODE=remote` 实时检索需要能连 NCBI 的网络 + API Key（无 Key 限流 3 req/s）
- PubMed 不提供被引数，榜单的 citations 字段恒为 NA（不用 0 冒充）

## 本地开发提示

`frontend/.env` 默认 `VITE_USE_MOCK=true`（前端可脱离后端独立开发）。**生产构建必须关掉**：

```powershell
cd frontend
$env:VITE_USE_MOCK = 'false'
npm run build
```

`deploy/deploy.sh` 会校验产物不是 Mock 构建才允许上线——用 Mock 包上线会全程显示假数据，这个守卫是实测踩坑后加的。

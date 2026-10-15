# PubMed 领域分析 Demo — 部署文档

> 目标机：腾讯云轻量应用服务器（境内·上海）`122.51.97.86`，Ubuntu 22.04，2 核 / 2GB / 50GB
> 部署原则：**只新增，不修改**。机器上已有一整套服务在跑，本 demo 以「独立端口 + 独立 systemd 单元 + 独立 conf 文件」接入，对现有服务零改动，卸载无残留。

---

## 1. 架构与端口

```
                    公网
                     │
                     ▼
        ┌────────────────────────┐
        │  nginx  :5300          │  ← 本 demo 唯一暴露面（新增 server 块）
        │  /assets/  静态长缓存   │
        │  /         SPA 回退    │
        │  /api/  →  反向代理     │
        └───────────┬────────────┘
                    │ 127.0.0.1:8000（不对公网）
                    ▼
        ┌────────────────────────┐
        │  uvicorn (FastAPI)     │  ← systemd: pubmed-demo.service，User=pubmed
        │  读 data/presets/*.json│  ← DATA_MODE=local，完全不碰外网
        │  期刊指标映射/统计/聚类 │
        │  DeepSeek 综述（可选）  │
        └────────────────────────┘
```

### 端口分配

| 端口 | 服务 | 归属 | 说明 |
|---|---|---|---|
| 80 | nginx 统一入口 | 已有 | AI 助手 / NetSec 等，**不动** |
| 8080 | AI 助手 Web | 已有 | **不动** |
| 5100 | NetSec 安全平台 | 已有 | **不动** |
| 5200 | Brain | 已有 | 默认停用 |
| 3306 / 6379 | MySQL / Redis | 已有 | **不动** |
| **5300** | **本 demo（nginx 对外）** | **新增** | 演示地址 `http://122.51.97.86:5300/` |
| **8000** | **本 demo（uvicorn）** | **新增** | 只听 `127.0.0.1`，防火墙不用开 |

> 为什么是 5300：80/8080/5100/5200/3306/6379 全部被占，5300 是空档。
> 为什么 uvicorn 只听 127.0.0.1：公网入口只有 nginx 一个，应用端口不暴露，
> 少一个攻击面，也少一条要在控制台放行的规则。

---

## 2. 部署（一条命令）

```bash
# ① 本机：把项目传到服务器（不含 node_modules / venv / .git）
scp -r pubmed-demo/ root@122.51.97.86:/opt/

# ② SSH 上服务器，执行
ssh root@122.51.97.86
cd /opt/pubmed-demo/deploy
bash deploy.sh
```

`deploy.sh` 是**幂等**的，任何时候重跑都安全（重复执行 = 更新部署）。
它会依次完成：前置检查 → 建用户/目录 → 同步后端 → 建 venv 装依赖 →
部署前端产物（含 Mock 构建校验）→ 生成 .env → 装 nginx conf 并 **reload**
（不是 restart，不断现有连接）→ 装 systemd 服务 → 健康检查。

### 部署后必须人工做的三件事（脚本不会替你做）

1. **腾讯云控制台 → 轻量服务器 → 防火墙 → 放行 5300/TCP**。不放行外网打不开，这是最常见的第一步卡点。
2. 编辑 `/opt/pubmed-demo/backend/.env` 填入 `DEEPSEEK_API_KEY`（权限已是 600）。
   不填也能跑——AI 综述接口自动降级，页面其余部分照常工作。
3. 如果 `data/presets/` 是空的，先按 §4 抓取数据集再传上来。**没有预置数据，演示页没有内容可看。**

---

## 3. 部署后验证清单

```bash
# 1) 本机健康检查（在服务器上执行）
curl -s http://127.0.0.1:8000/api/health
# 期望：{"status":"ok","data_mode":"local","llm":{"available":true,...},"preset_count":5,...}

# 2) 预置数据集列表
curl -s http://127.0.0.1:8000/api/presets

# 3) 全链路：拿一个数据集（首屏大接口）
curl -s http://127.0.0.1:8000/api/datasets/crispr-gene-editing | head -c 500

# 4) 单篇详情
curl -s http://127.0.0.1:8000/api/datasets/crispr-gene-editing/papers/38123456 | head -c 300

# 5) AI 综述（降级路径也要验证：不配 key 时应返回 degraded:true 且 HTTP 200）
curl -s -X POST http://127.0.0.1:8000/api/reviews \
     -H 'Content-Type: application/json' \
     -d '{"slug":"crispr-gene-editing","max_words":500}'

# 6) 出网连通性（提前暴露 NCBI 通不通，别等演示当天）
curl -s http://127.0.0.1:8000/api/admin/connectivity

# 7) 外网入口（本机执行）
curl -s -o /dev/null -w '%{http_code}\n' http://122.51.97.86:5300/
```

全部 200 且 `preset_count > 0` 即部署成功。
`/docs` 有 FastAPI 自带交互式接口文档，现场演示接口时可以直接打开给面试官看。

---

## 4. 数据采集（两条通道，首选 Europe PMC）

架构上「采集」和「服务」是分开的。**实测结论**（2026-10-15，腾讯云上海）：

| 通道 | 1000 篇耗时 | 说明 |
|---|---|---|
| `fetch_epmc.py`（Europe PMC） | **~15 秒/关键词** | 单次请求取 1000 条，首选 |
| `fetch_dataset.py`（NCBI） | ~2 分钟/关键词 | 10 次 efetch，国际带宽 ~187KB/s 是瓶颈 |

> 备注：部署脚本的连通性探测显示**本服务器可以直连 NCBI**（reachable=true），
> 所以两条通道在服务器上都能跑； Europe PMC 快一个数量级，且**用户本机也通**
> （本机直连 NCBI 的 TLS 被阻断，Europe PMC 不受影响）。

Europe PMC 是 EMBL-EBI 维护的 PubMed/MEDLINE 完整镜像，PMID 一致，
预置数据的 `source` 字段会如实标注采集通道。

```bash
# 在服务器上（或任何能连 Europe PMC 的机器）
cd /opt/pubmed-demo/backend
venv/bin/python tools/fetch_epmc.py --preset --limit 1000

# 本机（Windows）
cd pubmed-demo\backend
pip install -r requirements.txt
python tools\fetch_epmc.py --keyword "CAR-T cell therapy" --limit 1000
```

采集策略：`sort=CITED desc`（按被引降序抓领域高影响力文献）。
实测这个排序同时解决两个问题——默认的最新优先会让 1000 篇全挤在最近
3 个年份（年份分布图没有信息量），按被引排序后年份跨度显著拉大
（单细胞测序数据集实测 1978–2024）；且高被引文献集中在大刊，
**CRISPR 数据集的指标覆盖率从 10.7% 提升到 52.8%**（两个数字来自不同数据集，如实标注测量条件）。

预置数据集是**请求时读文件**的，传完即刻生效，不需要重启服务。

### 已知覆盖率现状（2026-10-15 实测）

| 预设 | 覆盖率 |
|---|---|
| CRISPR 基因编辑 | 52.8% |
| 肠道菌群与肥胖 | 33.1% |
| 机器学习药物发现 | 32.6% |
| 新冠疫苗有效性 | 41.6% |
| 单细胞测序 | 54.7% |

根因是**种子表只有 60 本期刊**（目标是 300–500 本）。扩充种子表是纯数据
工作：把上面这些未匹配期刊（Frontiers in plant science、Nucleic acids
research、The CRISPR journal……）按 JCR 2024 补进 `data/journals.json`，
补完重跑采集即可，代码零改动。

---

## 5. 前端重新构建（Mock 陷阱，必读）

`frontend/.env` 里 `VITE_USE_MOCK=true` 是**开发期**开关，会被 Vite 内联进产物。
用这个状态构建出来的 dist 上线后会**全程显示假数据**（顶栏有「数据来源：Mock」黄条）。

`deploy.sh` 会自动校验产物，发现 Mock 构建会强制在服务器上重新构建
（服务器有 node 时）；服务器没有 node 则报错并提示本机构建命令。

本机构建正确姿势：

```powershell
cd frontend
$env:VITE_USE_MOCK = 'false'      # 只对这一条命令生效，不动 .env
npm run build
```

---

## 6. 日常运维

```bash
# 日志（follow 模式）
journalctl -u pubmed-demo -f

# 重启 / 停止
systemctl restart pubmed-demo
systemctl stop pubmed-demo

# 看资源占用（2G 机器，留意总内存）
systemctl status pubmed-demo        # 有 MemoryMax=512M 硬上限
free -m

# 更新部署（改完代码重跑即可，幂等）
cd /opt/pubmed-demo/deploy && bash deploy.sh

# 只更新预置数据：直接 scp 新 json 到 presets/，无需重启

# nginx 配置有手动改动时
nginx -t && systemctl reload nginx
```

### 回滚 / 卸载

```bash
bash /opt/pubmed-demo/deploy/deploy.sh rollback
# 停服 + 摘除 nginx conf + reload。现有服务全程不受影响。
# 数据保留在 /opt/pubmed-demo，确认不要了再整体删除。
```

---

## 7. 排障（四段式：现象 / 根因 / 修复 / 预防）

### ① 外网打不开 `http://IP:5300`

- **现象**：本机 `curl 127.0.0.1:8000/api/health` 通，外网超时。
- **根因**：腾讯云控制台防火墙没放行 5300/TCP（轻量服务器是控制台防火墙 + ufw 双层）。
- **修复**：控制台 → 防火墙 → 放行 5300/TCP；服务器上 `ufw allow 5300/tcp`。
- **预防**：部署脚本末尾已打印该 TODO；把「放行端口」写进部署检查单。

### ② `502 Bad Gateway`（nginx 报错，`/api/*` 全挂）

- **现象**：页面能打开（静态文件正常），接口 502。
- **根因**：uvicorn 没起来，或端口对不上。`journalctl -u pubmed-demo -n 50` 看真实原因，
  九成是 venv 依赖没装全或 `.env` 语法错误（pydantic-settings 解析失败会直接退出）。
- **修复**：按日志修完后 `systemctl restart pubmed-demo`。
- **预防**：deploy.sh 第 3 步装完依赖会立即 `import fastapi, uvicorn, httpx, numpy` 自检，
  第 8 步健康检查 30 秒无响应直接终止部署。

### ③ 页面白屏 / 刷新 404，但接口正常

- **现象**：首页能开，`/about` 刷新后 404，或 JS/CSS 404。
- **根因**：dist 没同步过去，或 SPA 回退没生效。
- **修复**：确认 `/opt/pubmed-demo/frontend/dist/index.html` 存在；nginx conf 里
  `location /` 必须有 `try_files $uri $uri/ /index.html;`。
- **预防**：deploy.sh 同步 dist 后会校验产物存在；nginx 模板已内置 SPA 回退。

### ④ AI 综述一直显示「已降级」

- **现象**：`/api/reviews` 返回 `degraded: true`。
- **根因**：`.env` 里 `DEEPSEEK_API_KEY` 为空 / 写错 / 余额不足 / 模型名写成了已废弃的
  `deepseek-chat`（2026-07-24 起弃用，当前用 `deepseek-v4-flash`）。
- **修复**：改 `.env` 后 `systemctl restart pubmed-demo`，再 `curl /api/health` 看
  `llm.available` 是否变 true。
- **预防**：这是**设计好的降级路径不是故障**——现场网络不稳时这一手能救命，
  演示前反而要主动验证一次降级长什么样。

### ⑤ 服务器连不上 NCBI（实时检索不可用）

- **现象**：`/api/admin/connectivity` 显示不可达；`DATA_MODE=remote` 时 `/api/search` 报错。
- **根因**：境内网络到 `eutils.ncbi.nlm.nih.gov` 的 TLS 握手被阻断（本机实测：
  DNS 正常、TCP 443 能连、curl exit 35 SSL 错误，是 SNI 层阻断不是配置问题）。
- **修复**：不需要修——架构就是双数据源。演示走 `DATA_MODE=local` 预置数据，
  现场断网也能完整跑通。确需实时检索时，给采集机（不是服务器）配代理后按 §4 抓取。
- **预防**：部署脚本自动跑连通性探测并把结果打印出来，问题在部署当天就暴露，
  而不是演示当天。

---

## 8. 安全清单（面试会被问）

| 项 | 状态 |
|---|---|
| NCBI / DeepSeek Key | 只存在于服务器 `.env`（权限 600），不进前端、不进 git、不进日志 |
| 应用端口 | uvicorn 只听 127.0.0.1，公网入口只有 nginx |
| 运行身份 | 专用系统用户 `pubmed`（无登录 shell），不用 root 跑 Web 服务 |
| 资源隔离 | `MemoryMax=512M`，内存泄漏也拖不垮同机的 MySQL/Redis |
| 卸载 | `deploy.sh rollback` 一键摘除，现有服务零影响 |

> 已知历史遗留（面试主动说比被问出来强）：机器上**早期服务**是 root 直连 SSH +
> 明文密码部署的，那是 AI_Assistant 项目早期为了快速排障留的隐患，后来改了。
> 本 demo 从第一天起就是非 root 运行 + 密钥走环境变量。

---

## 9. 文件清单

```
deploy/
├── deploy.sh              # 一键部署/更新/回滚（幂等）
├── pubmed-demo.conf       # nginx 模板（__PLACEHOLDER__ 由脚本替换）
├── pubmed-demo.service    # systemd 单元模板
└── DEPLOY.md              # 本文档
```

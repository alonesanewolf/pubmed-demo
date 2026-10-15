/**
 * 唯一的数据入口。所有请求都走相对路径 `/api/xxx`：
 *  - 开发期由 Vite proxy 转发到后端（见 vite.config.ts）
 *  - 生产期前端产物由 FastAPI 同源托管，天然同源
 * 前端不持有任何密钥，也不出现任何域名常量。
 *
 * Mock 策略（环境变量控制，见 frontend/.env.example）：
 *  - VITE_USE_MOCK=true       全程离线，后端不启动也能独立验证全部视觉与交互
 *  - VITE_MOCK_FALLBACK=true  走真实后端，但网络层失败时自动回落到 mock
 *  - VITE_MOCK_REVIEW_DEGRADED=true  让 mock 的综述接口返回 degraded=true，用于演示降级路径
 */
import { request } from './http';
import {
  mockAbout,
  mockDataset,
  mockGenerateReview,
  mockHealth,
  mockPaperDetail,
  mockPresets,
} from './mock/data';
import type {
  AboutContent,
  DataMode,
  Dataset,
  Health,
  PaperDetail,
  PresetList,
  Review,
  ReviewRequest,
} from './types';

const env = import.meta.env;

export const USE_MOCK = env.VITE_USE_MOCK === 'true';
export const MOCK_FALLBACK = env.VITE_MOCK_FALLBACK === 'true';
export const MOCK_REVIEW_DEGRADED = env.VITE_MOCK_REVIEW_DEGRADED === 'true';

/** mock 请求的模拟延迟，让 skeleton / loading 态在开发期也能被看到 */
const MOCK_LATENCY = 260;

function delay<T>(value: T, ms = MOCK_LATENCY): Promise<T> {
  return new Promise((resolve) => {
    window.setTimeout(() => resolve(value), ms);
  });
}

// ---------- mock 是否正在生效（顶栏「数据来源」提示用） ----------

let mockInUse = USE_MOCK;
const listeners = new Set<() => void>();

export function isMockActive(): boolean {
  return mockInUse;
}

export function subscribeMock(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function setMockInUse(v: boolean): void {
  if (mockInUse === v) return;
  mockInUse = v;
  listeners.forEach((fn) => fn());
}

/** 仅供 mock 面板/测试切换用 */
export function __setMockInUse(v: boolean): void {
  setMockInUse(v);
}

/**
 * 包一层：真实请求「传输层失败」时改走 mock。
 *
 * 只对传输层失败回落 —— 连接被拒（fetch 抛错），或 Vite proxy 连不上后端时
 * 返回的「无 error body 的 5xx」。后端正常返回的业务错误（NOT_FOUND /
 * UPSTREAM_TIMEOUT / LLM_UNAVAILABLE 等）要如实展示，不能被 mock 掩盖。
 */
async function withFallback<T>(live: () => Promise<T>, mock: () => Promise<T>): Promise<T> {
  if (USE_MOCK) return mock();
  try {
    return await live();
  } catch (err) {
    const e = err as { isNetworkError?: boolean; isTransportError?: boolean };
    if (MOCK_FALLBACK && (e.isNetworkError || e.isTransportError)) {
      setMockInUse(true);
      return mock();
    }
    throw err;
  }
}

// ---------- 接口 ----------

export function getHealth(): Promise<Health> {
  return withFallback(
    () => request<Health>('/health'),
    () => delay(mockHealth, 120),
  );
}

export function getPresets(): Promise<PresetList> {
  return withFallback(
    () => request<PresetList>('/presets'),
    () => delay(mockPresets),
  );
}

export function getDataset(slug: string): Promise<Dataset> {
  return withFallback(
    () => request<Dataset>(`/datasets/${encodeURIComponent(slug)}`),
    () => delay(mockDataset(slug), 420),
  );
}

export function getPaperDetail(slug: string, pmid: string): Promise<PaperDetail> {
  return withFallback(
    () => request<PaperDetail>(`/datasets/${encodeURIComponent(slug)}/papers/${encodeURIComponent(pmid)}`),
    // 摘要按契约只在这里出现，绝不在列表接口预加载
    () => delay(mockPaperDetail(slug, pmid), 300),
  );
}

export interface ReviewExtra {
  hallucinated_filtered?: string[];
}

export function generateReview(payload: ReviewRequest): Promise<Review & ReviewExtra> {
  const runMock = () =>
    delay(
      mockGenerateReview(
        payload.slug,
        MOCK_REVIEW_DEGRADED,
        MOCK_REVIEW_DEGRADED ? ['99999999', '88888888'] : ['77777777'],
      ),
      // 真实调用 30~60s，mock 保留一个可感知的等待，避免"秒出"掩盖加载态问题
      2200,
    );
  return withFallback(
    () => request<Review & ReviewExtra>('/reviews', { method: 'POST', body: payload }),
    runMock,
  );
}

export function getAbout(): Promise<AboutContent> {
  return withFallback(
    () => request<AboutContent>('/about'),
    () => delay<AboutContent>(mockAbout, 180),
  );
}

export const DATA_MODE_LABEL: Record<DataMode, string> = {
  local: '本地预置数据集',
  remote: '实时直连 NCBI',
  hybrid: '本地优先，远程兜底',
};

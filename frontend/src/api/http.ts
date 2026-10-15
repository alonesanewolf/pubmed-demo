import type { ApiErrorBody } from './types';

/**
 * 后端基址：只有相对路径。开发期由 Vite proxy 转发，生产期与静态文件同源。
 * 前端不持有任何密钥，也不会出现任何域名常量。
 */
export const API_BASE = '/api';

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly detail?: string;
  /** 网络层失败（后端没起来 / 连接被拒），与后端返回的业务错误区分开 */
  readonly isNetworkError: boolean;
  /**
   * 传输层失败：响应没带着契约里的 error body。
   * 典型场景是 Vite proxy 连不上后端时自带的 500 空响应 ——
   * 它看起来像 HTTP 错误，实际是「后端没起来」，两者要能区分开。
   */
  readonly isTransportError: boolean;

  constructor(
    message: string,
    opts: {
      code: string;
      status: number;
      detail?: string;
      isNetworkError?: boolean;
      isTransportError?: boolean;
    },
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = opts.code;
    this.status = opts.status;
    this.detail = opts.detail;
    this.isNetworkError = opts.isNetworkError ?? false;
    this.isTransportError = opts.isTransportError ?? false;
  }
}

function isErrorBody(body: unknown): body is ApiErrorBody {
  return (
    typeof body === 'object' &&
    body !== null &&
    'error' in body &&
    typeof (body as ApiErrorBody).error?.message === 'string'
  );
}

const FRIENDLY: Record<string, string> = {
  UPSTREAM_TIMEOUT: 'PubMed 检索超时，请稍后重试',
  UPSTREAM_ERROR: '上游数据源返回异常',
  INVALID_QUERY: '检索词不合法，请调整后重试',
  NOT_FOUND: '请求的数据集不存在',
  LLM_UNAVAILABLE: 'AI 综述服务不可用',
  INTERNAL: '服务端内部错误',
};

export function friendlyMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.isNetworkError || err.isTransportError) return '无法连接后端服务，请确认服务已启动';
    return FRIENDLY[err.code] ?? err.message ?? '请求失败';
  }
  if (err instanceof Error) return err.message;
  return '未知错误';
}

interface RequestOptions {
  method?: 'GET' | 'POST';
  body?: unknown;
  signal?: AbortSignal;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal } = options;
  const url = `${API_BASE}${path}`;

  let res: Response;
  try {
    res = await fetch(url, {
      method,
      signal,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    // fetch 抛错 = 请求没发出去或连接断了
    throw new ApiError('无法连接后端服务', {
      code: 'NETWORK',
      status: 0,
      isNetworkError: true,
      detail: cause instanceof Error ? cause.message : String(cause),
    });
  }

  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }

  if (!res.ok) {
    if (isErrorBody(parsed)) {
      throw new ApiError(parsed.error.message, {
        code: parsed.error.code,
        status: res.status,
        detail: parsed.error.detail,
      });
    }
    // 没有契约 error body —— 是 proxy / 网关层失败，不是后端业务错误
    throw new ApiError(
      res.status === 0 || res.status >= 500
        ? '无法连接后端服务，请确认服务已启动'
        : `请求失败（HTTP ${res.status}）`,
      { code: 'INTERNAL', status: res.status, isTransportError: true },
    );
  }

  if (parsed === null) {
    throw new ApiError('响应不是合法 JSON', { code: 'INTERNAL', status: res.status });
  }
  return parsed as T;
}

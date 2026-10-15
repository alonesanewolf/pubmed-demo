/**
 * 异步数据 hook（用 React 内置 useState/useEffect，不引状态库）。
 * 每个区块各自调用 → 各自独立 loading / error，互不牵连。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { friendlyMessage } from '../api/http';

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  /** 上一次的 error，用于决定是否还能沿用旧数据展示 */
  reload: () => void;
  setData: (updater: T | ((prev: T | null) => T)) => void;
}

export function useAsync<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: unknown[],
  options: { enabled?: boolean } = {},
): AsyncState<T> {
  const { enabled = true } = options;
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const ctrl = new AbortController();
    let alive = true;
    setLoading(true);
    setError(null);
    loaderRef
      .current(ctrl.signal)
      .then((value) => {
        if (!alive) return;
        setData(value);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!alive || ctrl.signal.aborted) return;
        setError(friendlyMessage(err));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  const update = useCallback((updater: T | ((prev: T | null) => T)) => {
    setData((prev) =>
      typeof updater === 'function' ? (updater as (p: T | null) => T)(prev) : updater,
    );
  }, []);

  return { data, loading, error, reload, setData: update };
}

/**
 * 顶部搜索区：关键词输入 + 预置标签 + 数据来源/健康状态。
 * 自由关键词走 POST /api/search（仅 remote/hybrid 模式可用），失败由页面给出可读原因。
 */
import { useState, type FormEvent } from 'react';
import type { Health, PresetItem } from '../api/types';
import { DATA_MODE_LABEL } from '../api/client';

export default function SearchBar({
  onSearch,
  presets,
  activeSlug,
  activeLabel,
  onSelectPreset,
  health,
  loading,
  sourceLabel,
}: {
  onSearch: (keyword: string) => void;
  presets: PresetItem[];
  activeSlug: string | null;
  activeLabel: string | null;
  onSelectPreset: (p: PresetItem) => void;
  health: Health | null;
  loading: boolean;
  sourceLabel: string | null;
}) {
  const [text, setText] = useState('');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const k = text.trim();
    if (k) onSearch(k);
  };

  return (
    <div className="searchbar">
      <form className="search-row" onSubmit={submit}>
        <input
          className="search-input"
          type="search"
          value={text}
          placeholder="输入检索关键词（需后端处于 remote/hybrid 模式），如：CRISPR gene editing"
          aria-label="检索关键词"
          onChange={(e) => setText(e.target.value)}
          disabled={loading}
        />
        <button type="submit" className="btn btn-primary" disabled={loading || !text.trim()}>
          {loading ? '加载中…' : '检索'}
        </button>
      </form>

      <div className="preset-row">
        <span className="preset-label">预置数据集</span>
        {presets.length === 0 ? (
          <span className="muted">预置列表暂不可用，请重试</span>
        ) : (
          presets.map((p) => (
            <button
              key={p.slug}
              type="button"
              className={`preset ${activeSlug === p.slug ? 'is-active' : ''}`}
              onClick={() => onSelectPreset(p)}
              disabled={loading}
              aria-current={activeSlug === p.slug}
            >
              {p.label}
              <span className="preset-sub">
                {p.fetched_count} 篇 · 指标 {(p.metrics_rate * 100).toFixed(0)}%
              </span>
            </button>
          ))
        )}
      </div>

      <div className="source-line-row">
        <span className="pill pill-info">数据来源：{sourceLabel ?? 'PubMed（NCBI E-utilities）'}</span>
        {activeLabel && <span className="muted">当前数据集：{activeLabel}</span>}
        {health && (
          <>
            <span className="muted">模式：{DATA_MODE_LABEL[health.data_mode] ?? health.data_mode}</span>
            <span className={`pill ${health.llm.available ? 'pill-ok' : 'pill-warn'}`}>
              AI 综述：{health.llm.available ? `可用（${health.llm.model ?? '未知模型'}）` : '不可用'}
            </span>
            <span className="muted">v{health.version}</span>
          </>
        )}
      </div>
    </div>
  );
}

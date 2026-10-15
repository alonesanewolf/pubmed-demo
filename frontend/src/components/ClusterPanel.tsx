import { useState } from 'react';
import type { Cluster } from '../api/types';
import { paletteOf } from '../lib/palette';
import { useTheme } from '../theme/ThemeProvider';
import { Card } from './ui';

export default function ClusterPanel({ clusters }: { clusters: Cluster[] }) {
  const { theme } = useTheme();
  const p = paletteOf(theme);
  const [expanded, setExpanded] = useState<number | null>(null);

  if (!clusters.length) {
    return (
      <Card title="研究方向聚类">
        <p className="muted">后端未返回聚类结果。可能原因：数据集未生成聚类，或样本量不足以聚类。</p>
      </Card>
    );
  }

  const total = clusters.reduce((a, c) => a + c.size, 0) || 1;

  return (
    <Card title="研究方向聚类" subtitle="按论文规模排序，点击展开代表文献标题">
      <div className="clusters">
        {clusters.map((c) => {
          const open = expanded === c.id;
          const share = (c.size / total) * 100;
          return (
            <article key={c.id} className="cluster" style={{ borderLeftColor: p.palette[c.id % p.palette.length] }}>
              <header className="cluster-head">
                <div>
                  <h3 className="cluster-label">
                    <span className="cluster-id" style={{ background: p.palette[c.id % p.palette.length] }}>
                      {c.id}
                    </span>
                    {c.label}
                    <span className={`tag tag-${c.label_source === 'llm' ? 'llm' : 'rule'}`}>
                      {c.label_source === 'llm' ? 'AI 命名' : '规则命名'}
                    </span>
                  </h3>
                  <p className="cluster-meta">
                    {c.size} 篇 · 占比 {share.toFixed(1)}%
                  </p>
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  aria-expanded={open}
                  onClick={() => setExpanded(open ? null : c.id)}
                >
                  {open ? '收起' : `代表文献 ${c.sample_titles.length}`}
                </button>
              </header>
              <div className="cluster-bar" aria-hidden="true">
                <div style={{ width: `${share}%`, background: p.palette[c.id % p.palette.length] }} />
              </div>
              <ul className="chips">
                {c.keywords.map((k) => (
                  <li key={k} className="chip">
                    {k}
                  </li>
                ))}
              </ul>
              {open && (
                <ol className="cluster-samples">
                  {c.sample_titles.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ol>
              )}
            </article>
          );
        })}
      </div>
    </Card>
  );
}

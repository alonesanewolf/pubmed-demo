/**
 * 概览卡片 + 期刊指标覆盖率进度条。
 * 覆盖率与 data_quality_note 如实展示：PubMed 官方 API 不提供 IF/分区，
 * 数据来自后端内置种子表，覆盖率低是已知情况，不能藏。
 */
import type { Dataset } from '../api/types';
import { Card } from './ui';

function coverageTone(rate: number): 'ok' | 'warn' | 'bad' {
  if (rate >= 0.85) return 'ok';
  if (rate >= 0.6) return 'warn';
  return 'bad';
}

export default function OverviewCards({ dataset }: { dataset: Dataset }) {
  const { total_count, fetched_count, year_range, metrics_coverage: cov, source } = dataset;
  const ratePct = cov.rate * 100;
  const tone = coverageTone(cov.rate);

  return (
    <div className="overview">
      <div className="stat-grid">
        <div className="stat">
          <span className="stat-label">PubMed 命中总数</span>
          <strong className="stat-value">{total_count.toLocaleString('zh-CN')}</strong>
          <span className="stat-sub">esearch 返回</span>
        </div>
        <div className="stat">
          <span className="stat-label">已抓取样本</span>
          <strong className="stat-value">{fetched_count.toLocaleString('zh-CN')}</strong>
          <span className="stat-sub">
            覆盖 {((fetched_count / Math.max(1, total_count)) * 100).toFixed(1)}%
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">年份跨度</span>
          <strong className="stat-value">
            {year_range.min}–{year_range.max}
          </strong>
          <span className="stat-sub">{year_range.max - year_range.min + 1} 年</span>
        </div>
      </div>

      <Card
        title="期刊指标覆盖率"
        subtitle="影响因子 / JCR / 中科院分区的覆盖情况"
        actions={<span className={`pill pill-${tone}`}>{ratePct.toFixed(1)}%</span>}
      >
        <div
          className={`progress progress-${tone}`}
          role="progressbar"
          aria-valuenow={Math.round(ratePct)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="期刊指标覆盖率"
        >
          <div className="progress-fill" style={{ width: `${Math.min(100, ratePct)}%` }} />
        </div>
        <p className="progress-legend">
          <span>
            已匹配 <strong>{cov.matched.toLocaleString('zh-CN')}</strong> / {cov.total_papers.toLocaleString('zh-CN')} 篇
          </span>
          <span>
            未收录 {(cov.total_papers - cov.matched).toLocaleString('zh-CN')} 篇（显示为 NA，不按 0 处理）
          </span>
        </p>
        {cov.unmatched_top.length > 0 && (
          <details className="unmatched">
            <summary>未收录最多的期刊（前 {cov.unmatched_top.length}）</summary>
            <table className="mini-table">
              <thead>
                <tr>
                  <th>期刊</th>
                  <th>篇数</th>
                  <th>原因</th>
                </tr>
              </thead>
              <tbody>
                {cov.unmatched_top.map((u) => (
                  <tr key={u.journal}>
                    <td>{u.journal}</td>
                    <td>{u.count}</td>
                    <td className="muted">{u.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
        <p className="note note-info">
          <strong>数据质量说明：</strong>
          {dataset.data_quality_note}
        </p>
        <p className="muted source-line">数据来源：{source}</p>
      </Card>
    </div>
  );
}

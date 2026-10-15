/**
 * 影响力 Top100 榜单。
 * 要点：
 *  - 列表接口不含摘要（契约如此），点行才 GET 单篇详情 —— 服务器只有 4Mbps 带宽。
 *  - if 为 null 一律显示 NA，不显示 0。
 *  - citations 后端恒为 null（PubMed 不提供被引数），列保留但显示 NA + tooltip 说明。
 */
import { useMemo, useState } from 'react';
import type { TopPaper } from '../api/types';
import { EmptyState } from './ui';

export type SortKey = 'rank' | 'if' | 'year' | 'journal' | 'cas' | 'jcr';

const COLUMNS: { key: SortKey; label: string; align?: 'right' }[] = [
  { key: 'rank', label: '排名', align: 'right' },
  { key: 'journal', label: '标题 / 期刊' },
  { key: 'if', label: 'IF', align: 'right' },
  { key: 'jcr', label: 'JCR' },
  { key: 'cas', label: '中科院' },
  { key: 'year', label: '年份', align: 'right' },
];

function ifCell(v: number | null): string {
  return v === null || v === undefined ? 'NA' : v.toFixed(1);
}

/** null 统一排末尾（与后端排序规则一致），不当作 0 参与比较 */
function cmp(a: string | number | null, b: string | number | null, dir: 1 | -1): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  if (typeof a === 'number' && typeof b === 'number') return (a - b) * dir;
  return String(a).localeCompare(String(b), 'zh-CN') * dir;
}

export default function TopPapersTable({
  papers,
  highlightPmid,
  onSelect,
}: {
  papers: TopPaper[];
  highlightPmid?: string | null;
  onSelect: (p: TopPaper) => void;
}) {
  // 默认按 IF 降序（与后端 top_papers 的口径一致），null 值自动沉底
  const [sortKey, setSortKey] = useState<SortKey>('if');
  const [dir, setDir] = useState<1 | -1>(-1);

  const sorted = useMemo(() => {
    const arr = [...papers];
    arr.sort((a, b) => {
      switch (sortKey) {
        case 'if':
          return cmp(a.if, b.if, dir);
        case 'year':
          return cmp(a.year, b.year, dir);
        case 'journal':
          return cmp(a.journal, b.journal, dir);
        case 'cas':
          return cmp(a.cas, b.cas, dir);
        case 'jcr':
          return cmp(a.jcr, b.jcr, dir);
        default:
          return (a.rank - b.rank) * dir;
      }
    });
    return arr;
  }, [papers, sortKey, dir]);

  if (!papers.length) {
    return (
      <EmptyState
        title="该数据集没有可排名的文献"
        hint="Top100 取自近 5 年、且后端有排序结果的记录。若数据集为空，请先用预设关键词加载一次。"
      />
    );
  }

  const toggle = (key: SortKey) => {
    if (key === sortKey) setDir((d) => (d === 1 ? -1 : 1));
    else {
      setSortKey(key);
      setDir(key === 'rank' ? 1 : -1);
    }
  };

  return (
    <div className="table-wrap">
      <table className="data-table">
        <caption className="sr-only">影响力 Top {papers.length} 榜单，可点击列头排序</caption>
        <thead>
          <tr>
            {COLUMNS.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={c.align === 'right' ? 'right' : undefined}
                aria-sort={sortKey === c.key ? (dir === 1 ? 'ascending' : 'descending') : 'none'}
              >
                <button type="button" className="th-btn" onClick={() => toggle(c.key)}>
                  {c.label}
                  <span className="sort-arrow">{sortKey === c.key ? (dir === 1 ? '▲' : '▼') : '⇅'}</span>
                </button>
              </th>
            ))}
            <th scope="col" className="right">
              引用数
              <span className="hint-dot" title="PubMed 官方 API 不提供被引次数，该列恒为 NA，并非数据缺失。">
                ?
              </span>
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((p) => {
            const isHi = highlightPmid === p.pmid;
            return (
              <tr
                key={p.pmid}
                id={`paper-row-${p.pmid}`}
                tabIndex={0}
                role="button"
                className={isHi ? 'row-hl' : undefined}
                onClick={() => onSelect(p)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onSelect(p);
                  }
                }}
              >
                <td className="right mono">{p.rank}</td>
                <td>
                  <div className="cell-title">{p.title}</div>
                  <div className="cell-sub">
                    {p.journal} · {p.year} · PMID {p.pmid}
                    {!p.has_abstract && <span className="tag tag-warn">无摘要</span>}
                  </div>
                </td>
                <td className={`right mono ${p.if === null ? 'na' : ''}`}>{ifCell(p.if)}</td>
                <td className={p.jcr ? '' : 'na'}>{p.jcr ?? 'NA'}</td>
                <td className={p.cas ? '' : 'na'}>{p.cas ?? 'NA'}</td>
                <td className="right mono">{p.year}</td>
                <td className="right mono na" title="PubMed 不提供被引次数">
                  NA
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * 文献详情抽屉：点行才拉摘要（列表接口不含摘要）。
 * 独立 loading/error 态，失败可在抽屉内重试，不影响列表。
 */
import { useEffect } from 'react';
import { getPaperDetail } from '../api/client';
import { useAsync } from '../hooks/useAsync';
import { ErrorState, Skeleton } from './ui';

export default function PaperDrawer({
  slug,
  pmid,
  onClose,
}: {
  slug: string;
  pmid: string | null;
  onClose: () => void;
}) {
  const { data, loading, error, reload } = useAsync(
    (_signal) => getPaperDetail(slug, pmid as string),
    [slug, pmid],
    { enabled: Boolean(pmid) },
  );

  useEffect(() => {
    if (!pmid) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    document.body.classList.add('no-scroll');
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.classList.remove('no-scroll');
    };
  }, [pmid, onClose]);

  if (!pmid) return null;

  return (
    <div className="drawer-mask" onClick={onClose} role="presentation">
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label="文献详情"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="drawer-head">
          <span className="drawer-pmid mono">PMID {pmid}</span>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose} aria-label="关闭">
            关闭 ✕
          </button>
        </header>
        <div className="drawer-body">
          {loading && <Skeleton rows={6} />}
          {error && <ErrorState message={error} onRetry={reload} />}
          {data && (
            <article className="paper">
              <h3 className="paper-title">{data.title}</h3>
              <dl className="paper-meta">
                <div>
                  <dt>期刊</dt>
                  <dd>
                    {data.journal}
                    {data.if !== null && <span className="muted">（IF {data.if.toFixed(1)}）</span>}
                  </dd>
                </div>
                <div>
                  <dt>分区</dt>
                  <dd>
                    JCR {data.jcr ?? 'NA'} · 中科院 {data.cas ?? 'NA'}
                  </dd>
                </div>
                <div>
                  <dt>年份</dt>
                  <dd>{data.year}</dd>
                </div>
                <div>
                  <dt>DOI</dt>
                  <dd>{data.doi ?? 'NA'}</dd>
                </div>
              </dl>

              <section>
                <h4>作者</h4>
                <p className="authors">{data.authors.length ? data.authors.join('、') : 'NA'}</p>
              </section>

              <section>
                <h4>摘要</h4>
                {data.abstract ? (
                  <p className="abstract">{data.abstract}</p>
                ) : (
                  <p className="muted">PubMed 未收录该文摘要（点击下方链接查看官方页面）。</p>
                )}
              </section>

              <section>
                <h4>MeSH 主题词</h4>
                {data.mesh_terms.length ? (
                  <ul className="chips">
                    {data.mesh_terms.map((t) => (
                      <li key={t} className="chip">
                        {t}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">NA</p>
                )}
              </section>

              {data.pubtypes.length > 0 && (
                <section>
                  <h4>文献类型</h4>
                  <ul className="chips">
                    {data.pubtypes.map((t) => (
                      <li key={t} className="chip">
                        {t}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <a className="btn btn-primary" href={data.pubmed_url} target="_blank" rel="noreferrer noopener">
                在 PubMed 打开
              </a>
            </article>
          )}
        </div>
      </aside>
    </div>
  );
}

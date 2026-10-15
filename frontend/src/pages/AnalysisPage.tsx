/**
 * 主分析页。每个区块自己拉数据、自己 loading/error —— 不做整页等待。
 * slug 存 URL query，刷新/分享能复现同一视图；带 slug 的深链也能直接生效。
 */
import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getDataset, getHealth, getPresets, isMockActive } from '../api/client';
import { request } from '../api/http';
import type { PresetItem, TopPaper } from '../api/types';
import { useAsync } from '../hooks/useAsync';
import ClusterPanel from '../components/ClusterPanel';
import OverviewCards from '../components/OverviewCards';
import PaperDrawer from '../components/PaperDrawer';
import ReviewPanel from '../components/ReviewPanel';
import SearchBar from '../components/SearchBar';
import TopPapersTable from '../components/TopPapersTable';
import { Card, EmptyState, ErrorState, Skeleton, SkeletonCard } from '../components/ui';

// ECharts 相关组件单独成 chunk，首屏不必等图表库
const ChartsSection = lazy(() => import('../components/ChartsSection'));
const WordCloudPanel = lazy(() => import('../components/WordCloudPanel'));

export default function AnalysisPage() {
  const [params, setParams] = useSearchParams();
  const slug = params.get('slug');

  const health = useAsync(() => getHealth(), []);
  const presets = useAsync(() => getPresets(), []);
  const dataset = useAsync(() => getDataset(slug as string), [slug], { enabled: Boolean(slug) });

  const [searchError, setSearchError] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [drawerPmid, setDrawerPmid] = useState<string | null>(null);

  const presetItems = useMemo<PresetItem[]>(() => presets.data?.items ?? [], [presets.data]);
  const active = useMemo(() => presetItems.find((p) => p.slug === slug) ?? null, [presetItems, slug]);

  // 首次进入若无 slug，自动加载第一个预置数据集，避免空屏
  useEffect(() => {
    if (!slug && presetItems.length && !presets.loading) {
      setParams({ slug: presetItems[0].slug }, { replace: true });
    }
  }, [slug, presetItems, presets.loading, setParams]);

  const selectPreset = useCallback(
    (p: PresetItem) => {
      setHighlight(null);
      setDrawerPmid(null);
      setSearchError(null);
      setParams({ slug: p.slug });
    },
    [setParams],
  );

  const search = useCallback(
    async (keyword: string) => {
      setSearchError(null);
      try {
        // 实时检索走 POST /api/search，成功后后端返回完整聚合数据。
        // 这里不落 slug（它是一次性结果），直接用返回值渲染。
        const ds = await request<import('../api/types').Dataset>('/search', {
          method: 'POST',
          body: { keyword, limit: 1000 },
        });
        setParams({});
        dataset.setData(ds);
      } catch (err) {
        setSearchError(err instanceof Error ? err.message : '检索失败');
      }
    },
    [dataset, setParams],
  );

  const jumpToPmid = useCallback((pmid: string) => {
    setHighlight(pmid);
  }, []);

  const ds = dataset.data;
  const showDatasetError = dataset.error && !ds;

  return (
    <div className="stack">
      <SearchBar
        onSearch={search}
        presets={presetItems}
        activeSlug={slug}
        activeLabel={ds?.label ?? active?.label ?? null}
        onSelectPreset={selectPreset}
        health={health.data}
        loading={dataset.loading}
        sourceLabel={isMockActive() ? 'Mock 假数据（契约一致）' : ds?.source || null}
      />

      {searchError && (
        <div className="note note-warn">
          <strong>实时检索未成功：</strong>
          {searchError}
          <span className="muted"> 后端当前可能为 local 模式（只读预置数据集），请改用上方预置标签查看分析结果。</span>
        </div>
      )}

      {showDatasetError && (
        <ErrorState
          message={`数据集加载失败：${dataset.error}`}
          onRetry={dataset.reload}
        />
      )}

      {!ds && dataset.loading && (
        <div className="stack">
          <SkeletonCard rows={4} />
          <SkeletonCard rows={6} />
        </div>
      )}

      {!ds && !dataset.loading && !dataset.error && (
        <Card title="开始分析">
          <EmptyState
            title="还没有选择数据集"
            hint="点击上方任一预置标签即可载入该领域的完整分析结果。"
          />
        </Card>
      )}

      {ds && (
        <>
          <OverviewCards dataset={ds} />

          <Suspense fallback={<SkeletonCard rows={6} />}>
            <ChartsSection dataset={ds} />
          </Suspense>

          <Card title="关键词词云" subtitle="颜色对应下方研究方向聚类；灰色为未归类词">
            {ds.wordcloud.length ? (
              <Suspense fallback={<Skeleton rows={4} height={220} />}>
                <WordCloudPanel words={ds.wordcloud} clusters={ds.clusters} />
              </Suspense>
            ) : (
              <EmptyState title="暂无词云数据" hint="数据集样本量不足或后端未生成关键词统计。" />
            )}
          </Card>

          <ClusterPanel clusters={ds.clusters} />

          <Card
            title={`影响力 Top ${ds.top_papers.length}`}
            subtitle="默认按影响因子降序，点击列头排序；点行查看详情。窗口为含最新年份的近 5 个自然年，窗口内不足 100 篇时按同规则用窗口外补齐，窗口内永远排在前面"
          >
            <TopPapersTable
              papers={ds.top_papers}
              highlightPmid={highlight}
              onSelect={(p: TopPaper) => setDrawerPmid(p.pmid)}
            />
          </Card>

          <ReviewPanel slug={ds.slug} keyword={ds.keyword} onJumpToPmid={jumpToPmid} />

          {slug && <PaperDrawer slug={slug} pmid={drawerPmid} onClose={() => setDrawerPmid(null)} />}
        </>
      )}
    </div>
  );
}

/**
 * 5 个统计图，全部 ECharts 柱/饼/环。
 * 本模块静态引用 echarts，所以由 AnalysisPage 用 React.lazy 异步加载：
 * 首屏只等概览卡片，图表 chunk 后到 —— 顺手解决体积问题。
 */
import { useMemo } from 'react';
import type { Dataset, JournalStatBucket, StatBucket } from '../api/types';
import { baseTooltip, paletteOf, useChart } from '../hooks/useChart';
import { useTheme } from '../theme/ThemeProvider';
import { Card, EmptyState } from './ui';
import type { EChartsCoreOption } from '../lib/echarts';

function ChartBox({ option, height = 280 }: { option: EChartsCoreOption; height?: number }) {
  const { ref } = useChart(option);
  return <div className="chart-box" ref={ref} style={{ height }} />;
}

function YearChart({ buckets }: { buckets: StatBucket[] }) {
  const { theme } = useTheme();
  const p = paletteOf(theme);
  const option = useMemo<EChartsCoreOption>(
    () => ({
      tooltip: { trigger: 'axis', ...baseTooltip(p), axisPointer: { type: 'shadow' } },
      grid: { left: 48, right: 16, top: 24, bottom: 52 },
      xAxis: {
        type: 'category',
        data: buckets.map((b) => b.key),
        axisLabel: {
          color: p.subText,
          rotate: buckets.length > 20 ? 60 : 0,
          fontSize: 10,
          interval: buckets.length > 20 ? 2 : 0,
        },
        axisLine: { lineStyle: { color: p.axisLine } },
      },
      yAxis: {
        type: 'value',
        name: '篇数',
        nameTextStyle: { color: p.subText, fontSize: 11 },
        axisLabel: { color: p.subText, fontSize: 10 },
        splitLine: { lineStyle: { color: p.splitLine } },
      },
      series: [
        {
          type: 'bar',
          name: '文献数',
          data: buckets.map((b) => b.count),
          itemStyle: { color: p.palette[0], borderRadius: [2, 2, 0, 0] },
          barMaxWidth: 18,
        },
      ],
    }),
    [buckets, p],
  );
  return <ChartBox option={option} />;
}

function JournalChart({ buckets }: { buckets: JournalStatBucket[] }) {
  const { theme } = useTheme();
  const p = paletteOf(theme);
  const top = useMemo(() => buckets.slice(0, 20).reverse(), [buckets]);
  const option = useMemo<EChartsCoreOption>(
    () => ({
      tooltip: {
        trigger: 'axis',
        ...baseTooltip(p),
        axisPointer: { type: 'shadow' },
        formatter: (params: unknown) => {
          const arr = params as { dataIndex: number }[];
          const i = arr[0]?.dataIndex ?? 0;
          const b = top[i];
          if (!b) return '';
          const ifTxt = b.if === null ? 'NA' : b.if.toFixed(1);
          return `${b.key}<br/>篇数：${b.count}<br/>IF：${ifTxt}　JCR：${b.jcr ?? 'NA'}　中科院：${b.cas ?? 'NA'}`;
        },
      },
      grid: { left: 150, right: 40, top: 12, bottom: 20 },
      xAxis: {
        type: 'value',
        axisLabel: { color: p.subText, fontSize: 10 },
        splitLine: { lineStyle: { color: p.splitLine } },
      },
      yAxis: {
        type: 'category',
        data: top.map((b) => (b.key.length > 22 ? `${b.key.slice(0, 21)}…` : b.key)),
        axisLabel: { color: p.subText, fontSize: 10 },
        axisLine: { lineStyle: { color: p.axisLine } },
      },
      series: [
        {
          type: 'bar',
          name: '篇数',
          data: top.map((b) => b.count),
          itemStyle: { color: p.palette[1], borderRadius: [0, 3, 3, 0] },
          barMaxWidth: 14,
        },
      ],
    }),
    [top, p],
  );
  return <ChartBox option={option} height={420} />;
}

function CasPie({ buckets }: { buckets: StatBucket[] }) {
  const { theme } = useTheme();
  const p = paletteOf(theme);
  const option = useMemo<EChartsCoreOption>(
    () => ({
      tooltip: { trigger: 'item', ...baseTooltip(p), formatter: '{b}：{c} 篇（{d}%）' },
      legend: { bottom: 0, textStyle: { color: p.subText, fontSize: 11 } },
      series: [
        {
          type: 'pie',
          radius: ['38%', '66%'],
          center: ['50%', '44%'],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: 'transparent', borderWidth: 1 },
          label: { color: p.text, fontSize: 11 },
          data: buckets.map((b, i) => ({
            name: b.key,
            value: b.count,
            itemStyle: { color: p.palette[i % p.palette.length] },
          })),
        },
      ],
    }),
    [buckets, p],
  );
  return <ChartBox option={option} height={300} />;
}

function IfBandChart({ buckets }: { buckets: StatBucket[] }) {
  const { theme } = useTheme();
  const p = paletteOf(theme);
  // 与后端 analysis.py 的 IF_BANDS 同序：先按影响因子从高到低，
  // 「无IF/未收录」固定压在最后 —— 它是没查到，不是影响因子低。
  const order = ['IF≥20', '10≤IF<20', '5≤IF<10', '3≤IF<5', '1≤IF<3', 'IF<1', '无IF/未收录'];
  const sorted = useMemo(() => {
    const map = new Map(buckets.map((b) => [b.key, b.count]));
    const known = order.map((k) => ({ key: k, count: map.get(k) ?? 0 })).filter(
      (b) => b.count > 0 || buckets.some((x) => x.key === b.key),
    );
    // 后端若新增了未知档位，追加在后面，避免数据被静默丢掉
    const extra = buckets.filter((b) => !order.includes(b.key));
    return [...known, ...extra];
  }, [buckets]);
  const option = useMemo<EChartsCoreOption>(
    () => ({
      tooltip: {
        trigger: 'axis',
        ...baseTooltip(p),
        axisPointer: { type: 'shadow' },
        formatter: (params: unknown) => {
          const arr = params as { name: string; value: number }[];
          const it = arr[0];
          const name = it.name === '无IF/未收录' ? '无IF/未收录（NA）' : it.name;
          return `${name}：${it.value} 篇`;
        },
      },
      grid: { left: 48, right: 16, top: 24, bottom: 44 },
      xAxis: {
        type: 'category',
        data: sorted.map((b) => b.key),
        axisLabel: {
          color: p.subText,
          fontSize: 10,
          interval: 0,
          rotate: sorted.length > 5 ? 22 : 0,
          formatter: (v: string) => (v === '无IF/未收录' ? '无IF\n(未收录)' : v),
        },
        axisLine: { lineStyle: { color: p.axisLine } },
      },
      yAxis: {
        type: 'value',
        name: '篇数',
        nameTextStyle: { color: p.subText, fontSize: 11 },
        axisLabel: { color: p.subText, fontSize: 10 },
        splitLine: { lineStyle: { color: p.splitLine } },
      },
      series: [
        {
          type: 'bar',
          data: sorted.map((b, i) => ({
            value: b.count,
            itemStyle: {
              color: b.key === '无IF/未收录' ? '#9aa5b4' : p.palette[i % p.palette.length],
              borderRadius: [2, 2, 0, 0],
            },
          })),
          barMaxWidth: 42,
        },
      ],
    }),
    [sorted, p],
  );
  return <ChartBox option={option} />;
}

function JcrDonut({ buckets }: { buckets: StatBucket[] }) {
  const { theme } = useTheme();
  const p = paletteOf(theme);
  const option = useMemo<EChartsCoreOption>(
    () => ({
      tooltip: { trigger: 'item', ...baseTooltip(p), formatter: '{b}：{c} 篇（{d}%）' },
      legend: { bottom: 0, textStyle: { color: p.subText, fontSize: 11 } },
      series: [
        {
          type: 'pie',
          radius: ['52%', '76%'],
          center: ['50%', '44%'],
          itemStyle: { borderColor: 'transparent', borderWidth: 1 },
          label: { color: p.text, fontSize: 11 },
          data: buckets.map((b, i) => ({
            name: b.key,
            value: b.count,
            itemStyle: { color: p.palette[(i + 4) % p.palette.length] },
          })),
        },
      ],
    }),
    [buckets, p],
  );
  return <ChartBox option={option} height={300} />;
}

export default function ChartsSection({ dataset }: { dataset: Dataset }) {
  const s = dataset.stats;
  const empty = (name: string) => (
    <EmptyState title={`后端未返回${name}聚合数据`} hint="这属于数据缺失而非前端故障，请检查数据集生成配置。" />
  );

  return (
    <div className="grid-2">
      <Card title="年份分布" subtitle={`${dataset.year_range.min} – ${dataset.year_range.max} 的发文量走势`}>
        {s.by_year.length ? <YearChart buckets={s.by_year} /> : empty('年份')}
      </Card>
      <Card title="期刊 Top 20" subtitle="按收录篇数排序（悬停查看该刊 IF / 分区）">
        {s.by_journal.length ? <JournalChart buckets={s.by_journal} /> : empty('期刊')}
      </Card>
      <Card title="中科院分区分布">
        {s.by_cas.length ? <CasPie buckets={s.by_cas} /> : empty('中科院分区')}
      </Card>
      <Card title="影响因子区间分布" subtitle="沿用后端 by_if_band 口径；灰色档为未收录期刊（NA），不等于 IF 很低">
        {s.by_if_band.length ? <IfBandChart buckets={s.by_if_band} /> : empty('影响因子区间')}
      </Card>
      <Card title="JCR 分区分布" className="span-2">
        {s.by_jcr.length ? <JcrDonut buckets={s.by_jcr} /> : empty('JCR 分区')}
      </Card>
    </div>
  );
}

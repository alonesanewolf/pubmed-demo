/**
 * 词云：颜色按 clusters[].id 分配色系，一眼能看出词属于哪个研究方向。
 * 没有归属聚类的词走中性灰，避免"看起来有含义其实没有"。
 */
import { useMemo } from 'react';
import type { Cluster, WordCloudWord } from '../api/types';
import { baseTooltip, paletteOf, useChart } from '../hooks/useChart';
import { useTheme } from '../theme/ThemeProvider';
import type { EChartsCoreOption } from '../lib/echarts';

export default function WordCloudPanel({
  words,
  clusters,
}: {
  words: WordCloudWord[];
  clusters: Cluster[];
}) {
  const { theme } = useTheme();
  const p = paletteOf(theme);

  const option = useMemo<EChartsCoreOption>(() => {
    const kwIndex = new Map<string, number>();
    clusters.forEach((c) => c.keywords.forEach((k) => kwIndex.set(k.toLowerCase(), c.id)));

    const data = words.slice(0, 150).map((w) => {
      const cid = kwIndex.get(w.word.toLowerCase());
      const base = cid === undefined ? '#8b98a9' : p.palette[cid % p.palette.length];
      return {
        name: w.word,
        value: w.weight,
        textStyle: { color: base },
        clusterId: cid ?? -1,
      };
    });

    return {
      tooltip: {
        ...baseTooltip(p),
        formatter: (params: unknown) => {
          const o = params as { name: string; value: number; dataIndex: number };
          const cid = (data[o.dataIndex] as { clusterId: number }).clusterId;
          const label = cid === -1 ? '未归入研究方向' : clusters[cid]?.label ?? '未归入研究方向';
          return `${o.name}<br/>词频权重：${o.value}<br/>所属方向：${label}`;
        },
      },
      series: [
        {
          type: 'wordCloud',
          shape: 'circle',
          sizeRange: [12, 52],
          rotationRange: [-45, 45],
          gridSize: 8,
          drawOutOfBound: false,
          textStyle: { fontFamily: 'system-ui, "Microsoft YaHei", sans-serif' },
          emphasis: { textStyle: { textBorderBlur: 2, textBorderWidth: 1 } },
          data,
        },
      ],
    };
  }, [words, clusters, p]);

  const { ref } = useChart(option);

  return (
    <div className="wordcloud-wrap">
      <div className="chart-box" ref={ref} style={{ height: 360 }} />
      <ul className="cloud-legend">
        {clusters.map((c) => (
          <li key={c.id}>
            <span className="dot" style={{ background: p.palette[c.id % p.palette.length] }} aria-hidden="true" />
            {c.label}
          </li>
        ))}
        <li>
          <span className="dot" style={{ background: '#8b98a9' }} aria-hidden="true" />
          未归类词
        </li>
      </ul>
    </div>
  );
}

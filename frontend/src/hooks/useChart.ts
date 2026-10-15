/**
 * ECharts 实例封装（引用 echarts 的模块 —— 只有图表区块才应该 import 它）。
 * option / 容器变化时增量更新；主题切换由调用方重算 option 触发。
 */
import { useCallback, useEffect, useRef } from 'react';
import { echarts, type EChartsCoreOption } from '../lib/echarts';
import { useTheme } from '../theme/ThemeProvider';
import { paletteOf, type ChartPalette } from '../lib/palette';

export { paletteOf };
export type { ChartPalette };

export function baseTooltip(p: ChartPalette): Record<string, unknown> {
  return {
    backgroundColor: p.tooltipBg,
    borderColor: p.tooltipBorder,
    borderWidth: 1,
    textStyle: { color: p.text, fontSize: 12 },
    extraCssText: 'box-shadow:0 6px 20px rgba(15,23,42,0.14);border-radius:6px;',
  };
}

export function useChart(option: EChartsCoreOption, deps: unknown[] = []) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const { theme } = useTheme();

  const render = useCallback(() => {
    if (!ref.current) return;
    if (!chartRef.current || chartRef.current.isDisposed()) {
      chartRef.current = echarts.init(ref.current, undefined, { renderer: 'canvas' });
    }
    chartRef.current.setOption(option, true);
  }, [option]);

  useEffect(() => {
    render();
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => chartRef.current?.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      chartRef.current?.dispose();
      chartRef.current = null;
    };
    // theme 参与依赖：切深浅色时 option 会被重算并重绘
  }, [render, theme, ...deps]);

  return { ref, rerender: render };
}

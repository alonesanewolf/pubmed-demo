/**
 * 图表配色：纯数据模块，不引用 echarts。
 * 单独拆出来是为了让 OverviewCards / ClusterPanel 这类首屏组件
 * 也能拿到同一套色板，而不会把 echarts 拖进首屏 chunk。
 */
export interface ChartPalette {
  text: string;
  subText: string;
  axisLine: string;
  splitLine: string;
  tooltipBg: string;
  tooltipBorder: string;
  palette: string[];
}

const LIGHT: ChartPalette = {
  text: '#1b2330',
  subText: '#6b7788',
  axisLine: '#d7dde6',
  splitLine: '#e8ecf2',
  tooltipBg: 'rgba(255,255,255,0.97)',
  tooltipBorder: '#d7dde6',
  palette: ['#2f6feb', '#4f9cf9', '#12a594', '#e6a23c', '#8a63d2', '#e0607e'],
};

const DARK: ChartPalette = {
  text: '#e8edf5',
  subText: '#94a3b8',
  axisLine: '#3a4658',
  splitLine: '#2a3444',
  tooltipBg: 'rgba(24,31,43,0.97)',
  tooltipBorder: '#3a4658',
  palette: ['#5b9bff', '#7cc0ff', '#2dd4bf', '#f5b041', '#a78bfa', '#f472b6'],
};

export function paletteOf(theme: 'light' | 'dark'): ChartPalette {
  return theme === 'dark' ? DARK : LIGHT;
}

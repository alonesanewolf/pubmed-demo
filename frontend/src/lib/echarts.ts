/**
 * ECharts 按需引入 + React 封装。
 *
 * 关键点：绝不使用 `import * as echarts from 'echarts'`（那是全量包 ~1MB）。
 * 这里只注册本项目真正用到的图表与组件，并由 ChartsSection 动态 import，
 * 保证 ECharts 落到独立 chunk，不计入首屏 JS。
 */
import * as echarts from 'echarts/core';
import { BarChart, PieChart } from 'echarts/charts';
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components';
import { LabelLayout } from 'echarts/features';
import { CanvasRenderer } from 'echarts/renderers';
import 'echarts-wordcloud';

echarts.use([
  BarChart,
  PieChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  LabelLayout,
  CanvasRenderer,
]);

export { echarts };
export type { EChartsCoreOption } from 'echarts/core';

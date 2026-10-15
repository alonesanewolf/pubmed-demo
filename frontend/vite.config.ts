import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// 前端所有接口都走相对路径 /api，开发期由 proxy 转发到后端，
// 生产期由后端或 nginx 同源托管 —— 代码里不出现任何域名。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const target = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000';

  return {
    plugins: [react()],
    server: {
      port: Number(env.VITE_PORT || 5173),
      strictPort: false,
      proxy: {
        '/api': {
          target,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      // ECharts 走动态 import，会被拆成独立 chunk，这里放宽单 chunk 体积告警。
      chunkSizeWarningLimit: 900,
    },
  };
});

import { useEffect, useState, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { isMockActive, USE_MOCK } from '../api/client';
import { useTheme } from '../theme/ThemeProvider';

export default function Layout({ children }: { children: ReactNode }) {
  const { theme, toggle } = useTheme();
  const loc = useLocation();
  const [mock, setMock] = useState(isMockActive());

  // mock 可能在运行期被自动回落切换，顶栏需要跟着变
  useEffect(() => {
    const t = window.setInterval(() => setMock(isMockActive()), 2000);
    return () => window.clearInterval(t);
  }, []);

  return (
    <div className="app">
      <header className="app-bar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <h1>PubMed 领域分析</h1>
            <p className="brand-sub">检索 · 统计 · 影响力排序 · AI 综述</p>
          </div>
        </div>
        <nav className="nav">
          <Link to="/" className={loc.pathname === '/' ? 'is-active' : ''}>
            主分析
          </Link>
          <Link to="/about" className={loc.pathname === '/about' ? 'is-active' : ''}>
            设计说明
          </Link>
        </nav>
        <div className="app-bar-right">
          {mock && (
            <span className="pill pill-warn" title={USE_MOCK ? 'VITE_USE_MOCK=true' : '后端不可达，已自动回落到 mock'}>
              数据来源：Mock
            </span>
          )}
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={toggle}
            aria-label={theme === 'light' ? '切换到深色模式' : '切换到浅色模式'}
          >
            {theme === 'light' ? '🌙 深色' : '☀ 浅色'}
          </button>
        </div>
      </header>
      <main className="app-main">{children}</main>
      <footer className="app-foot">
        PubMed 数据版权归 NCBI 所有；影响因子与分区来自后端内置期刊指标表，非 PubMed 官方数据。
      </footer>
    </div>
  );
}

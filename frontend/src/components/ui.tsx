import type { ReactNode } from 'react';

/** 通用卡片外壳：统一标题栏 / 边距 / 深浅色 */
export function Card({
  title,
  subtitle,
  actions,
  children,
  className = '',
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`.trim()}>
      {(title || actions) && (
        <header className="card-head">
          <div className="card-head-text">
            {title && <h2 className="card-title">{title}</h2>}
            {subtitle && <p className="card-subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      <div className="card-body">{children}</div>
    </section>
  );
}

/** 区块级 skeleton：单独占位，不让整页转圈 */
export function Skeleton({ rows = 3, height }: { rows?: number; height?: number }) {
  return (
    <div className="skeleton" aria-busy="true" aria-live="polite">
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="skeleton-row"
          style={{ height: height ?? (i === 0 ? 28 : 16), width: i === 0 ? '55%' : '100%' }}
        />
      ))}
    </div>
  );
}

export function SkeletonCard({ rows = 3 }: { rows?: number }) {
  return (
    <Card>
      <Skeleton rows={rows} />
    </Card>
  );
}

/** 错误态：可读文案 + 重试，不弹 alert */
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <span className="state-icon" aria-hidden="true">
        !
      </span>
      <p className="state-text">{message}</p>
      {onRetry && (
        <button type="button" className="btn btn-sm" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}

/** 空态：明确告诉用户发生了什么、下一步做什么 */
export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="state state-empty">
      <p className="state-text">{title}</p>
      {hint && <p className="state-hint">{hint}</p>}
      {action}
    </div>
  );
}

/**
 * AI 综述区。
 *
 * 三条硬性行为：
 *  1. 生成可能耗时 30~60 秒 → 需要明确的进度提示（阶段文字 + 耗时计时 + 取消）。
 *  2. degraded=true 是正常业务状态（HTTP 200）→ 显示提示条，页面其余部分照常工作，
 *     不弹错误对话框、不清空页面。
 *  3. 要点末尾的引用 PMID 可点击 → 跳到 Top100 表格对应行并高亮。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { generateReview } from '../api/client';
import { friendlyMessage } from '../api/http';
import type { Review } from '../api/types';
import { Card, ErrorState, Skeleton } from './ui';

type Stage = 'idle' | 'running' | 'done' | 'error';

const STAGE_TEXT: Record<string, string> = {
  running: '正在请求 AI 综述生成…',
  warning: '用时已超过 30 秒，通常还需 10~30 秒，请勿刷新页面',
  slow: '用时已超过 60 秒，仍在等待后端返回…',
};

/** 正文里的 [12345678,87654321] 渲染成可点角标 */
function CitationText({
  text,
  onJump,
}: {
  text: string;
  onJump: (pmid: string) => void;
}) {
  const parts = text.split(/(\[\d+(?:,\s*\d+)*\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const m = /^\[(\d+(?:,\s*\d+)*)\]$/.exec(part);
        if (!m) return <span key={i}>{part}</span>;
        return (
          <span key={i} className="cite-group">
            {m[1].split(',').map((n) => (
              <button key={n} type="button" className="cite" onClick={() => onJump(n.trim())}>
                {n.trim()}
              </button>
            ))}
          </span>
        );
      })}
    </>
  );
}

export default function ReviewPanel({
  slug,
  keyword,
  onJumpToPmid,
}: {
  slug: string;
  keyword: string;
  onJumpToPmid: (pmid: string) => void;
}) {
  const [review, setReview] = useState<Review | null>(null);
  const [stage, setStage] = useState<Stage>('idle');
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [extra, setExtra] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  // 切数据集时清空上一份综述，避免张冠李戴
  useEffect(() => {
    setReview(null);
    setStage('idle');
    setError(null);
    setExtra([]);
  }, [slug]);

  useEffect(() => {
    if (stage !== 'running') return;
    const t0 = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [stage]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const run = useCallback(async () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setStage('running');
    setError(null);
    setElapsed(0);
    try {
      const res = await generateReview({ slug, max_words: 500, language: 'zh' });
      if (ctrl.signal.aborted) return;
      setReview(res);
      setExtra(res.hallucinated_filtered ?? []);
      setStage('done');
    } catch (err) {
      if (ctrl.signal.aborted) return;
      setError(friendlyMessage(err));
      setStage('error');
    }
  }, [slug]);

  const jump = useCallback(
    (pmid: string) => {
      onJumpToPmid(pmid);
      const el = document.getElementById(`paper-row-${pmid}`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    },
    [onJumpToPmid],
  );

  const stageKey = elapsed > 60 ? 'slow' : elapsed > 30 ? 'warning' : 'running';

  return (
    <Card
      title="AI 中文综述"
      subtitle={`由大模型基于本数据集的统计聚合与 Top100 文献生成 · 关键词：${keyword}`}
    >
      {stage === 'idle' && (
        <div className="review-idle">
          <p>
            综述由后端调用大模型生成，约需 40–70 秒（实测 50–66 秒）。生成结果带引用角标，
            可点击跳转到下方 Top100 对应文献。
          </p>
          <button type="button" className="btn btn-primary" onClick={run}>
            生成 AI 综述
          </button>
        </div>
      )}

      {stage === 'running' && (
        <div className="review-loading" role="status" aria-live="polite">
          <div className="progress progress-info is-indeterminate">
            <div className="progress-fill" />
          </div>
          <p className="review-stage">{STAGE_TEXT[stageKey]}</p>
          <p className="muted">已用时 {elapsed}s · 期间可以继续浏览页面其他区块</p>
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => abortRef.current?.abort()}>
            取消
          </button>
        </div>
      )}

      {stage === 'error' && (
        <>
          <ErrorState message={error ?? '生成失败'} onRetry={run} />
          <p className="muted">统计图表、词云与 Top100 榜单不受影响，可正常使用。</p>
        </>
      )}

      {stage === 'done' && review && review.degraded && (
        <div className="note note-warn" role="status">
          <strong>AI 服务暂不可用，已降级为纯统计模式。</strong>
          {review.degraded_reason && <span> 原因：{review.degraded_reason}</span>}
          <span> 页面其余区块照常工作，可稍后重试。</span>
          <button type="button" className="btn btn-sm btn-ghost" onClick={run}>
            重试生成
          </button>
        </div>
      )}

      {stage === 'done' && review && !review.degraded && extra.length > 0 && (
        <p className="note note-info">已剔除 {extra.length} 个无效引用编号（{extra.join('、')}），避免模型编造引用。</p>
      )}

      {stage === 'done' && review && !review.degraded && review.sections.length === 0 && <Skeleton rows={4} />}

      {stage === 'done' && review && !review.degraded && review.sections.length > 0 && (
        <div className="review-body">
          <p className="muted review-foot">
            模型：{review.model ?? 'NA'} · 约 {review.word_count} 字 · 生成于{' '}
            {new Date(review.generated_at).toLocaleString('zh-CN')}
            {review.cost_estimate_cny !== null && ` · 预估成本 ¥${review.cost_estimate_cny.toFixed(3)}`}
          </p>
          {review.sections.map((s, i) => (
            <section key={i} className="review-point">
              <h4>{s.point}</h4>
              <p>
                <CitationText text={s.text} onJump={jump} />
              </p>
            </section>
          ))}
          {review.citations.length > 0 && (
            <details className="review-refs">
              <summary>引用文献（{review.citations.length}）</summary>
              <ol>
                {review.citations.map((c) => (
                  <li key={c.pmid}>
                    <button type="button" className="link" onClick={() => jump(c.pmid)}>
                      PMID {c.pmid}
                    </button>
                    <span className="muted">
                      {' '}
                      · {c.journal} · IF {c.if === null ? 'NA' : c.if.toFixed(1)}
                    </span>
                    <div className="muted ref-title">{c.title}</div>
                  </li>
                ))}
              </ol>
            </details>
          )}
        </div>
      )}
    </Card>
  );
}

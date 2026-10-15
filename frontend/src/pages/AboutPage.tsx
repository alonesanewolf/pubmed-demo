/**
 * 设计说明页。三块：竞品分析 / AI 工具使用思路 / 数据来源声明。
 * 后端 app/content/about.json 可能不存在（此时接口返回空数组），
 * 所以空态要给占位文案而不是白屏或崩。
 */
import { getAbout, getHealth } from '../api/client';
import type { AboutContent, AboutSection } from '../api/types';
import { useAsync } from '../hooks/useAsync';
import { Card, EmptyState, ErrorState, Skeleton } from '../components/ui';

function pickSections(content: AboutContent, keys: string[]): AboutSection[] {
  const out: AboutSection[] = [];
  for (const key of keys) {
    const v = content[key];
    if (Array.isArray(v)) out.push(...(v as AboutSection[]));
  }
  return out;
}

function SectionList({ sections, placeholder }: { sections: AboutSection[]; placeholder: string }) {
  if (!sections.length) {
    return <EmptyState title={placeholder} hint="该内容由后端 app/content/about.json 提供，文件存在后会自动渲染。" />;
  }
  return (
    <div className="about-list">
      {sections.map((s, i) => (
        <article key={i} className="about-item">
          {s.title && <h3>{s.title}</h3>}
          {s.body && <p>{s.body}</p>}
          {s.items && s.items.length > 0 && (
            <ul>
              {s.items.map((t, j) => (
                <li key={j}>{t}</li>
              ))}
            </ul>
          )}
        </article>
      ))}
    </div>
  );
}

export default function AboutPage() {
  const about = useAsync(() => getAbout(), []);
  const health = useAsync(() => getHealth(), []);

  const content: AboutContent = about.data ?? {};
  const competitors = Array.isArray(content.competitors) ? content.competitors : [];
  const aiSections = pickSections(content, ['ai_approach', 'ai_usage', 'ai_usage_notes']);
  const dataSections = pickSections(content, ['data_sources', 'data_source_note']);
  const generic = pickSections(content, ['sections']);

  return (
    <div className="stack">
      <h2 className="page-title">设计说明</h2>

      <Card title="竞品分析" subtitle="同类工具的取舍与本项目的定位">
        {about.loading && <Skeleton rows={3} />}
        {about.error && <ErrorState message={about.error} onRetry={about.reload} />}
        {!about.loading && !about.error && competitors.length === 0 && (
          <EmptyState
            title="竞品分析内容待补充"
            hint="后端 about.json 尚未提供 competitors 数组。示例结构见 frontend/README.md。"
          />
        )}
        {competitors.length > 0 && (
          <div className="grid-2">
            {competitors.map((c, i) => (
              <article key={i} className="competitor">
                <h3>{c.name}</h3>
                {c.tagline && <p className="muted">{c.tagline}</p>}
                {c.strengths && c.strengths.length > 0 && (
                  <>
                    <h4>优势</h4>
                    <ul>
                      {c.strengths.map((s, j) => (
                        <li key={j}>{s}</li>
                      ))}
                    </ul>
                  </>
                )}
                {c.weaknesses && c.weaknesses.length > 0 && (
                  <>
                    <h4>不足</h4>
                    <ul>
                      {c.weaknesses.map((s, j) => (
                        <li key={j}>{s}</li>
                      ))}
                    </ul>
                  </>
                )}
                {c.our_approach && (
                  <p className="note note-info">
                    <strong>本项目做法：</strong>
                    {c.our_approach}
                  </p>
                )}
              </article>
            ))}
          </div>
        )}
      </Card>

      <Card title="AI 工具使用思路" subtitle="AI 在本项目里承担什么、不承担什么">
        {about.loading && <Skeleton rows={3} />}
        {!about.loading && <SectionList sections={aiSections} placeholder="AI 使用思路待补充" />}
      </Card>

      <Card title="数据来源声明">
        {about.loading && <Skeleton rows={3} />}
        {!about.loading && <SectionList sections={dataSections} placeholder="数据来源声明待补充" />}
        {health.data && (
          <p className="muted">
            当前服务：{health.data.app} v{health.data.version} · 数据模式 {health.data.data_mode} · 预置数据集{' '}
            {health.data.preset_count} 个 · AI 综述模型 {health.data.llm.model ?? '未配置'}
          </p>
        )}
        <p className="note note-warn">
          影响因子与中科院分区<strong>不是 PubMed 提供的数据</strong>，来自后端内置的期刊指标种子表，
          覆盖率有限；未收录期刊一律显示 NA。
        </p>
      </Card>

      {generic.length > 0 && (
        <Card title="其他说明">
          <SectionList sections={generic} placeholder="" />
        </Card>
      )}
    </div>
  );
}

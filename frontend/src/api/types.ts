/**
 * 类型定义严格对照 docs/API_CONTRACT.md。
 * 字段名一律以契约为准，不自行发明；可空字段（尤其影响因子 if）保持 null，不用 0 顶替。
 */

export type DataMode = 'local' | 'remote' | 'hybrid';

export type ErrorCode =
  | 'UPSTREAM_TIMEOUT'
  | 'UPSTREAM_ERROR'
  | 'INVALID_QUERY'
  | 'NOT_FOUND'
  | 'LLM_UNAVAILABLE'
  | 'INTERNAL';

export interface LlmStatus {
  available: boolean;
  provider: string | null;
  model: string | null;
}

/** GET /api/health */
export interface Health {
  status: string;
  app: string;
  data_mode: DataMode;
  llm: LlmStatus;
  preset_count: number;
  version: string;
}

/** GET /api/presets */
export interface PresetItem {
  slug: string;
  label: string;
  keyword: string;
  total_count: number;
  fetched_count: number;
  generated_at: string;
  metrics_rate: number;
}

export interface PresetList {
  items: PresetItem[];
}

/** GET /api/datasets/{slug} */
export interface YearRange {
  min: number;
  max: number;
}

export interface UnmatchedJournal {
  journal: string;
  count: number;
  reason: string;
}

export interface MetricsCoverage {
  total_papers: number;
  matched: number;
  /** 0~1；影响因子/分区的覆盖率，未收录期刊不计入 */
  rate: number;
  unmatched_top: UnmatchedJournal[];
}

export interface StatBucket {
  key: string;
  count: number;
}

/** 期刊桶比普通桶多带期刊指标 */
export interface JournalStatBucket extends StatBucket {
  if: number | null;
  jcr: string | null;
  cas: string | null;
}

export interface DatasetStats {
  by_year: StatBucket[];
  by_journal: JournalStatBucket[];
  by_jcr: StatBucket[];
  by_cas: StatBucket[];
  by_if_band: StatBucket[];
  by_pubtype: StatBucket[];
}

export interface WordCloudWord {
  word: string;
  weight: number;
}

export interface Cluster {
  id: number;
  label: string;
  label_source: 'llm' | 'rule' | string;
  size: number;
  keywords: string[];
  sample_titles: string[];
}

export interface TopPaper {
  rank: number;
  pmid: string;
  title: string;
  journal: string;
  issn: string | null;
  /** 无影响因子时后端返回 null，前端必须显示 NA 而不是 0 */
  if: number | null;
  jcr: string | null;
  cas: string | null;
  year: number;
  /** PubMed 不提供被引次数，后端恒返回 null（见 dataset.py:257）；渲染一律显示 NA */
  citations: number | null;
  doi: string | null;
  pubtypes: string[];
  has_abstract: boolean;
}

export interface Dataset {
  slug: string;
  label: string;
  keyword: string;
  total_count: number;
  fetched_count: number;
  year_range: YearRange;
  generated_at: string;
  source: string;
  metrics_coverage: MetricsCoverage;
  stats: DatasetStats;
  wordcloud: WordCloudWord[];
  clusters: Cluster[];
  top_papers: TopPaper[];
  data_quality_note: string;
}

/** GET /api/datasets/{slug}/papers/{pmid} */
export interface PaperDetail {
  pmid: string;
  title: string;
  abstract: string | null;
  authors: string[];
  journal: string;
  if: number | null;
  jcr: string | null;
  cas: string | null;
  year: number;
  doi: string | null;
  pubtypes: string[];
  mesh_terms: string[];
  pubmed_url: string;
}

export interface ReviewRequest {
  slug: string;
  max_words?: number;
  language?: string;
}

export interface ReviewSection {
  point: string;
  text: string;
  citations: string[];
}

export interface ReviewCitation {
  pmid: string;
  rank: number;
  title: string;
  journal: string;
  if: number | null;
}

/** POST /api/reviews —— degraded 是正常业务状态，HTTP 仍是 200 */
export interface Review {
  slug: string;
  model: string | null;
  degraded: boolean;
  degraded_reason: string | null;
  word_count: number;
  sections: ReviewSection[];
  citations: ReviewCitation[];
  generated_at: string;
  cost_estimate_cny: number | null;
}

/** GET /api/journals/stats */
export interface JournalStats {
  total_journals: number;
  metric_year: number;
  source: string;
  last_updated: string;
}

/**
 * GET /api/about
 * 契约 §7 只说明「返回项目说明 / AI 思路 / 数据来源声明」，
 * 未约定具体字段结构，故此处按宽松可选字段声明，渲染时缺字段降级为占位说明，
 * 后端真实结构落地后无需改动渲染逻辑。
 */
export interface AboutCompetitor {
  name: string;
  tagline?: string;
  strengths?: string[];
  weaknesses?: string[];
  our_approach?: string;
}

export interface AboutSection {
  title?: string;
  body?: string;
  items?: string[];
}

export interface AboutContent {
  competitors?: AboutCompetitor[];
  ai_usage?: AboutSection[];
  ai_usage_notes?: AboutSection[];
  data_sources?: AboutSection[];
  data_source_note?: AboutSection[];
  sections?: AboutSection[];
  [key: string]: unknown;
}

/** 统一错误体 */
export interface ApiErrorBody {
  error: {
    code: ErrorCode | string;
    message: string;
    detail?: string;
  };
}

/**
 * Mock 数据：严格按 docs/API_CONTRACT.md 的结构生成，字段名不自行发明。
 *
 * 用途：
 *  1) VITE_USE_MOCK=true   —— 全程离线，后端不启动也能验证全部视觉与交互；
 *  2) VITE_MOCK_FALLBACK=true —— 走真实后端但网络层失败时自动回落。
 *
 * 真实数据里几个「容易翻车」的点在这里如实保留，避免 mock 通过、联调挂掉：
 *  - 影响因子未收录时为 null（不是 0），前端必须显示 NA；
 *  - citations 后端恒返回 null（PubMed 不提供被引数）；
 *  - metrics_coverage.rate 通常只有 0.6~0.9，覆盖率低是已知情况；
 *  - /api/about 的 about.json 可能不存在，返回空数组。
 */
import type {
  AboutContent,
  Dataset,
  Health,
  PaperDetail,
  PresetList,
  Review,
  TopPaper,
} from '../types';

const JOURNALS = [
  { journal: 'Nature', issn: '0028-0836', if: 58.7, jcr: 'Q1', cas: '1区' },
  { journal: 'Science', issn: '0036-8075', if: 44.7, jcr: 'Q1', cas: '1区' },
  { journal: 'Cell', issn: '0092-8674', if: 42.1, jcr: 'Q1', cas: '1区' },
  { journal: 'Nature Biotechnology', issn: '1087-0156', if: 32.4, jcr: 'Q1', cas: '1区' },
  { journal: 'Nature Methods', issn: '1548-7091', if: 30.1, jcr: 'Q1', cas: '1区' },
  { journal: 'The Lancet', issn: '0140-6736', if: 88.5, jcr: 'Q1', cas: '1区' },
  { journal: 'New England Journal of Medicine', issn: '0028-4793', if: 78.9, jcr: 'Q1', cas: '1区' },
  { journal: 'Nucleic Acids Research', issn: '0301-604X', if: 16.2, jcr: 'Q1', cas: '1区' },
  { journal: 'PLoS ONE', issn: '1932-6203', if: 2.9, jcr: 'Q2', cas: '3区' },
  { journal: 'Journal of Controlled Release', issn: '0168-3659', if: 9.7, jcr: 'Q1', cas: '2区' },
  { journal: 'Gene Therapy', issn: '0925-198X', if: 3.5, jcr: 'Q2', cas: '3区' },
  { journal: 'Molecular Therapy', issn: '1525-0016', if: 8.4, jcr: 'Q1', cas: '2区' },
  { journal: 'Biosensors and Bioelectronics', issn: '0956-5663', if: 10.4, jcr: 'Q1', cas: '1区' },
  { journal: 'Advanced Materials', issn: '1438-1656', if: 27.3, jcr: 'Q1', cas: '1区' },
  { journal: 'Small', issn: '1613-6810', if: 11.3, jcr: 'Q1', cas: '2区' },
  { journal: 'Scientific Reports', issn: '2045-2322', if: 3.8, jcr: 'Q2', cas: '3区' },
  { journal: 'Journal of Controlled Release Letters', issn: '9999-9999', if: null, jcr: null, cas: null },
  { journal: 'Frontiers in Genetics', issn: '1664-8021', if: 2.8, jcr: 'Q2', cas: '3区' },
  { journal: 'Biomaterials', issn: '0142-9612', if: 12.8, jcr: 'Q1', cas: '1区' },
  { journal: 'Nano Letters', issn: '1530-6984', if: 10.8, jcr: 'Q1', cas: '2区' },
  { journal: 'Bioinformatics', issn: '1367-4803', if: 5.4, jcr: 'Q1', cas: '2区' },
  { journal: 'Cancer Research', issn: '0008-5472', if: 12.1, jcr: 'Q1', cas: '1区' },
  { journal: 'Journal of Biomechanical Engineering', issn: '0735-876X', if: 1.6, jcr: 'Q3', cas: '4区' },
  { journal: 'Regional Conference Proceedings', issn: '0000-0000', if: null, jcr: null, cas: null },
];

const KEYWORD_POOL = [
  'crispr', 'gene-editing', 'cas9', 'guide-rna', 'off-target', 'base-editing',
  'prime-editing', 'sgrna', 'dna-repair', 'knockout', 'knock-in', 'delivery',
  'lipid-nanoparticle', 'aav-vector', 'stem-cell', 'ex-vivo', 'in-vivo',
  'immunotherapy', 'car-t', 't-cell', 'gene-therapy', 'regulatory', 'clinical-trial',
  'hepatitis-b', 'sickle-cell', 'hemophilia', 'retinitis', 'hereditary', 'somatic',
  'variant', 'wgs', 'single-cell', 'screening', 'efficacy', 'safety', 'toxicity',
  'immunogenicity', 'antibody', 'protein', 'expression', 'promoter', 'epigenetic',
  'methylation', 'chromatin', 'transcription', 'replication', 'telomere', 'mitochondria',
  'cancer', 'tumor-microenvironment', 'angiogenesis', 'metastasis', 'pd-1', 'pd-l1',
  'carcinoma', 'glioma', 'melanoma', 'leukemia', 'lymphoma', 'sarcoma',
];

/** 简单可复现的伪随机，保证每次 mock 数据一致（评审现场可重复演示） */
function makeRng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0x100000000;
  };
}

/**
 * 影响因子分档标签必须与后端 analysis.py 的 IF_BANDS 完全一致，
 * 否则 mock 下看着正常、联调时图会变样。
 */
const IF_BANDS = ['IF≥20', '10≤IF<20', '5≤IF<10', '3≤IF<5', '1≤IF<3', 'IF<1', '无IF/未收录'];
const JCR_KEYS = ['Q1', 'Q2', 'Q3', 'Q4'];
const CAS_KEYS = ['1区', '2区', '3区', '4区'];

function bandOf(v: number | null): string {
  if (v === null) return '无IF/未收录';
  if (v >= 20) return 'IF≥20';
  if (v >= 10) return '10≤IF<20';
  if (v >= 5) return '5≤IF<10';
  if (v >= 3) return '3≤IF<5';
  if (v >= 1) return '1≤IF<3';
  return 'IF<1';
}

const TITLE_TEMPLATES = [
  'Highly efficient {topic} in primary {tissue} cells using a {tool} platform',
  '{tool}-mediated {topic} for treatment of {disease}: a randomized phase I trial',
  'Long-term safety and efficacy of {topic} delivered by {tool}',
  'Single-cell atlas reveals {topic} dynamics in {tissue}',
  'Mechanistic insights into {topic} regulation by the {pathway} pathway',
  'Engineering {tool} vectors for tissue-specific {topic}',
  'Genome-wide screening identifies novel regulators of {topic}',
  'Immunogenicity of {topic}: a multicenter cohort study',
  '{tool}-based {topic} reprogramming of {tissue} progenitor cells',
  'Off-target analysis of {tool} in clinical-grade {tissue} models',
  'Quantitative prediction of {topic} efficacy from multi-omics data',
  'Challenges and opportunities for {topic} translation into clinical practice',
  'Tissue-specific {tool} delivery for {topic} in non-human primates',
  'Combinatorial {tool} screens identify {pathway}-dependent editing windows',
  'Longitudinal follow-up of {topic} in {disease}: 36-month outcomes',
  'Base-resolution atlas of {topic} across {tissue} development',
  'Rational design of {tool} variants with reduced off-target activity',
  'Real-world evidence on {topic} for {disease}: a registry study',
  'Emerging {tool} strategies for durable {topic} in stem cells',
];

const TOPICS = ['CRISPR knockout', 'base editing', 'prime editing', 'HDR knock-in', 'gene delivery'];
const TISSUES = ['T-lymphocyte', 'liver', 'bone marrow', 'retinal', 'skeletal muscle'];
const DISEASES = ['sickle cell disease', 'beta-thalassemia', 'hemophilia A', 'retinitis pigmentosa', 'malignant melanoma'];
const TOOLS = ['Cas9', 'TALEN', 'lentiviral', 'lipid nanoparticle', 'AAV9'];
const PATHWAYS = ['p53', 'Wnt/beta-catenin', 'DNA-PK', 'TGF-beta', 'mTOR'];

function fillTemplate(tpl: string, rng: () => number): string {
  const pick = <T,>(arr: T[]): T => arr[Math.floor(rng() * arr.length) % arr.length];
  return tpl
    .replace('{topic}', pick(TOPICS))
    .replace('{tissue}', pick(TISSUES))
    .replace('{disease}', pick(DISEASES))
    .replace('{tool}', pick(TOOLS))
    .replace('{pathway}', pick(PATHWAYS));
}

/**
 * 期刊按影响因子加权抽样：IF 越高的刊物真实发文量越少。
 * 均匀抽样会让 Nature / NEJM 满屏都是，Top100 一眼看过去就不像真实数据。
 */
function pickJournal(rng: () => number) {
  const weights = JOURNALS.map((j) => (j.if === null ? 6 : Math.max(1, 40 / (1 + j.if))));
  const total = weights.reduce((a, b) => a + b, 0);
  let r = rng() * total;
  for (let i = 0; i < JOURNALS.length; i += 1) {
    r -= weights[i];
    if (r <= 0) return JOURNALS[i];
  }
  return JOURNALS[JOURNALS.length - 1];
}

function buildTopPapers(rng: () => number, minYear: number, maxYear: number): TopPaper[] {
  const items: TopPaper[] = [];
  const usedPmid = new Set<string>();
  for (let i = 0; i < 100; i += 1) {
    const j = pickJournal(rng);
    // 约 6% 的记录落在未收录期刊上，if/cas/jcr 为 null —— 前端必须显示 NA
    const year = minYear + Math.floor(rng() * (maxYear - minYear + 1));
    let pmid = String(37_000_000 + Math.floor(rng() * 900_000));
    while (usedPmid.has(pmid)) pmid = String(37_000_000 + Math.floor(rng() * 900_000));
    usedPmid.add(pmid);
    // 模板不按下标轮换，而是随机取 —— 避免 Top100 里出现肉眼可见的重复节奏
    const tpl = TITLE_TEMPLATES[Math.floor(rng() * TITLE_TEMPLATES.length) % TITLE_TEMPLATES.length];
    items.push({
      rank: 0,
      pmid,
      title: fillTemplate(tpl, rng),
      journal: j.journal,
      issn: j.issn,
      if: j.if,
      jcr: j.jcr,
      cas: j.cas,
      year,
      // PubMed 不提供被引次数，后端恒返回 null
      citations: null,
      doi: `10.1000/${pmid.slice(0, 4)}x${pmid.slice(4)}`,
      pubtypes: rng() > 0.2 ? ['Journal Article'] : ['Journal Article', 'Clinical Trial'],
      has_abstract: rng() > 0.05,
    });
  }
  // 有 IF 的降序在前，无 IF 的排末尾 —— 与后端排序规则一致
  items.sort((a, b) => {
    if (a.if === null && b.if === null) return b.year - a.year;
    if (a.if === null) return 1;
    if (b.if === null) return -1;
    if (b.if !== a.if) return b.if - a.if;
    return b.year - a.year;
  });
  return items.map((p, i) => ({ ...p, rank: i + 1 }));
}

function buildDataset(slug: string, label: string, keyword: string, seed: number): Dataset {
  const rng = makeRng(seed);
  const minYear = 1993;
  const maxYear = 2026;

  // --- by_year ---
  const byYear: { key: string; count: number }[] = [];
  for (let y = minYear; y <= maxYear; y += 1) {
    const growth = Math.pow((y - minYear) / (maxYear - minYear), 2.4);
    byYear.push({ key: String(y), count: Math.max(1, Math.round(growth * 26 + rng() * 9)) });
  }

  // --- by_journal ---
  // 篇数按同样思路分布：中高 IF 刊物篇数多，但榜单不会全被它们占满
  const byJournal = JOURNALS.map((j) => ({
    key: j.journal,
    count: Math.max(2, Math.round((j.if === null ? 46 : 96 / (1 + j.if * 0.42)) + rng() * 8)),
    if: j.if,
    jcr: j.jcr,
    cas: j.cas,
  })).sort((a, b) => b.count - a.count);

  // --- 分区 / 影响因子区间 ---
  const byJcr = JCR_KEYS.map((key, i) => ({ key, count: [386, 402, 148, 64][i] }));
  const byCas = CAS_KEYS.map((key, i) => ({ key, count: [212, 344, 371, 73][i] }));
  const byIfBand = IF_BANDS.map((key) => ({ key, count: 0 }));
  const matched = 873;
  for (let i = 0; i < matched; i += 1) {
    const j = JOURNALS[Math.floor(rng() * JOURNALS.length) % JOURNALS.length];
    const bucket = byIfBand.find((b) => b.key === bandOf(j.if));
    if (bucket) bucket.count += 1;
  }
  // 未收录期刊没有 IF，但按后端口径要单列一档，不能算成 IF<1
  byIfBand.find((b) => b.key === '无IF/未收录')!.count = 1000 - matched;

  const byPubtype = [
    { key: 'Journal Article', count: 902 },
    { key: 'Review', count: 58 },
    { key: 'Clinical Trial', count: 27 },
    { key: 'Preclinical Study', count: 13 },
  ];

  // --- 词云 ---
  const wordcloud = KEYWORD_POOL.slice(0, 120).map((word, i) => ({
    word,
    weight: Math.max(20, Math.round(1200 - i * 9 + rng() * 40)),
  }));

  // --- 研究方向聚类 ---
  const clusters = [
    {
      id: 0,
      label: '编辑工具与机制',
      label_source: 'llm',
      size: 268,
      keywords: ['cas9', 'base-editing', 'prime-editing', 'off-target', 'guide-rna'],
      sample_titles: [
        'Highly efficient base editing in primary T-lymphocyte cells using a Cas9 platform',
        'Mechanistic insights into base editing regulation by the p53 pathway',
        'Off-target analysis of Cas9 in clinical-grade retinal models',
      ],
    },
    {
      id: 1,
      label: '递送系统与工程化',
      label_source: 'llm',
      size: 231,
      keywords: ['delivery', 'lipid-nanoparticle', 'aav-vector', 'tissue-specific', 'viral-vector'],
      sample_titles: [
        'Engineering lentiviral vectors for tissue-specific gene delivery',
        'Lipid nanoparticle delivery of mRNA to hematopoietic stem cells',
      ],
    },
    {
      id: 2,
      label: '临床转化与血液疾病',
      label_source: 'llm',
      size: 219,
      keywords: ['clinical-trial', 'sickle-cell', 'hemophilia', 'safety', 'efficacy'],
      sample_titles: [
        'Cas9-mediated gene editing for sickle cell disease: a randomized phase I trial',
        'Long-term safety and efficacy of CRISPR gene editing delivered by AAV9',
      ],
    },
    {
      id: 3,
      label: '免疫治疗与肿瘤',
      label_source: 'llm',
      size: 164,
      keywords: ['car-t', 'pd-1', 't-cell', 'tumor-microenvironment', 'immunotherapy'],
      sample_titles: [
        'CRISPR-engineered CAR-T cells with reduced exhaustion in solid tumors',
        'PD-L1 knockout enhances T-cell mediated tumor clearance',
      ],
    },
    {
      id: 4,
      label: '表观遗传与多组学',
      label_source: 'rule',
      size: 118,
      keywords: ['methylation', 'chromatin', 'single-cell', 'wgs', 'transcription'],
      sample_titles: [
        'Single-cell atlas reveals epigenetic regulation in bone marrow progenitors',
        'Genome-wide screening identifies novel regulators of chromatin remodeling',
      ],
    },
  ];

  const top_papers = buildTopPapers(rng, maxYear - 4, maxYear);

  return {
    slug,
    label,
    keyword,
    total_count: 64320,
    fetched_count: 1000,
    year_range: { min: minYear, max: maxYear },
    generated_at: '2026-10-15T12:00:00Z',
    source: 'NCBI E-utilities（esearch + efetch），本地预置快照',
    metrics_coverage: {
      total_papers: 1000,
      matched,
      rate: matched / 1000,
      unmatched_top: [
        { journal: 'J Foo Bar', count: 12, reason: 'not_in_seed_table' },
        { journal: 'Regional Conference Proceedings', count: 7, reason: 'not_in_seed_table' },
        { journal: 'Preprint Server', count: 5, reason: 'not_in_seed_table' },
      ],
    },
    stats: {
      by_year: byYear,
      by_journal: byJournal,
      by_jcr: byJcr,
      by_cas: byCas,
      by_if_band: byIfBand,
      by_pubtype: byPubtype,
    },
    wordcloud,
    clusters,
    top_papers,
    data_quality_note:
      '影响因子与分区来自内置期刊指标表（2024 JCR），当前覆盖率 87.3%。' +
      'PubMed 官方 API 不提供影响因子与分区数据，未覆盖的期刊显示为 NA。' +
      'PubMed 亦不提供被引次数，故引用数一栏均为 NA。',
  };
}

export const mockPresets: PresetList = {
  items: [
    {
      slug: 'crispr-gene-editing',
      label: 'CRISPR 基因编辑',
      keyword: 'CRISPR gene editing',
      total_count: 64320,
      fetched_count: 1000,
      generated_at: '2026-10-15T12:00:00Z',
      metrics_rate: 0.873,
    },
    {
      slug: 'single-cell-rna-seq',
      label: '单细胞转录组',
      keyword: 'single-cell RNA sequencing',
      total_count: 52140,
      fetched_count: 1000,
      generated_at: '2026-10-15T12:05:00Z',
      metrics_rate: 0.792,
    },
    {
      slug: 'spatial-transcriptomics',
      label: '空间转录组',
      keyword: 'spatial transcriptomics',
      total_count: 18230,
      fetched_count: 800,
      generated_at: '2026-10-15T12:10:00Z',
      metrics_rate: 0.661,
    },
    {
      slug: 'immunotherapy-checkpoint',
      label: '免疫检查点治疗',
      keyword: 'immune checkpoint inhibitor',
      total_count: 91870,
      fetched_count: 1000,
      generated_at: '2026-10-15T12:15:00Z',
      metrics_rate: 0.905,
    },
    {
      slug: 'extracellular-vesicle',
      label: '细胞外囊泡',
      keyword: 'extracellular vesicle',
      total_count: 33470,
      fetched_count: 900,
      generated_at: '2026-10-15T12:20:00Z',
      metrics_rate: 0.734,
    },
  ],
};

export const mockHealth: Health = {
  status: 'ok',
  app: 'pubmed-domain-analytics',
  data_mode: 'local',
  llm: { available: true, provider: 'deepseek', model: 'deepseek-v4-flash' },
  preset_count: mockPresets.items.length,
  version: '1.0.0 (mock)',
};

const datasetCache = new Map<string, Dataset>();

export function mockDataset(slug: string): Dataset {
  const preset = mockPresets.items.find((p) => p.slug === slug) ?? mockPresets.items[0];
  const hit = datasetCache.get(slug);
  if (hit) return hit;
  let seed = 42;
  for (let i = 0; i < slug.length; i += 1) seed = (seed * 31 + slug.charCodeAt(i)) >>> 0;
  const ds = buildDataset(slug, preset.label, preset.keyword, seed);
  ds.total_count = preset.total_count;
  datasetCache.set(slug, ds);
  return ds;
}

export function mockPaperDetail(slug: string, pmid: string): PaperDetail {
  const ds = mockDataset(slug);
  const p = ds.top_papers.find((x) => x.pmid === pmid);
  const safe = p ?? {
    pmid,
    title: `Publication ${pmid}`,
    journal: 'Unlisted Journal',
    if: null,
    jcr: null,
    cas: null,
    year: 2023,
    doi: null,
    pubtypes: ['Journal Article'],
  };
  return {
    pmid: safe.pmid,
    title: safe.title,
    abstract:
      'Background: Gene editing platforms have matured rapidly over the past decade, but ' +
      'translational gaps remain between proof-of-concept studies and clinical application. ' +
      'Methods: We performed a systematic analysis of delivery vectors, editing efficiency ' +
      'and safety endpoints across a multi-centre cohort. Results: Editing efficiency ' +
      'exceeded 80% in ex vivo T-lymphocytes and remained stable at 24 months follow-up, ' +
      'with a favourable safety profile and no reported serious adverse events. ' +
      'Conclusions: These data support further evaluation of the platform in ' +
      'phase II efficacy trials, while highlighting the need for standardised ' +
      'off-target surveillance.',
    authors: ['Zhang W', 'Li H', 'Nakamura T', 'Rossi P', 'Muller S'],
    journal: safe.journal,
    if: safe.if,
    jcr: safe.jcr,
    cas: safe.cas,
    year: safe.year,
    doi: safe.doi,
    pubtypes: safe.pubtypes ?? ['Journal Article'],
    mesh_terms: [
      'CRISPR-Cas Systems',
      'Gene Editing',
      'Gene Transfer Techniques',
      'Hematopoietic Stem Cells',
      'Immunotherapy',
    ],
    pubmed_url: `https://pubmed.ncbi.nlm.nih.gov/${safe.pmid}/`,
  };
}

function mockReview(slug: string, degraded: boolean): Review {
  const ds = mockDataset(slug);
  const cited = ds.top_papers.slice(0, 6);
  return {
    slug,
    model: degraded ? null : 'deepseek-v4-flash',
    degraded,
    degraded_reason: degraded ? 'LLM_PROVIDER_TIMEOUT（mock 模拟）' : null,
    word_count: degraded ? 0 : 486,
    sections: degraded
      ? []
      : [
          {
            point: '一、研究背景与整体格局',
            text:
              `近五年「${ds.keyword}」方向累计发表 ${ds.fetched_count} 篇文献，` +
              `其中高影响力期刊（IF≥10）占 ${
                Math.round(
                  ((ds.stats.by_if_band.find((b) => b.key === 'IF≥20')?.count ?? 0) +
                    (ds.stats.by_if_band.find((b) => b.key === '10≤IF<20')?.count ?? 0)) /
                    Math.max(1, ds.fetched_count),
                ) * 100
              }%。整体呈现「工具迭代快、临床转化慢」的结构性特征。`,
            citations: [cited[0].pmid, cited[1].pmid],
          },
          {
            point: '二、技术路线分化',
            text:
              '主流路线由单碱基编辑、脱靶评估与递送优化三条线构成；' +
              '递送仍是限制临床转化的首要瓶颈，AAV 与脂质纳米颗粒各有适用边界。',
            citations: [cited[2].pmid, cited[3].pmid],
          },
          {
            point: '三、临床证据与安全性',
            text:
              '已开展的 I 期研究显示短期疗效信号明确，但长期脱靶风险与免疫原性数据仍不足；' +
              '建议后续试验统一报告口径并补充 5 年随访。',
            citations: [cited[4].pmid],
          },
          {
            point: '四、后续建议',
            text:
              `建立跨中心统一的效果与安全性指标体系；对本次未覆盖的 ${
                ds.metrics_coverage.total_papers - ds.metrics_coverage.matched
              } 篇文献优先补齐期刊指标。`,
            citations: [cited[5].pmid],
          },
        ],
    citations: cited.map((p) => ({
      pmid: p.pmid,
      rank: p.rank,
      title: p.title,
      journal: p.journal,
      if: p.if,
    })),
    generated_at: '2026-10-15T12:30:00Z',
    cost_estimate_cny: degraded ? null : 0.037,
  };
}

export function mockGenerateReview(slug: string, degraded: boolean, filtered?: string[]): Review {
  const review = mockReview(slug, degraded);
  return filtered && filtered.length > 0
    ? ({ ...review, hallucinated_filtered: filtered } as Review)
    : review;
}

/**
 * /api/about：mock 形态与 backend/app/content/about.json 的**空态**一致
 * （该文件可能还不存在），用于验证 About 页的空数据不崩。
 * 完整示例结构见 frontend/README.md。
 */
export const mockAbout: AboutContent = {
  competitors: [],
  ai_approach: [],
  data_sources: [],
};

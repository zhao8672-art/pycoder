/**
 * F5 代码审查 API 封装
 *
 * 调用后端 `/api/review/*` 系列端点，统一处理 fetch、错误、JSON 解析。
 */

import { getApiBase } from './config';

// ═══════════════════════════════════════════════════════════
// 类型定义
// ═══════════════════════════════════════════════════════════

export interface ReviewIssue {
  file_path: string;
  line_start: number;
  line_end: number;
  severity: 'info' | 'warning' | 'error' | 'critical';
  category: 'security' | 'perf' | 'style' | 'bug' | 'best-practice';
  message: string;
  suggestion: string;
  fix_patch: string;
}

export interface ReviewStats {
  by_severity: Record<string, number>;
  by_category: Record<string, number>;
}

export interface ReviewResult {
  overall_score: number;
  summary: string;
  issues: ReviewIssue[];
  stats: ReviewStats;
  truncated: boolean;
}

export interface FileInput {
  path: string;
  content: string;
}

export interface RunReviewOptions {
  diff?: string;
  files?: FileInput[];
  max_files?: number;
  include_static?: boolean;
  include_llm?: boolean;
  scan_dependencies?: boolean;
}

export interface FixResult {
  success: boolean;
  patch: string;
  applied_preview: {
    file_path: string;
    added: number;
    removed: number;
    changed: boolean;
  };
}

export interface PrReviewOptions {
  owner: string;
  repo: string;
  pr_number: number;
  max_files?: number;
  auto_comment?: boolean;
}

export interface PrReviewResult {
  success: boolean;
  result: ReviewResult | null;
  comment_posted?: boolean;
  comment_url?: string;
  message?: string;
}

// ═══════════════════════════════════════════════════════════
// 内部辅助
// ═══════════════════════════════════════════════════════════

async function _post<T>(path: string, body: unknown): Promise<T> {
  const base = await getApiBase();
  const resp = await fetch(`${base}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let text = '';
    try { text = await resp.text(); } catch { /* ignore */ }
    throw new Error(`HTTP ${resp.status}: ${text || resp.statusText}`);
  }
  return resp.json() as Promise<T>;
}

// ═══════════════════════════════════════════════════════════
// API 方法
// ═══════════════════════════════════════════════════════════

/** 执行代码审查（diff 或 files） */
export async function runReview(options: RunReviewOptions): Promise<ReviewResult> {
  const data = await _post<{ success: boolean; result: ReviewResult }>('/api/review/run', {
    diff: options.diff || '',
    files: options.files || [],
    max_files: options.max_files ?? 10,
    include_static: options.include_static ?? true,
    include_llm: options.include_llm ?? true,
    scan_dependencies: options.scan_dependencies ?? false,
  });
  return data.result;
}

/** 为单条 issue 生成修复补丁 */
export async function generateFix(issue: ReviewIssue): Promise<FixResult> {
  const data = await _post<FixResult>('/api/review/fix', { issue });
  return data;
}

/** 拉取 GitHub PR diff 自动审查 */
export async function reviewPullRequest(options: PrReviewOptions): Promise<PrReviewResult> {
  return _post<PrReviewResult>('/api/review/pr', {
    owner: options.owner,
    repo: options.repo,
    pr_number: options.pr_number,
    max_files: options.max_files ?? 10,
    auto_comment: options.auto_comment ?? false,
  });
}

export default {
  runReview,
  generateFix,
  reviewPullRequest,
};

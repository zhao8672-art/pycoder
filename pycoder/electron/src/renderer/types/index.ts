// === 文件类型 ===
export interface FileEntry {
  name: string;
  type: 'file' | 'dir';
  path?: string;
  children?: FileEntry[];
  size?: number;
  modifiedAt?: number;
  truncated?: boolean;
  error?: string;
}

// === 聊天消息 ===
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  timestamp: number;
}

// === 编辑器标签页 ===
export interface EditorTab {
  id: string;
  filePath: string;
  fileName: string;
  content: string;
  isDirty: boolean;
  language: string;
}

// === Hermes 分析 ===
export interface HermesAnalysis {
  goal: string;
  scope: string[];
  priority: string;
}

// === Hermes 计划 ===
export interface HermesPlan {
  strategy: string;
  phases: HermesPhase[];
}

export interface HermesPhase {
  description: string;
  files: string[];
}

// === Hermes 步骤 ===
export interface HermesStep {
  phase: number;
  totalPhases: number;
  status: 'running' | 'done' | 'error';
  output: string;
}

// === Diff 文件 ===
export interface DiffFile {
  path: string;
  hunks: DiffHunk[];
}

export interface DiffHunk {
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  lines: string[];
}

// === Git 状态 ===
export interface GitStatus {
  branch: string;
  changes: GitChange[];
  ahead: number;
  behind: number;
}

export interface GitChange {
  file: string;
  status: 'M' | 'A' | 'D' | 'R' | 'C' | 'U' | '?';
  staged: boolean;
}

// === 后端状态 ===
export type BackendStatus = 'starting' | 'running' | 'stopped' | 'crashed' | 'error';

// === 模型信息 ===
export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  available: boolean;
  contextWindow: number;
  pricing: string;
  pricing_input: number;
  pricing_output: number;
  max_output: number;
  api_base: string;
  features: string[];
  custom_api_base: boolean;
}

// === API 响应类型（替换 request<any>） ===
export interface ApiResponse<T = unknown> {
  success?: boolean;
  error?: string;
  data?: T;
}

export interface HealthResponse {
  status: string;
  version: string;
  server_uptime: number;
}

export interface ModelsResponse {
  models: ModelInfo[];
  total: number;
  recommended_model: string;
}

export interface EnvResponse {
  python_version: string;
  python_path: string;
  workspace: string;
  platform: string;
}

export interface SessionItem {
  id: string;
  model?: string;
  title?: string;
  updated_at?: number;
  message_count?: number;
}

export interface SessionsListResponse {
  sessions: SessionItem[];
  total: number;
}

export interface SessionMessagesResponse {
  messages: Array<{
    id: string;
    role: string;
    content: string;
    timestamp: number;
  }>;
  total: number;
}

export interface WorkspaceResponse {
  path: string;
  restored?: boolean;
}

export interface GitStatusResponse {
  branch: string;
  changes: GitChange[];
  ahead: number;
  behind: number;
}

export interface SearchResponse {
  results: Array<{ file: string; line: number; text: string }>;
  total: number;
}

export interface DiffListResponse {
  diffs: DiffFile[];
  total: number;
}

export interface ExtensionInfo {
  id: string;
  name: string;
  description: string;
  version: string;
  installed: boolean;
}

export interface ExtensionsResponse {
  extensions: ExtensionInfo[];
  total: number;
}

export interface SkillsResponse {
  skills: Array<{
    id: string;
    name: string;
    description: string;
    category: string;
    quality_score: number;
  }>;
  total: number;
}

export interface CodeExecResponse {
  success: boolean;
  stdout: string;
  stderr: string;
  error_type: string;
  error_message: string;
  traceback: string;
  execution_time: number;
  output_length: number;
}

export interface CloudSyncResponse {
  success: boolean;
  synced_at: number;
  items: number;
}

export interface TeamResponse {
  agents: Array<{
    id: string;
    name: string;
    role: string;
    status: string;
  }>;
}

export interface EvolutionStatsResponse {
  stats: {
    total_tasks: number;
    successful: number;
    failed: number;
    lines_changed: number;
  };
}

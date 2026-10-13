// Shapes returned by the FastAPI backend (see backend/app/main.py).

export const STAGES = ['parse', 'detect', 'vision', 'chunk', 'embed', 'store'] as const;
export type StageName = (typeof STAGES)[number];

export type StageStatus = 'pending' | 'running' | 'done' | 'skipped' | 'warning';

export interface StageProgress {
  status: StageStatus;
  detail?: string;
  ms?: number;
}

export interface DocumentProfile {
  shape: string;
  pages: number;
  chars_per_page: number;
  graphic_pages: number;
  visual_pages: number[];
  stats: Record<string, number>;
  strategies: string[];
  chunks?: Record<string, number>;
  sections?: number;
  footnotes_attached?: number;
}

export type DocumentStatus = 'processing' | 'ready' | 'failed';

export interface DocumentInfo {
  id: number;
  filename: string;
  title: string | null;
  pages: number | null;
  status: DocumentStatus;
  stage: StageName | null;
  progress: Partial<Record<StageName, StageProgress>>;
  profile: DocumentProfile | null;
  error: string | null;
}

export interface UploadResult {
  id: number;
  reused: boolean;
}

export type ChunkKind = 'text' | 'table' | 'figure' | 'visual' | 'note';

export interface Source {
  chunk_id: number;
  kind: ChunkKind;
  section: string;
  page_start: number;
  page_end: number;
  score: number;
  vector_rank: number | null;
  keyword_rank: number | null;
  expanded: boolean;
  text: string;
}

export interface ChatResponse {
  answer: string;
  searchQuery: string;
  scope: string[];
  sources: Source[];
  timings_ms: { retrieval: number; total: number };
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  response?: ChatResponse;
  isError?: boolean;
}

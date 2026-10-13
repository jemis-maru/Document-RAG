import type { ChatMessage, ChatResponse, DocumentInfo, UploadResult } from '@/types';

/** The backend's error body is {detail: "..."} (FastAPI); surface that text. */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { cache: 'no-store', ...init });
  } catch {
    throw new Error('Cannot reach the server. Is the backend running?');
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in body ? String((body as { detail: unknown }).detail) : null;
    throw new Error(detail || `Request failed (${res.status}). Is the backend running on port 8000?`);
  }
  return body as T;
}

export function uploadDocument(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append('file', file);
  return request<UploadResult>('/api/documents', { method: 'POST', body: form });
}

export function getDocument(id: number): Promise<DocumentInfo> {
  return request<DocumentInfo>(`/api/documents/${id}`);
}

export function askQuestion(documentId: number, message: string, history: ChatMessage[]): Promise<ChatResponse> {
  return request<ChatResponse>('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      documentId,
      message,
      history: history.filter((m) => !m.isError).map((m) => ({ role: m.role, text: m.text })),
    }),
  });
}

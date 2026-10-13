import type { ReactNode } from 'react';

import type { ChatResponse, ChunkKind } from '@/types';

interface SourceListProps {
  response: ChatResponse;
  openSource: number | null;
  onToggle: (n: number) => void;
}

const KIND_STYLE: Record<ChunkKind, string> = {
  text: 'bg-surface-3 text-dim',
  table: 'bg-table/10 text-table',
  figure: 'bg-warn/10 text-warn',
  visual: 'bg-visual/10 text-visual',
  note: 'bg-surface-3 text-dim',
};

const KIND_LABEL: Record<ChunkKind, string> = {
  text: 'text',
  table: 'table',
  figure: 'figure',
  visual: 'chart',
  note: 'footnote',
};

/** The retrieved passages behind an answer -- the single most useful thing to
 *  look at when an answer is wrong: was it retrieval, or the model? */
export function SourceList({ response, openSource, onToggle }: SourceListProps): ReactNode {
  const { sources, scope, searchQuery, timings_ms } = response;

  return (
    <div className="min-w-0 rounded-2xl border border-line bg-surface p-2 text-sm sm:p-3">
      <div className="mb-1.5 flex flex-wrap items-center gap-1.5 px-1 text-xs text-mute">
        <span className="font-medium text-dim">
          {sources.length} source{sources.length === 1 ? '' : 's'}
        </span>
        <span aria-hidden>·</span>
        <span className="tabular-nums">{(timings_ms.total / 1000).toFixed(1)}s</span>
        {scope.length > 0 && (
          <span className="min-w-0 max-w-full truncate rounded-full bg-accent-soft px-2 py-0.5 font-medium text-accent">
            Scoped to {scope.join(' + ')}
          </span>
        )}
      </div>
      {searchQuery && (
        <p className="mb-1.5 px-1 text-xs italic text-mute wrap-anywhere">Searched: “{searchQuery}”</p>
      )}

      {sources.length === 0 && (
        <p className="px-1 py-1 text-mute">No passage was relevant enough — so the answer did not use any.</p>
      )}

      <ol className="space-y-1">
        {sources.map((s, i) => {
          const n = i + 1;
          const open = openSource === n;
          const pages = s.page_start === s.page_end ? `p. ${s.page_start}` : `pp. ${s.page_start}–${s.page_end}`;
          return (
            <li
              key={s.chunk_id}
              className={`min-w-0 rounded-xl border transition ${open ? 'border-accent/40 bg-accent-soft/40' : 'border-transparent'}`}
            >
              <button
                type="button"
                onClick={() => onToggle(n)}
                aria-expanded={open}
                className="w-full min-w-0 rounded-xl px-2 py-1.5 text-left hover:bg-surface-2"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    className={`flex h-5 min-w-5 shrink-0 items-center justify-center rounded-md px-1 font-mono text-[11px] font-semibold ${
                      open ? 'bg-accent text-white' : 'bg-accent-soft text-accent'
                    }`}
                  >
                    {n}
                  </span>
                  {/* Wide screens: section inline. Phones: it gets its own line below. */}
                  <span className="hidden min-w-0 flex-1 truncate text-dim sm:block" title={s.section}>
                    {s.section || 'No section'}
                  </span>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${KIND_STYLE[s.kind]}`}>
                    {KIND_LABEL[s.kind]}
                  </span>
                  <span className="ml-auto whitespace-nowrap text-xs text-mute sm:ml-0">{pages}</span>
                </span>
                <span className="mt-0.5 block truncate pl-7 text-xs text-dim sm:hidden">
                  {s.section || 'No section'}
                </span>
              </button>
              {open && (
                <div className="min-w-0 px-2 pb-2">
                  <p className="mb-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-mute">
                    <span title="Cross-encoder reranker score — higher is more relevant">
                      relevance <span className="font-mono text-dim">{s.score.toFixed(2)}</span>
                    </span>
                    <span>vector rank {s.vector_rank ?? '—'}</span>
                    <span>keyword rank {s.keyword_rank ?? '—'}</span>
                    {s.expanded && <span>+ neighbouring chunk</span>}
                  </p>
                  <p className="mb-1.5 text-xs text-dim wrap-anywhere">{s.section}</p>
                  <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-surface-2 p-3 font-mono text-xs leading-relaxed text-dim wrap-anywhere">
                    {s.text}
                  </pre>
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

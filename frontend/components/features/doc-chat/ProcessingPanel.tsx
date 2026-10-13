'use client';

import type { ReactNode } from 'react';

import { STAGES, type DocumentInfo, type StageStatus } from '@/types';

interface ProcessingPanelProps {
  document: DocumentInfo;
  onRetry: () => void;
}

const LABELS: Record<(typeof STAGES)[number], string> = {
  parse: 'Parse the layout',
  detect: 'Detect document shape',
  vision: 'Read charts (Gemini vision)',
  chunk: 'Chunk by section',
  embed: 'Embed locally',
  store: 'Store in Postgres',
};

const DOT: Record<StageStatus, string> = {
  pending: 'border-line-strong bg-surface',
  running: 'border-accent bg-accent animate-pulse',
  done: 'border-ok bg-ok',
  skipped: 'border-line-strong bg-surface-3',
  warning: 'border-warn bg-warn',
};

const BADGE: Partial<Record<StageStatus, string>> = {
  running: 'bg-accent-soft text-accent',
  skipped: 'bg-surface-3 text-mute',
  warning: 'bg-warn/10 text-warn',
};

// One width per number of finished stages (0-6), as literal classes so
// Tailwind can see them at build time.
const BAR_WIDTH = ['w-[4%]', 'w-1/6', 'w-2/6', 'w-3/6', 'w-4/6', 'w-5/6', 'w-full'];

export function ProcessingPanel({ document, onRetry }: ProcessingPanelProps): ReactNode {
  const failed = document.status === 'failed';
  const doneCount = STAGES.filter((s) => {
    const st = document.progress[s]?.status;
    return st === 'done' || st === 'skipped' || st === 'warning';
  }).length;
  const percent = Math.round((doneCount / STAGES.length) * 100);

  return (
    <section className="mx-auto w-full max-w-2xl rounded-3xl border border-line bg-surface p-5 shadow-[var(--shadow-card)] sm:p-8">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold sm:text-xl">{failed ? 'Processing failed' : 'Processing your document…'}</h2>
          <p className="mt-0.5 text-sm text-mute wrap-anywhere">
            {document.filename}
            {document.pages ? ` · ${document.pages} pages` : ''}
          </p>
        </div>
        {!failed && <span className="shrink-0 text-2xl font-semibold text-accent tabular-nums">{percent}%</span>}
      </div>

      {!failed && (
        <div className="mb-6 h-1.5 overflow-hidden rounded-full bg-surface-3">
          <div
            className={`h-full rounded-full bg-gradient-to-r from-accent to-teal-500 transition-[width] duration-500 ${BAR_WIDTH[doneCount]}`}
          />
        </div>
      )}

      <ol className="space-y-1">
        {STAGES.map((stage, i) => {
          const p = document.progress[stage] ?? { status: 'pending' as const };
          return (
            <li key={stage} className="flex gap-3">
              <div className="flex flex-col items-center">
                <span className={`mt-1.5 h-3 w-3 shrink-0 rounded-full border-2 ${DOT[p.status]}`} />
                {i < STAGES.length - 1 && <span className="my-1 w-px flex-1 bg-line" />}
              </div>
              <div className="min-w-0 flex-1 pb-3">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <span className={`font-medium ${p.status === 'pending' ? 'text-mute' : 'text-ink'}`}>
                    {LABELS[stage]}
                  </span>
                  <span className="flex items-center gap-2">
                    {BADGE[p.status] && (
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${BADGE[p.status]}`}>
                        {p.status}
                      </span>
                    )}
                    {p.ms !== undefined && (
                      <span className="font-mono text-xs text-mute tabular-nums">{(p.ms / 1000).toFixed(1)}s</span>
                    )}
                  </span>
                </div>
                {p.detail && <p className="mt-0.5 text-sm text-dim wrap-anywhere">{p.detail}</p>}
              </div>
            </li>
          );
        })}
      </ol>

      {failed && (
        <div className="mt-4 rounded-2xl border border-danger/20 bg-danger/5 p-4 text-sm text-danger">
          <p className="wrap-anywhere">{document.error}</p>
          <button type="button" onClick={onRetry} className="mt-2 font-medium underline underline-offset-2">
            Upload again
          </button>
        </div>
      )}
      {!failed && (
        <p className="mt-4 rounded-xl bg-surface-2 px-3 py-2 text-xs text-mute">
          A 200-page report takes a few minutes on CPU — the embedding stage is the slowest.
        </p>
      )}
    </section>
  );
}

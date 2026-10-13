'use client';

import { useState, type ReactNode } from 'react';

import type { DocumentInfo } from '@/types';

interface DocumentProfileCardProps {
  document: DocumentInfo;
  reused: boolean;
}

/** What the pipeline detected and which strategies it applied -- the
 *  "why is this document handled differently" part of the exercise.
 *  On small screens it collapses to one row so the chat stays in view. */
export function DocumentProfileCard({ document, reused }: DocumentProfileCardProps): ReactNode {
  const [expanded, setExpanded] = useState(false);
  const profile = document.profile;
  const [shapeName, shapeWhy] = (profile?.shape ?? '').split(' — ');

  return (
    <aside className="h-fit min-w-0 rounded-3xl border border-line bg-surface shadow-[var(--shadow-card)] lg:sticky lg:top-20">
      <div className="flex items-start gap-3 p-4 sm:p-5">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
            <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" strokeLinejoin="round" />
            <path d="M14 3v5h5M9 13h6M9 17h4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold leading-snug wrap-anywhere">{document.title || document.filename}</h2>
          <p className="mt-0.5 text-xs text-mute">
            {document.pages} pages
            {shapeName ? ` · ${shapeName}` : ''}
            {reused ? ' · reused' : ''}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          className="shrink-0 rounded-full border border-line px-2.5 py-1 text-xs font-medium text-dim transition hover:border-accent hover:text-accent lg:hidden"
        >
          {expanded ? 'Hide' : 'Details'}
        </button>
      </div>

      {profile && (
        <div className={`${expanded ? 'block' : 'hidden'} space-y-5 border-t border-line p-4 sm:p-5 lg:block`}>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-mute">Detected shape</p>
            <p className="mt-1.5 inline-flex rounded-full bg-accent-soft px-2.5 py-0.5 text-sm font-medium text-accent">
              {shapeName}
            </p>
            {shapeWhy && <p className="mt-1.5 text-sm text-dim">{shapeWhy}</p>}
          </div>

          <dl className="grid grid-cols-3 gap-2 text-center">
            {[
              ['sections', profile.sections ?? 0],
              ['tables', profile.stats.tables ?? 0],
              ['footnotes', profile.stats.notes ?? 0],
            ].map(([label, value]) => (
              <div key={label} className="rounded-2xl border border-line bg-surface-2 px-2 py-2.5">
                <dd className="text-lg font-semibold tabular-nums">{value}</dd>
                <dt className="text-xs text-mute">{label}</dt>
              </div>
            ))}
          </dl>

          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-mute">Strategies applied</p>
            <ul className="space-y-2 text-sm text-dim">
              {profile.strategies.map((s) => (
                <li key={s} className="flex gap-2">
                  <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-ok/10 text-[10px] text-ok">
                    ✓
                  </span>
                  <span className="min-w-0 wrap-anywhere">{s}</span>
                </li>
              ))}
            </ul>
          </div>

          {profile.chunks && (
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(profile.chunks).map(([kind, n]) => (
                <span key={kind} className="rounded-full bg-surface-3 px-2.5 py-0.5 text-xs text-dim">
                  {n} {kind} chunks
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </aside>
  );
}

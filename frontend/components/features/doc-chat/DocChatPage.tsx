'use client';

import { useState, type ReactNode } from 'react';

import { ChatPanel } from '@/components/features/doc-chat/ChatPanel';
import { DocumentProfileCard } from '@/components/features/doc-chat/DocumentProfileCard';
import { ProcessingPanel } from '@/components/features/doc-chat/ProcessingPanel';
import { UploadPanel } from '@/components/features/doc-chat/UploadPanel';
import { useDocumentStatus } from '@/hooks/useDocumentStatus';

/**
 * The whole app is one flow:
 *   upload a PDF -> watch the pipeline process it -> chat about that document.
 * "New chat" returns to the upload step; nothing is kept between sessions.
 */
export function DocChatPage(): ReactNode {
  const [documentId, setDocumentId] = useState<number | null>(null);
  const [reused, setReused] = useState(false);
  const { document, error } = useDocumentStatus(documentId);

  const reset = (): void => {
    setDocumentId(null);
    setReused(false);
  };

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-30 border-b border-line/70 bg-bg/80 backdrop-blur-md">
        <div className="mx-auto flex w-full max-w-7xl items-center justify-between gap-3 px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-teal-500 text-sm font-bold text-white shadow-[var(--shadow-lift)]">
              D
            </span>
            <div className="min-w-0">
              <h1 className="text-base font-semibold leading-tight tracking-tight sm:text-lg">Doc RAG</h1>
              <p className="hidden truncate text-xs text-mute sm:block">
                Answers only from your PDF — every fact cited to its page
              </p>
            </div>
          </div>
          {documentId !== null && (
            <button
              type="button"
              onClick={reset}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3.5 py-1.5 text-sm font-medium text-dim shadow-sm transition hover:border-accent hover:text-accent"
            >
              <span aria-hidden className="text-base leading-none">+</span>
              New chat
            </button>
          )}
        </div>
      </header>

      <main className="mx-auto flex w-full min-w-0 max-w-7xl flex-1 flex-col px-4 py-5 sm:px-6 sm:py-8 lg:px-8">
        {documentId === null && (
          <UploadPanel
            onUploaded={(id, wasReused) => {
              setDocumentId(id);
              setReused(wasReused);
            }}
          />
        )}

        {documentId !== null && !document && (
          <div className="flex flex-1 items-center justify-center">
            <p className="flex items-center gap-2 text-sm text-mute">
              <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />
              {error ?? 'Loading document…'}
            </p>
          </div>
        )}

        {document && document.status !== 'ready' && <ProcessingPanel document={document} onRetry={reset} />}

        {document && document.status === 'ready' && (
          // minmax(0, 1fr): without it the chat column grows to fit its
          // widest line (a long table row) and pushes the page off-screen.
          <div className="grid min-w-0 flex-1 gap-4 lg:grid-cols-[300px_minmax(0,1fr)] lg:gap-6">
            <DocumentProfileCard document={document} reused={reused} />
            <ChatPanel key={document.id} document={document} />
          </div>
        )}
      </main>
    </div>
  );
}

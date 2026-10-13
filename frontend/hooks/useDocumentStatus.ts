'use client';

import { useEffect, useState } from 'react';

import { getDocument } from '@/lib/api';
import type { DocumentInfo } from '@/types';

const POLL_MS = 1000;

interface UseDocumentStatus {
  document: DocumentInfo | null;
  error: string | null;
}

/** Polls the document every second while the pipeline runs, then stops. */
export function useDocumentStatus(documentId: number | null): UseDocumentStatus {
  const [document, setDocument] = useState<DocumentInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDocument(null);
    setError(null);
    if (documentId === null) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async (): Promise<void> => {
      try {
        const doc = await getDocument(documentId);
        if (cancelled) return;
        setDocument(doc);
        setError(null);
        if (doc.status === 'processing') timer = setTimeout(poll, POLL_MS);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Could not load the document');
        timer = setTimeout(poll, POLL_MS * 3); // the backend may be restarting
      }
    };
    void poll();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [documentId]);

  return { document, error };
}

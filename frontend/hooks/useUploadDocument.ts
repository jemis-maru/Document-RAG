'use client';

import { useCallback, useState } from 'react';

import { uploadDocument } from '@/lib/api';
import type { UploadResult } from '@/types';

interface UseUploadDocument {
  upload: (file: File) => Promise<UploadResult | null>;
  isUploading: boolean;
  error: string | null;
}

export function useUploadDocument(): UseUploadDocument {
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const upload = useCallback(async (file: File): Promise<UploadResult | null> => {
    setIsUploading(true);
    setError(null);
    try {
      return await uploadDocument(file);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
      return null;
    } finally {
      setIsUploading(false);
    }
  }, []);

  return { upload, isUploading, error };
}

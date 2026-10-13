'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useState, type DragEvent, type ReactNode } from 'react';
import { useForm } from 'react-hook-form';

import {
  MAX_UPLOAD_MB,
  uploadFormSchema,
  type UploadFormValues,
} from '@/components/features/doc-chat/uploadForm.schema';
import { useUploadDocument } from '@/hooks/useUploadDocument';

interface UploadPanelProps {
  onUploaded: (documentId: number, reused: boolean) => void;
}

const STEPS = [
  ['Parse', 'Headings, paragraphs, tables, figures and footnotes from the page layout'],
  ['Detect', 'Narrative, long & structured, or visual — from layout statistics'],
  ['Vision', 'Chart-heavy pages of short documents are described by Gemini (cached)'],
  ['Chunk', 'Section-aware pieces; tables stay whole; footnotes attached'],
  ['Embed', 'A local model turns each chunk into a vector — no API quota'],
  ['Store', 'Postgres keeps vectors and a keyword index side by side'],
] as const;

export function UploadPanel({ onUploaded }: UploadPanelProps): ReactNode {
  const { upload, isUploading, error } = useUploadDocument();
  const [isDragging, setIsDragging] = useState(false);
  const {
    handleSubmit,
    setValue,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<UploadFormValues>({ resolver: zodResolver(uploadFormSchema) });

  const file = watch('file');
  const busy = isSubmitting || isUploading;

  const onSubmit = async (values: UploadFormValues): Promise<void> => {
    const result = await upload(values.file);
    if (result) onUploaded(result.id, result.reused);
  };

  const pick = (f: File | undefined): void => {
    if (f) setValue('file', f, { shouldValidate: true });
  };

  const onDrop = (e: DragEvent<HTMLLabelElement>): void => {
    e.preventDefault();
    setIsDragging(false);
    pick(e.dataTransfer.files[0]);
  };

  return (
    <div className="mx-auto w-full max-w-5xl">
      <div className="mb-6 text-center sm:mb-10">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-3 py-1 text-xs font-medium text-accent">
          Retrieval-augmented generation
        </span>
        <h2 className="mt-3 text-2xl font-semibold tracking-tight text-balance sm:text-4xl">
          Ask questions about any PDF
        </h2>
        <p className="mx-auto mt-2 max-w-xl text-sm text-dim text-pretty sm:text-base">
          Narrative reports, 200-page structured documents, or chart-heavy factsheets — each is parsed the way its
          layout needs, and every answer cites the page it came from.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px] lg:gap-6">
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="min-w-0 rounded-3xl border border-line bg-surface p-4 shadow-[var(--shadow-card)] sm:p-6"
        >
          <label htmlFor="pdf" className="mb-2 block text-sm font-medium text-dim">
            PDF document
          </label>
          <label
            htmlFor="pdf"
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={onDrop}
            className={`group flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-4 py-10 text-center transition sm:py-16 ${
              isDragging
                ? 'border-accent bg-accent-soft'
                : file
                  ? 'border-accent/50 bg-accent-soft/50'
                  : 'border-line-strong bg-surface-2 hover:border-accent hover:bg-accent-soft/40'
            }`}
          >
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-surface text-accent shadow-[var(--shadow-card)] transition group-hover:scale-105">
              <svg viewBox="0 0 24 24" className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
                <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" strokeLinejoin="round" />
                <path d="M14 3v5h5M12 17v-6m-3 3 3-3 3 3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span className="max-w-full font-medium wrap-anywhere">
              {file ? file.name : (
                <>
                  <span className="text-accent">Choose a PDF</span> or drag it here
                </>
              )}
            </span>
            <span className="text-xs text-mute sm:text-sm">
              {file
                ? `${(file.size / 1024 / 1024).toFixed(1)} MB · ready to upload`
                : `Up to ${MAX_UPLOAD_MB} MB and 250 pages, with a text layer`}
            </span>
          </label>
          <input
            id="pdf"
            type="file"
            accept="application/pdf,.pdf"
            className="sr-only"
            onChange={(e) => pick(e.target.files?.[0])}
          />

          {(errors.file || error) && (
            <p role="alert" className="mt-3 rounded-xl bg-danger/8 px-3 py-2 text-sm text-danger wrap-anywhere">
              {errors.file?.message ?? error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy || !file}
            className="mt-5 w-full rounded-xl bg-accent px-4 py-3 font-medium text-white shadow-[var(--shadow-lift)] transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
          >
            {busy ? 'Uploading…' : 'Upload and process'}
          </button>
          <p className="mt-3 text-center text-xs text-mute">
            Uploading the same file again reuses the processed copy instantly.
          </p>
        </form>

        <aside className="min-w-0 rounded-3xl border border-line bg-surface p-4 shadow-[var(--shadow-card)] sm:p-6">
          <h3 className="mb-4 text-xs font-semibold uppercase tracking-wider text-mute">What happens next</h3>
          <ol className="relative space-y-4">
            {STEPS.map(([name, text], i) => (
              <li key={name} className="flex gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent">
                  {i + 1}
                </span>
                <div className="min-w-0 text-sm">
                  <p className="font-medium leading-7">{name}</p>
                  <p className="text-dim">{text}</p>
                </div>
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </div>
  );
}

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { useForm } from 'react-hook-form';

import { chatFormSchema, type ChatFormValues } from '@/components/features/doc-chat/chatForm.schema';
import { MessageBubble } from '@/components/features/doc-chat/MessageBubble';
import { useChat } from '@/hooks/useChat';
import type { DocumentInfo } from '@/types';

interface ChatPanelProps {
  document: DocumentInfo;
}

const HOW_IT_WORKS = [
  ['Search', 'meaning + exact keywords, scoped to a section if you name one'],
  ['Rerank', 'a local model keeps only passages that answer the question'],
  ['Answer', 'Gemini writes from those passages only, citing each fact'],
] as const;

export function ChatPanel({ document }: ChatPanelProps): ReactNode {
  const { messages, isAsking, ask } = useChat(document.id);
  const bottomRef = useRef<HTMLDivElement>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ChatFormValues>({ resolver: zodResolver(chatFormSchema), defaultValues: { question: '' } });

  useEffect(() => {
    if (messages.length) bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, isAsking]);

  const onSubmit = async (values: ChatFormValues): Promise<void> => {
    reset();
    await ask(values.question);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>): void => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit(onSubmit)();
    }
  };

  const busy = isSubmitting || isAsking;

  return (
    <section className="flex min-h-[60dvh] min-w-0 flex-col rounded-3xl border border-line bg-surface shadow-[var(--shadow-card)] lg:h-[calc(100dvh-8.5rem)] lg:min-h-[32rem]">
      <div className="min-w-0 flex-1 space-y-6 p-4 sm:p-6 lg:overflow-y-auto">
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center py-10 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-soft text-accent">
              <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
                <path
                  d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              </svg>
            </span>
            <p className="mt-3 text-lg font-semibold">Ask anything about this document</p>
            <p className="mt-1 max-w-md text-sm text-mute text-pretty">
              Click a citation like <span className="rounded bg-accent-soft px-1 font-mono text-xs text-accent">1</span>{' '}
              in an answer to see the exact passage, its section and page.
            </p>
            <ol className="mt-6 grid w-full max-w-2xl gap-2 text-left sm:grid-cols-3">
              {HOW_IT_WORKS.map(([name, text], i) => (
                <li key={name} className="rounded-2xl border border-line bg-surface-2 p-3">
                  <p className="text-xs font-semibold text-accent">
                    {i + 1}. {name}
                  </p>
                  <p className="mt-0.5 text-xs text-dim">{text}</p>
                </li>
              ))}
            </ol>
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {isAsking && (
          <div className="flex items-center gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft">
              <span className="flex gap-1">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.3s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.15s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent" />
              </span>
            </span>
            <span className="text-sm text-mute">Searching the document and writing an answer…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Sticky on phones, where the page itself scrolls; a normal footer on desktop. */}
      <form
        onSubmit={handleSubmit(onSubmit)}
        className="sticky bottom-0 rounded-b-3xl border-t border-line bg-surface/95 p-3 backdrop-blur sm:p-4 lg:static"
      >
        <label htmlFor="question" className="sr-only">
          Your question
        </label>
        <div className="flex items-end gap-2 rounded-2xl border border-line-strong bg-surface-2 p-1.5 transition focus-within:border-accent focus-within:ring-4 focus-within:ring-accent/10">
          <textarea
            id="question"
            rows={1}
            placeholder="Ask a question…  e.g. What is the growth outlook for South Asia?"
            onKeyDown={onKeyDown}
            {...register('question')}
            className="max-h-40 min-h-10 min-w-0 flex-1 resize-none bg-transparent px-2.5 py-2 text-base text-ink [field-sizing:content] placeholder:text-mute focus:outline-none sm:text-[15px]"
          />
          <button
            type="submit"
            disabled={busy}
            aria-label="Ask"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent text-white shadow-[var(--shadow-lift)] transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none sm:w-auto sm:px-4"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5 sm:hidden" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="hidden text-sm font-medium sm:inline">Ask</span>
          </button>
        </div>
        <div className="mt-1.5 flex items-center justify-between gap-2 px-1 text-xs text-mute">
          {errors.question ? <span className="text-danger">{errors.question.message}</span> : <span />}
          <span className="hidden sm:inline">Enter to send · Shift + Enter for a new line</span>
        </div>
      </form>
    </section>
  );
}

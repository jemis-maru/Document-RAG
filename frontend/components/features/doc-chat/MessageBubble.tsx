'use client';

import { useState, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { SourceList } from '@/components/features/doc-chat/SourceList';
import type { ChatMessage } from '@/types';

interface MessageBubbleProps {
  message: ChatMessage;
}

const SUPERSCRIPT: Record<string, string> = {
  '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
};

/** Prepare the model's markdown for display:
 *  - "[2]" and "[1, 3]" become links to #cite-N, rendered as chips
 *  - stray <sup>1</sup> HTML (markdown has no superscript) becomes "¹";
 *    HTML is never rendered, so it would otherwise show as literal tags */
function prepareAnswer(text: string): string {
  return text
    .replace(/<sup>\s*(\d+)\s*<\/sup>/gi, (_, n: string) => n.replace(/\d/g, (d) => SUPERSCRIPT[d]))
    .replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g, (_, nums: string) =>
      nums
        .split(',')
        .map((n) => `[${n.trim()}](#cite-${n.trim()})`)
        .join(''),
    );
}

export function MessageBubble({ message }: MessageBubbleProps): ReactNode {
  const [openSource, setOpenSource] = useState<number | null>(null);

  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <p className="max-w-[88%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent px-4 py-2.5 text-white shadow-[var(--shadow-lift)] wrap-anywhere sm:max-w-[75%]">
          {message.text}
        </p>
      </div>
    );
  }

  if (message.isError) {
    return (
      <div className="flex gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-danger/10 text-sm font-semibold text-danger">
          !
        </span>
        <p className="min-w-0 rounded-2xl border border-danger/20 bg-danger/5 px-4 py-2.5 text-sm text-danger wrap-anywhere">
          {message.text}
        </p>
      </div>
    );
  }

  const markdown: Components = {
    a: ({ href, children }) => {
      const cite = href?.startsWith('#cite-') ? Number(href.slice(6)) : null;
      if (cite === null) {
        return (
          <a href={href} target="_blank" rel="noreferrer" className="text-accent underline underline-offset-2 wrap-anywhere">
            {children}
          </a>
        );
      }
      return (
        <button
          type="button"
          onClick={() => setOpenSource(openSource === cite ? null : cite)}
          className={`mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md px-1 align-[0.1em] font-mono text-[11px] font-semibold transition ${
            openSource === cite ? 'bg-accent text-white' : 'bg-accent-soft text-accent hover:bg-accent hover:text-white'
          }`}
        >
          {cite}
        </button>
      );
    },
    p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
    ul: ({ children }) => <ul className="mb-3 list-disc space-y-1.5 pl-5 marker:text-accent/60">{children}</ul>,
    ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1.5 pl-5 marker:text-accent/60">{children}</ol>,
    li: ({ children }) => <li className="pl-0.5">{children}</li>,
    strong: ({ children }) => <strong className="font-semibold text-ink">{children}</strong>,
    h1: ({ children }) => <h3 className="mb-2 mt-3 font-semibold first:mt-0">{children}</h3>,
    h2: ({ children }) => <h3 className="mb-2 mt-3 font-semibold first:mt-0">{children}</h3>,
    h3: ({ children }) => <h4 className="mb-2 mt-3 font-semibold first:mt-0">{children}</h4>,
    code: ({ children }) => (
      <code className="rounded bg-surface-3 px-1 py-0.5 font-mono text-[0.85em] wrap-anywhere">{children}</code>
    ),
    pre: ({ children }) => (
      <pre className="mb-3 max-w-full overflow-x-auto rounded-xl bg-surface-3 p-3 text-xs">{children}</pre>
    ),
    // Tables scroll inside their own box instead of widening the page.
    table: ({ children }) => (
      <div className="mb-3 max-w-full overflow-x-auto rounded-xl border border-line bg-surface">
        <table className="w-max min-w-full text-sm wrap-normal">{children}</table>
      </div>
    ),
    th: ({ children }) => (
      <th className="whitespace-nowrap border-b border-line bg-surface-2 px-3 py-1.5 text-left font-medium text-dim">
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td className="whitespace-nowrap border-b border-line/60 px-3 py-1.5 tabular-nums">{children}</td>
    ),
  };

  const response = message.response;

  return (
    <div className="flex min-w-0 gap-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-accent to-teal-500 text-xs font-bold text-white">
        AI
      </span>
      <div className="min-w-0 flex-1 space-y-2.5">
        <div className="min-w-0 rounded-2xl rounded-tl-md border border-line bg-surface-2 px-4 py-3 leading-relaxed wrap-anywhere">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdown}>
            {prepareAnswer(message.text)}
          </ReactMarkdown>
        </div>
        {response && (
          <SourceList
            response={response}
            openSource={openSource}
            onToggle={(n) => setOpenSource(openSource === n ? null : n)}
          />
        )}
      </div>
    </div>
  );
}

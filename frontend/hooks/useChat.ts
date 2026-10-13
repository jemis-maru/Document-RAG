'use client';

import { useCallback, useState } from 'react';

import { askQuestion } from '@/lib/api';
import type { ChatMessage } from '@/types';

interface UseChat {
  messages: ChatMessage[];
  isAsking: boolean;
  ask: (question: string) => Promise<void>;
}

let nextId = 0;
const newId = (): string => `m${++nextId}`;

/** One chat session about one document. Nothing is persisted: a new chat
 *  (or a page reload) starts from an empty conversation. */
export function useChat(documentId: number): UseChat {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isAsking, setIsAsking] = useState(false);

  const ask = useCallback(
    async (question: string): Promise<void> => {
      const history = messages;
      setMessages((prev) => [...prev, { id: newId(), role: 'user', text: question }]);
      setIsAsking(true);
      try {
        const response = await askQuestion(documentId, question, history);
        setMessages((prev) => [...prev, { id: newId(), role: 'assistant', text: response.answer, response }]);
      } catch (e) {
        const text = e instanceof Error ? e.message : 'Something went wrong';
        setMessages((prev) => [...prev, { id: newId(), role: 'assistant', text, isError: true }]);
      } finally {
        setIsAsking(false);
      }
    },
    [documentId, messages],
  );

  return { messages, isAsking, ask };
}

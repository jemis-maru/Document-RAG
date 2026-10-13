import { z } from 'zod';

export const chatFormSchema = z.object({
  question: z.string().trim().min(1, 'Type a question').max(2000, 'Keep it under 2000 characters'),
});

export type ChatFormValues = z.infer<typeof chatFormSchema>;

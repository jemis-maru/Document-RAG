import { z } from 'zod';

export const MAX_UPLOAD_MB = 40;

export const uploadFormSchema = z.object({
  file: z
    .instanceof(File, { message: 'Choose a PDF file' })
    .refine((f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'), 'Only PDF files are supported')
    .refine((f) => f.size <= MAX_UPLOAD_MB * 1024 * 1024, `The file must be ${MAX_UPLOAD_MB} MB or smaller`),
});

export type UploadFormValues = z.infer<typeof uploadFormSchema>;

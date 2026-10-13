import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';

import './globals.css';

export const metadata: Metadata = {
  title: 'Doc RAG — ask a PDF',
  description: 'Upload a PDF and ask questions answered only from that document, with citations.',
};

export const viewport: Viewport = {
  themeColor: '#f5f6fb',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }): ReactNode {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

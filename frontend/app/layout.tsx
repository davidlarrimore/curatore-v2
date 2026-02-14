// app/layout.tsx
import '../styles/globals.css'
import { ReactNode, Suspense } from 'react'
import { AppLayout } from '@/components/layout/AppLayout'
import { AuthProvider } from '@/lib/auth-context'
import { UnifiedJobsProvider } from '@/lib/unified-jobs-context'
import { LoadingBar } from '@/components/LoadingBar'

import type { Metadata, Viewport } from 'next'

export const metadata: Metadata = {
  title: 'Curatore v2 - RAG Document Processing',
  description: 'Transform documents into RAG-ready, semantically optimized content',
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
}

interface RootLayoutProps {
  children: ReactNode
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full bg-gray-50 antialiased">
        <Suspense fallback={null}>
          <LoadingBar />
        </Suspense>
        <AuthProvider>
          {/* Unified jobs provider with WebSocket + polling fallback */}
          <UnifiedJobsProvider>
            <AppLayout>
              {children}
            </AppLayout>
          </UnifiedJobsProvider>
        </AuthProvider>
      </body>
    </html>
  )
}
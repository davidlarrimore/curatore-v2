// app/layout.tsx
import '../styles/globals.css'
import { ReactNode, Suspense } from 'react'
import { AppLayout } from '@/components/layout/AppLayout'
import { AuthProvider } from '@/lib/auth-context'
import { QueueProvider } from '@/lib/queue-context'
import { DeletionJobsProvider } from '@/lib/deletion-jobs-context'
import { ActiveJobsProvider } from '@/lib/active-jobs-context'
import { LoadingBar } from '@/components/LoadingBar'

export const metadata = {
  title: 'Curatore v2 - RAG Document Processing',
  description: 'Transform documents into RAG-ready, semantically optimized content',
  viewport: 'width=device-width, initial-scale=1',
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
          <QueueProvider>
            <DeletionJobsProvider>
              <ActiveJobsProvider>
                <AppLayout>
                  {children}
                </AppLayout>
              </ActiveJobsProvider>
            </DeletionJobsProvider>
          </QueueProvider>
        </AuthProvider>
      </body>
    </html>
  )
}
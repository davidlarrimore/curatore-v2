// app/layout.tsx
import '../styles/globals.css'
import { ReactNode } from 'react'
import { AppLayout } from '@/components/layout/AppLayout'
import { AuthProvider } from '@/lib/auth-context'

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
        <AuthProvider>
          <AppLayout>
            {children}
          </AppLayout>
        </AuthProvider>
      </body>
    </html>
  )
}
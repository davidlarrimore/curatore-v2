'use client'

/**
 * Organization-scoped layout.
 *
 * Guards all /orgs/[orgSlug]/* routes by:
 * 1. Extracting org slug from URL
 * 2. Fetching and validating organization access
 * 3. Providing organization context to all children
 *
 * Also sets the organization context in localStorage for API compatibility
 * during the migration period.
 */

import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { OrgUrlProvider, useOrgUrl } from '@/lib/org-url-context'
import { Loader2 } from 'lucide-react'

function OrgLayoutGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const { isLoading: authLoading, isAuthenticated } = useAuth()
  const { isLoading: orgLoading, error, organization } = useOrgUrl()

  // Still loading
  if (authLoading || orgLoading) {
    return (
      <div className="fixed inset-0 bg-white/80 dark:bg-gray-900/80 flex items-center justify-center z-50">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 animate-spin text-indigo-600" />
          <p className="text-sm text-gray-600 dark:text-gray-400">Loading organization...</p>
        </div>
      </div>
    )
  }

  // Not authenticated - redirect to login
  if (!isAuthenticated) {
    router.push('/login')
    return null
  }

  // Error loading organization
  if (error) {
    return (
      <div className="fixed inset-0 bg-white dark:bg-gray-900 flex items-center justify-center">
        <div className="text-center max-w-md px-4">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
            Organization Not Available
          </h1>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            {error}
          </p>
          <button
            onClick={() => router.push('/')}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
          >
            Return Home
          </button>
        </div>
      </div>
    )
  }

  // Organization loaded successfully
  if (!organization) {
    return null
  }

  return <>{children}</>
}

export default function OrgLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <OrgUrlProvider>
      <OrgLayoutGuard>{children}</OrgLayoutGuard>
    </OrgUrlProvider>
  )
}

'use client'

/**
 * Organization-scoped connections page.
 * Redirects to org settings connections tab.
 */

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useOrgUrl } from '@/lib/org-url-context'
import { Loader2 } from 'lucide-react'

export default function ConnectionsPage() {
  const router = useRouter()
  const { orgSlug } = useOrgUrl()

  useEffect(() => {
    // Redirect to the connections tab in org admin settings
    // For now, redirect to org dashboard since org-level settings isn't implemented yet
    router.replace(`/orgs/${orgSlug}`)
  }, [router, orgSlug])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="text-center">
        <Loader2 className="w-8 h-8 animate-spin text-indigo-600 mx-auto" />
        <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">Redirecting...</p>
      </div>
    </div>
  )
}

'use client'

/**
 * Root page - redirects users to appropriate location.
 *
 * - System admins in system mode: /system
 * - Users with organization: /orgs/{orgSlug}
 */

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { useOrganization } from '@/lib/organization-context'
import { organizationsApi } from '@/lib/api'
import { Loader2 } from 'lucide-react'

export default function RootRedirectPage() {
  const router = useRouter()
  const { user, token, isAdmin, isLoading: authLoading } = useAuth()
  const { mode, currentOrganization, isLoading: orgLoading } = useOrganization()

  useEffect(() => {
    // Wait for auth and org context to load
    if (authLoading || orgLoading) return

    const performRedirect = async () => {
      // System admins in system mode go to /system
      if (isAdmin && mode === 'system') {
        router.replace('/system')
        return
      }

      // If we have a current organization with a slug, go to that org's dashboard
      if (currentOrganization?.slug) {
        router.replace(`/orgs/${currentOrganization.slug}`)
        return
      }

      // For users without org context loaded yet, try to get their org
      if (user?.organization_id && token) {
        try {
          const org = await organizationsApi.getCurrentOrganization(token)
          if (org?.slug) {
            router.replace(`/orgs/${org.slug}`)
            return
          }
        } catch (error) {
          console.error('Failed to get user organization:', error)
        }
      }

      // Default fallback for admins without org context
      if (isAdmin) {
        router.replace('/system')
      }
    }

    performRedirect()
  }, [authLoading, orgLoading, isAdmin, mode, currentOrganization, user, token, router])

  return (
    <div className="fixed inset-0 bg-white dark:bg-gray-900 flex items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <Loader2 className="w-8 h-8 animate-spin text-indigo-600" />
        <p className="text-sm text-gray-600 dark:text-gray-400">Loading...</p>
      </div>
    </div>
  )
}

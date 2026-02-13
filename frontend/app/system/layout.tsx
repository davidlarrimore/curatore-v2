'use client'

/**
 * System admin layout.
 *
 * Guards all /system/* routes to require admin role.
 * Redirects non-admins to the home page.
 */

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { useOrganization } from '@/lib/organization-context'

export default function SystemLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const { isAdmin, isLoading: authLoading } = useAuth()
  const { mode, switchToSystemContext } = useOrganization()

  useEffect(() => {
    // Wait for auth to load
    if (authLoading) return

    // Redirect non-admins to home
    if (!isAdmin) {
      router.push('/')
      return
    }

    // Auto-switch to system context when entering /system routes
    if (mode !== 'system') {
      switchToSystemContext()
    }
  }, [isAdmin, authLoading, mode, router, switchToSystemContext])

  // Show loading state while checking auth
  if (authLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-600"></div>
      </div>
    )
  }

  // Don't render children if not admin
  if (!isAdmin) {
    return null
  }

  return <>{children}</>
}

'use client'

/**
 * Protected route wrapper component.
 *
 * Ensures that only authenticated users can access wrapped content.
 * Unauthenticated users are automatically redirected to the login page
 * with their intended destination stored for post-login redirect.
 *
 * Features:
 * - Automatic redirect to login for unauthenticated users
 * - Return URL storage for post-login redirect
 * - Optional role-based access control
 * - Loading state during authentication check
 *
 * Anti-redirect-loop measures:
 * - Only redirects after loading is complete
 * - Prevents redirect if already on login page
 * - Uses ref to track redirect state
 * - Stores return URL in session storage (not URL params)
 *
 * Usage:
 * ```tsx
 * <ProtectedRoute>
 *   <YourProtectedContent />
 * </ProtectedRoute>
 *
 * // With role requirement
 * <ProtectedRoute requiredRole="org_admin">
 *   <AdminOnlyContent />
 * </ProtectedRoute>
 * ```
 */

import { useEffect, useRef } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'

interface ProtectedRouteProps {
  children: React.ReactNode
  requiredRole?: 'admin' | 'org_admin' | 'member' | 'viewer'
}

const RETURN_URL_KEY = 'auth_return_url'

export default function ProtectedRoute({ children, requiredRole }: ProtectedRouteProps) {
  const router = useRouter()
  const pathname = usePathname()
  const { isAuthenticated, isLoading, user } = useAuth()

  // Track if we've already redirected to prevent loops
  const hasRedirected = useRef(false)

  /**
   * Handle unauthenticated users.
   *
   * This effect runs when:
   * - Loading is complete (isLoading = false)
   * - User is not authenticated
   * - We haven't already redirected
   * - We're not on the login page
   *
   * It will:
   * 1. Store the current path as the return URL
   * 2. Redirect to the login page
   * 3. Mark that we've redirected to prevent loops
   */
  useEffect(() => {
    if (!isLoading && !isAuthenticated && !hasRedirected.current && pathname !== '/login') {
      console.log('ProtectedRoute: User not authenticated, redirecting to login from:', pathname)

      // Store the current path as the return URL (not including /login)
      if (pathname !== '/login') {
        sessionStorage.setItem(RETURN_URL_KEY, pathname)
      }

      // Mark that we're redirecting
      hasRedirected.current = true

      // Redirect to login
      router.push('/login')
    }
  }, [isAuthenticated, isLoading, pathname, router])

  /**
   * Handle role-based access control.
   *
   * This effect runs when:
   * - Loading is complete
   * - User is authenticated
   * - A required role is specified
   * - User doesn't have the required role
   *
   * Role hierarchy: admin > org_admin > member > viewer
   * admin can access everything, org_admin can access org_admin/member/viewer pages
   *
   * It will redirect to the home page with insufficient permissions.
   */
  useEffect(() => {
    if (!isLoading && isAuthenticated && requiredRole) {
      // admin can access everything
      // org_admin can access org_admin, member, viewer pages
      const hasAccess =
        user?.role === 'admin' ||
        user?.role === requiredRole ||
        (user?.role === 'org_admin' && requiredRole !== 'admin')

      if (!hasAccess) {
        console.log('ProtectedRoute: Insufficient permissions, redirecting to home')
        router.push('/')
      }
    }
  }, [isAuthenticated, isLoading, user, requiredRole, router])

  /**
   * Show loading spinner during authentication check.
   *
   * This prevents flash of unauthenticated content and provides
   * visual feedback during the initial auth check.
   */
  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600 dark:text-gray-400">Loading...</p>
        </div>
      </div>
    )
  }

  /**
   * Don't render anything if not authenticated.
   *
   * Return null instead of the children to prevent flash of content
   * before redirect completes. The useEffect above will handle the redirect.
   */
  if (!isAuthenticated) {
    return null
  }

  /**
   * Render protected content for authenticated users.
   */
  return <>{children}</>
}

'use client'

/**
 * Login page component.
 *
 * Provides authentication functionality with the following features:
 * - Email/username and password authentication
 * - Return URL support (redirects back to intended page after login)
 * - Automatic redirect if already authenticated
 * - Session storage for return URL to support browser refresh
 * - Comprehensive error handling
 *
 * Anti-redirect-loop measures:
 * - Only redirects authenticated users (not during loading)
 * - Clears return URL after successful login
 * - Does not redirect to /login as return URL
 */

import { useState, FormEvent, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { Button } from '@/components/ui/Button'

const RETURN_URL_KEY = 'auth_return_url'

export default function LoginPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { login, isAuthenticated, isLoading: authLoading } = useAuth()
  const [emailOrUsername, setEmailOrUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  // Store return URL from query parameter or retrieve from session storage
  useEffect(() => {
    const returnUrl = searchParams.get('returnUrl')
    if (returnUrl && returnUrl !== '/login') {
      sessionStorage.setItem(RETURN_URL_KEY, returnUrl)
    }
  }, [searchParams])

  // Redirect if already authenticated (but only after auth loading is complete)
  useEffect(() => {
    if (!authLoading && isAuthenticated) {
      // Get return URL from session storage, default to home
      const returnUrl = sessionStorage.getItem(RETURN_URL_KEY) || '/'

      // Clear the return URL to prevent future redirects
      sessionStorage.removeItem(RETURN_URL_KEY)

      // Prevent redirect loop: never redirect back to login
      if (returnUrl !== '/login') {
        router.push(returnUrl)
      } else {
        router.push('/')
      }
    }
  }, [isAuthenticated, authLoading, router])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      await login(emailOrUsername, password)

      // Get return URL from session storage
      const returnUrl = sessionStorage.getItem(RETURN_URL_KEY) || '/'

      // Clear the return URL
      sessionStorage.removeItem(RETURN_URL_KEY)

      // Redirect to return URL (or home if no return URL)
      // Prevent redirect loop: never redirect back to login
      if (returnUrl !== '/login') {
        router.push(returnUrl)
      } else {
        router.push('/')
      }
    } catch (err: any) {
      setError(err.message || 'Login failed. Please check your credentials.')
    } finally {
      setIsLoading(false)
    }
  }

  // Show loading state during auth check
  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600 dark:text-gray-400">Loading...</p>
        </div>
      </div>
    )
  }

  // Don't render form if already authenticated (will redirect via useEffect)
  if (isAuthenticated) {
    return null
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 px-4">
      <div className="max-w-md w-full space-y-8">
        <div>
          <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900 dark:text-white">
            Sign in to Curatore
          </h2>
          <p className="mt-2 text-center text-sm text-gray-600 dark:text-gray-400">
            Document processing and optimization platform
          </p>
        </div>

        <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
          {error && (
            <div className="rounded-md bg-red-50 dark:bg-red-900/20 p-4">
              <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          <div className="rounded-md shadow-sm space-y-4">
            <div>
              <label htmlFor="email-username" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Email or Username
              </label>
              <input
                id="email-username"
                name="email-username"
                type="text"
                autoComplete="username"
                required
                className="appearance-none relative block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 placeholder-gray-500 dark:placeholder-gray-400 text-gray-900 dark:text-white rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 focus:z-10 sm:text-sm bg-white dark:bg-gray-800"
                placeholder="Enter your email or username"
                value={emailOrUsername}
                onChange={(e) => setEmailOrUsername(e.target.value)}
                disabled={isLoading}
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                className="appearance-none relative block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 placeholder-gray-500 dark:placeholder-gray-400 text-gray-900 dark:text-white rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 focus:z-10 sm:text-sm bg-white dark:bg-gray-800"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isLoading}
              />
            </div>
          </div>

          <div>
            <Button
              type="submit"
              disabled={isLoading}
              className="w-full"
            >
              {isLoading ? 'Signing in...' : 'Sign in'}
            </Button>
          </div>

          <div className="mt-6 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
            <h3 className="text-sm font-semibold text-blue-900 dark:text-blue-100 mb-3">
              Default Credentials
            </h3>

            <div className="space-y-3 text-sm text-blue-800 dark:text-blue-200">
              <div>
                <p className="font-medium mb-1">Admin Account:</p>
                <p className="flex items-center justify-between">
                  <span>Email:</span>
                  <code className="bg-blue-100 dark:bg-blue-800 px-2 py-1 rounded text-xs">admin@example.com</code>
                </p>
                <p className="flex items-center justify-between mt-1">
                  <span>Password:</span>
                  <code className="bg-blue-100 dark:bg-blue-800 px-2 py-1 rounded text-xs">changeme</code>
                </p>
              </div>

              <div className="pt-2 border-t border-blue-200 dark:border-blue-700">
                <p className="text-xs italic">
                  Change the default password immediately after first login.
                  Additional users can be created by admins in the Users section.
                </p>
              </div>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}

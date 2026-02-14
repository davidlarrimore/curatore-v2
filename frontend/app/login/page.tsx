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

import { useState, FormEvent, useEffect, useCallback, useRef, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { systemApi } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import toast from 'react-hot-toast'

const RETURN_URL_KEY = 'auth_return_url'
type LoginStage = 'idle' | 'submitting' | 'finalizing'

function LoginContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { login, isAuthenticated, isLoading: authLoading } = useAuth()
  const [emailOrUsername, setEmailOrUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loginStage, setLoginStage] = useState<LoginStage>('idle')
  const hasRedirected = useRef(false)

  const getLoginErrorMessage = (err: unknown) => {
    if (err && typeof err === 'object') {
      const error = err as { message?: string; detail?: string | { detail?: string } }
      if (typeof error.detail === 'string') return error.detail
      if (error.detail && typeof error.detail === 'object' && typeof error.detail.detail === 'string') return error.detail.detail
      if (typeof error.message === 'string' && error.message.trim()) return error.message
    }
    return 'Invalid email/username or password.'
  }

  const resolveReturnUrl = useCallback(() => {
    const returnUrl = sessionStorage.getItem(RETURN_URL_KEY) || '/'
    return returnUrl !== '/login' ? returnUrl : '/'
  }, [])

  const redirectToReturnUrl = useCallback(() => {
    if (hasRedirected.current) return
    hasRedirected.current = true
    const returnUrl = resolveReturnUrl()
    sessionStorage.removeItem(RETURN_URL_KEY)
    router.replace(returnUrl)
  }, [resolveReturnUrl, router])

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
      setLoginStage('finalizing')
      redirectToReturnUrl()
    }
  }, [isAuthenticated, authLoading, redirectToReturnUrl])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setLoginStage('submitting')

    try {
      const availability = await Promise.race([
        systemApi.checkAvailability(),
        new Promise<boolean>((_, reject) => setTimeout(() => reject(new Error('Health check timeout')), 5000)),
      ])

      if (!availability) {
        toast.error('Curatore is restarting. Please wait and try again.')
        setLoginStage('idle')
        return
      }

      await login(emailOrUsername, password)
      setLoginStage('finalizing')
      if (isAuthenticated) {
        redirectToReturnUrl()
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.message === 'Health check timeout') {
        toast.error('Curatore is restarting. Please wait and try again.')
        setLoginStage('idle')
        return
      }
      const message = getLoginErrorMessage(err)
      setError(message)
      toast.error(message)
      setLoginStage('idle')
    }
  }

  const isLoading = loginStage !== 'idle'
  const statusMessage = loginStage === 'finalizing'
    ? 'Finishing your sign-in and preparing your workspace...'
    : 'Signing you in. This may take a moment...'

  // Show loading state during auth check
  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600 dark:text-gray-400">Checking your session...</p>
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

          {isLoading && (
            <div className="rounded-md bg-blue-50 dark:bg-blue-900/20 p-4 border border-blue-200 dark:border-blue-800">
              <div className="flex items-center gap-3">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-blue-600 border-t-transparent"></div>
                <p className="text-sm text-blue-800 dark:text-blue-100">{statusMessage}</p>
              </div>
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

          <div className="space-y-3">
            <Button
              type="submit"
              disabled={isLoading}
              className="w-full"
            >
              {loginStage === 'finalizing' ? 'Finishing...' : isLoading ? 'Signing in...' : 'Sign in'}
            </Button>
            <div className="text-center">
              <a href="/forgot-password" className="text-sm text-blue-600 dark:text-blue-400 hover:underline">
                Forgot your password?
              </a>
            </div>
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

function LoginFallback() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
        <p className="text-gray-600 dark:text-gray-400">Loading...</p>
      </div>
    </div>
  )
}

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginFallback />}>
      <LoginContent />
    </Suspense>
  )
}

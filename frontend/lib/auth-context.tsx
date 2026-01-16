'use client'

/**
 * Authentication context provider for Curatore.
 *
 * Manages user authentication state, tokens, and session lifecycle with the following features:
 * - JWT token management (access + refresh tokens)
 * - Automatic token refresh before expiration
 * - Session expiration detection and handling
 * - Graceful logout on authentication errors (401)
 * - Redirect to login on session expiration
 *
 * Anti-redirect-loop measures:
 * - Tracks redirect state to prevent multiple simultaneous redirects
 * - Only redirects when not already on login page
 * - Clears redirect state after navigation
 * - Stores return URL for post-login redirect
 *
 * Token lifecycle:
 * - Access tokens expire in 60 minutes
 * - Refresh tokens expire in 30 days
 * - Automatic refresh every 50 minutes
 * - Manual refresh on 401 errors
 */

import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { authApi } from './api'

interface User {
  id: string
  email: string
  username: string
  full_name?: string
  role: string
  organization_id: string
  organization_name: string
  is_active: boolean
}

interface AuthContextType {
  user: User | null
  token: string | null
  isLoading: boolean
  isAuthenticated: boolean
  login: (emailOrUsername: string, password: string) => Promise<void>
  logout: (reason?: string) => void
  refreshUserData: () => Promise<void>
  handleUnauthorized: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

const TOKEN_KEY = 'curatore_access_token'
const REFRESH_TOKEN_KEY = 'curatore_refresh_token'
const RETURN_URL_KEY = 'auth_return_url'
const TOKEN_REFRESH_INTERVAL = 50 * 60 * 1000 // 50 minutes (tokens expire in 60)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Track if we're currently redirecting to prevent loops
  const isRedirecting = useRef(false)

  // Load user data from token
  const loadUserFromToken = useCallback(async (accessToken: string) => {
    try {
      const userData = await authApi.getCurrentUser(accessToken)
      setUser(userData)
      setToken(accessToken)
      return true
    } catch (error: any) {
      // Check if it's a 401 error (unauthorized/expired token)
      if (error?.status === 401) {
        console.log('Token expired or invalid - will attempt refresh')
      } else {
        // For other errors, log them
        console.error('Failed to load user from token:', error)
      }

      // Clear invalid tokens
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(REFRESH_TOKEN_KEY)
      setToken(null)
      setUser(null)
      return false
    }
  }, [])

  // Refresh access token using refresh token
  const refreshAccessToken = useCallback(async () => {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
    if (!refreshToken) return false

    try {
      const response = await authApi.refreshToken(refreshToken)
      localStorage.setItem(TOKEN_KEY, response.access_token)
      localStorage.setItem(REFRESH_TOKEN_KEY, response.refresh_token)
      await loadUserFromToken(response.access_token)
      return true
    } catch (error: any) {
      // Only log as error if it's not a 401 (which is expected for expired tokens)
      if (error?.status === 401) {
        console.log('Refresh token expired or invalid')
      } else {
        console.error('Failed to refresh token:', error)
      }
      // Clear invalid tokens
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(REFRESH_TOKEN_KEY)
      setToken(null)
      setUser(null)
      return false
    }
  }, [loadUserFromToken])

  // Initialize auth state on mount
  useEffect(() => {
    const initAuth = async () => {
      const storedToken = localStorage.getItem(TOKEN_KEY)
      if (storedToken) {
        const success = await loadUserFromToken(storedToken)
        if (!success) {
          // Try refreshing if loading failed
          const refreshSuccess = await refreshAccessToken()

          // If both token loading and refresh failed, we have an invalid session
          if (!refreshSuccess) {
            console.log('Auth initialization failed - clearing invalid tokens')

            // Clear the invalid tokens
            localStorage.removeItem(TOKEN_KEY)
            localStorage.removeItem(REFRESH_TOKEN_KEY)

            // Only redirect to login if we're on a protected route
            // For now, we'll just clear tokens and let the app work without auth
            // Individual pages can use ProtectedRoute if they need authentication
          }
        }
      }
      setIsLoading(false)
    }

    initAuth()
  }, [loadUserFromToken, refreshAccessToken])

  // Set up periodic token refresh
  useEffect(() => {
    if (!token) return

    const intervalId = setInterval(() => {
      refreshAccessToken()
    }, TOKEN_REFRESH_INTERVAL)

    return () => clearInterval(intervalId)
  }, [token, refreshAccessToken])

  const login = async (emailOrUsername: string, password: string) => {
    try {
      const response = await authApi.login(emailOrUsername, password)
      localStorage.setItem(TOKEN_KEY, response.access_token)
      localStorage.setItem(REFRESH_TOKEN_KEY, response.refresh_token)
      setUser(response.user as User)
      setToken(response.access_token)
    } catch (error) {
      console.error('Login failed:', error)
      throw error
    }
  }

  /**
   * Logout function with optional reason tracking.
   *
   * @param reason - Optional reason for logout (e.g., 'session_expired', 'user_action')
   */
  const logout = useCallback((reason?: string) => {
    console.log('Logging out:', reason || 'user action')

    // Clear tokens and user state
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    setUser(null)
    setToken(null)

    // Store current path as return URL (if not already on login page)
    // This allows users to return to their intended page after re-authenticating
    if (pathname && pathname !== '/login') {
      sessionStorage.setItem(RETURN_URL_KEY, pathname)
    }

    // Redirect to login page (with loop prevention)
    if (!isRedirecting.current && pathname !== '/login') {
      isRedirecting.current = true
      router.push('/login')

      // Reset redirect flag after navigation
      setTimeout(() => {
        isRedirecting.current = false
      }, 1000)
    }
  }, [pathname, router])

  /**
   * Handle unauthorized (401) errors from API calls.
   *
   * This method should be called when an API request returns a 401 status,
   * indicating the user's session has expired or the token is invalid.
   *
   * It will:
   * 1. Clear authentication state
   * 2. Store the current path for return after re-authentication
   * 3. Redirect to the login page
   *
   * Anti-loop measures:
   * - Checks if already redirecting
   * - Checks if already on login page
   * - Uses timeout to reset redirect flag
   */
  const handleUnauthorized = useCallback(() => {
    console.log('Session expired or unauthorized, redirecting to login')

    // Only handle if we're not already redirecting and not on login page
    if (!isRedirecting.current && pathname !== '/login') {
      logout('session_expired')
    }
  }, [logout, pathname])

  const refreshUserData = async () => {
    if (!token) return
    await loadUserFromToken(token)
  }

  const value: AuthContextType = {
    user,
    token,
    isLoading,
    isAuthenticated: !!user && !!token,
    login,
    logout,
    refreshUserData,
    handleUnauthorized,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

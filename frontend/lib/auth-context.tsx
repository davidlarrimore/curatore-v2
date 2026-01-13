'use client'

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
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
  logout: () => void
  refreshUserData: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

const TOKEN_KEY = 'curatore_access_token'
const REFRESH_TOKEN_KEY = 'curatore_refresh_token'
const TOKEN_REFRESH_INTERVAL = 50 * 60 * 1000 // 50 minutes (tokens expire in 60)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Load user data from token
  const loadUserFromToken = useCallback(async (accessToken: string) => {
    try {
      const userData = await authApi.getCurrentUser(accessToken)
      setUser(userData)
      setToken(accessToken)
      return true
    } catch (error) {
      console.error('Failed to load user from token:', error)
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
    } catch (error) {
      console.error('Failed to refresh token:', error)
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
          await refreshAccessToken()
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

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    setUser(null)
    setToken(null)
  }

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

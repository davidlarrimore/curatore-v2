'use client'

/**
 * Organization context provider for Curatore.
 *
 * Manages organization switching for system admins. Regular users have a fixed
 * organization context from their user record. System admins can switch between
 * organizations or operate in "system context" (no specific org).
 *
 * Key features:
 * - Organization state derived from URL (/orgs/[orgSlug]/* or /system/*)
 * - Organization switching via URL navigation
 * - Provides X-Organization-Id header for API calls
 * - Visual mode indicator (org vs system)
 */

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { useAuth } from './auth-context'
import { organizationsApi, setOrgContext } from './api'
import toast from 'react-hot-toast'

export interface Organization {
  id: string
  name: string
  display_name: string
  slug: string
  is_active: boolean
}

export type ContextMode = 'organization' | 'system'

interface OrganizationContextType {
  // Current organization (null for system context)
  currentOrganization: Organization | null

  // Available organizations (only populated for admins)
  availableOrganizations: Organization[]

  // Current mode
  mode: ContextMode

  // Is in system context (admin only)
  isSystemContext: boolean

  // Loading state
  isLoading: boolean

  // Switch to a specific organization (admin only)
  switchOrganization: (orgId: string) => void

  // Switch to system context (admin only)
  switchToSystemContext: () => void

  // Get the organization ID header value (null for system context)
  getOrganizationHeader: () => string | null

  // Refresh available organizations list
  refreshOrganizations: () => Promise<void>
}

const OrganizationContext = createContext<OrganizationContextType | undefined>(undefined)

// ORG_CONTEXT_KEY removed — org context now managed via setOrgContext() in api.ts

export function OrganizationProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const { user, isAuthenticated, isAdmin, token } = useAuth()
  const [currentOrganization, setCurrentOrganization] = useState<Organization | null>(null)
  const [availableOrganizations, setAvailableOrganizations] = useState<Organization[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [mode, setMode] = useState<ContextMode>('organization')

  // Extract org slug from URL
  const orgSlugMatch = pathname?.match(/^\/orgs\/([^\/]+)/)
  const urlOrgSlug = orgSlugMatch ? orgSlugMatch[1] : null

  // Check if we're in a system route
  const isSystemRoute = pathname?.startsWith('/system')

  // Load available organizations for admins
  const refreshOrganizations = useCallback(async () => {
    if (!isAuthenticated || !isAdmin || !token) {
      setAvailableOrganizations([])
      return
    }

    try {
      const response = await organizationsApi.listOrganizations(token)
      // Filter out the reserved system org (belt-and-suspenders — backend also filters)
      const orgs = (response.organizations || []).filter(
        (o: { slug: string }) => o.slug !== '__system__'
      )
      setAvailableOrganizations(orgs)
    } catch (error) {
      console.error('Failed to load organizations:', error)
      setAvailableOrganizations([])
    }
  }, [isAuthenticated, isAdmin, token])

  // Initialize organization context
  useEffect(() => {
    const initContext = async () => {
      setIsLoading(true)

      if (!isAuthenticated || !user) {
        setCurrentOrganization(null)
        setMode('organization')
        setIsLoading(false)
        return
      }

      // Non-admin users: use their organization
      if (!isAdmin) {
        if (user.organization_id) {
          try {
            const org = await organizationsApi.getCurrentOrganization(token!)
            setCurrentOrganization(org)
            setOrgContext(org.id)
          } catch {
            // Fallback to basic info from user
            setCurrentOrganization({
              id: user.organization_id,
              name: user.organization_name || 'Unknown',
              display_name: user.organization_name || 'Unknown',
              slug: '',
              is_active: true,
            })
            setOrgContext(user.organization_id)
          }
        }
        setMode('organization')
        setIsLoading(false)
        return
      }

      // Admin users: set mode from URL immediately (before async work)
      if (isSystemRoute) {
        setMode('system')
        setCurrentOrganization(null)
        setOrgContext(null)
      }

      // Admin users: load available organizations (context derived from URL)
      await refreshOrganizations()
      setIsLoading(false)
    }

    initContext()
  }, [user, isAuthenticated, isAdmin, token, refreshOrganizations])

  // Sync context from URL for admin users
  useEffect(() => {
    if (!isAuthenticated || !isAdmin) return

    // System route can be set immediately — no need to wait for org list
    if (isSystemRoute) {
      // System route - system context
      if (mode !== 'system') {
        setCurrentOrganization(null)
        setMode('system')
        setOrgContext(null)
      }
    } else if (urlOrgSlug && !isLoading) {
      // Org route - find org by slug (wait for org list to load)
      const org = availableOrganizations.find(o => o.slug === urlOrgSlug)
      if (org && currentOrganization?.id !== org.id) {
        setCurrentOrganization(org)
        setMode('organization')
        setOrgContext(org.id)
      }
    }
  }, [urlOrgSlug, isSystemRoute, availableOrganizations, currentOrganization, isAuthenticated, isAdmin, isLoading, mode])

  // Switch to a specific organization via URL navigation
  const switchOrganization = useCallback((orgId: string) => {
    if (!isAdmin) return

    // Don't switch if already on this org
    if (currentOrganization?.id === orgId && mode === 'organization') {
      return
    }

    // Find org in already-loaded list
    const org = availableOrganizations.find(o => o.id === orgId)
    if (!org) {
      toast.error('Organization not found', { id: 'switch-org-error' })
      return
    }

    toast.success(`Switched to ${org.display_name}`, { id: `switch-org-${orgId}` })

    // Navigate to org dashboard - URL change will sync context
    if (org.slug) {
      router.push(`/orgs/${org.slug}`)
    }
  }, [isAdmin, currentOrganization, mode, availableOrganizations, router])

  // Switch to system context via URL navigation
  const switchToSystemContext = useCallback(() => {
    if (!isAdmin) return

    // Don't switch if already in system mode
    if (mode === 'system') {
      return
    }

    toast.success('Switched to System Administration', { id: 'switch-system' })
    // Navigate to system dashboard - URL change will sync context
    router.push('/system')
  }, [isAdmin, mode, router])

  // Get header value for API calls
  const getOrganizationHeader = useCallback((): string | null => {
    if (mode === 'system') {
      return null
    }
    return currentOrganization?.id || null
  }, [mode, currentOrganization])

  const value: OrganizationContextType = {
    currentOrganization,
    availableOrganizations,
    mode,
    isSystemContext: mode === 'system',
    isLoading,
    switchOrganization,
    switchToSystemContext,
    getOrganizationHeader,
    refreshOrganizations,
  }

  return (
    <OrganizationContext.Provider value={value}>
      {children}
    </OrganizationContext.Provider>
  )
}

export function useOrganization() {
  const context = useContext(OrganizationContext)
  if (context === undefined) {
    throw new Error('useOrganization must be used within an OrganizationProvider')
  }
  return context
}

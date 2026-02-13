'use client'

/**
 * URL-based organization context provider.
 *
 * Extracts organization slug from URL params and provides org context to children.
 * This is used for the /orgs/[orgSlug]/* routes.
 *
 * Key features:
 * - Extracts org slug from URL
 * - Fetches organization details from API
 * - Validates user access to the organization
 * - Provides org ID for API calls via X-Organization-Id header
 * - Sets localStorage for API client compatibility during migration
 */

import React, { createContext, useContext, useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from './auth-context'
import { organizationsApi, type Organization } from './api'

const ORG_CONTEXT_KEY = 'curatore_org_context'

interface OrgUrlContextType {
  // Current organization from URL
  organization: Organization | null

  // Organization slug from URL
  orgSlug: string | null

  // Loading state
  isLoading: boolean

  // Error state
  error: string | null

  // Get the organization ID for API headers
  getOrganizationId: () => string | null
}

const OrgUrlContext = createContext<OrgUrlContextType | undefined>(undefined)

export function OrgUrlProvider({ children }: { children: React.ReactNode }) {
  const params = useParams()
  const router = useRouter()
  const { token, isAuthenticated, isAdmin, user, isLoading: authLoading } = useAuth()

  const [organization, setOrganization] = useState<Organization | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Extract org slug from URL params
  const orgSlug = typeof params?.orgSlug === 'string' ? params.orgSlug : null

  // Fetch organization by slug
  useEffect(() => {
    const fetchOrganization = async () => {
      // Wait for auth to load
      if (authLoading) return

      // No org slug in URL - shouldn't happen in /orgs/[orgSlug]/* routes
      if (!orgSlug) {
        setIsLoading(false)
        setError('No organization specified')
        return
      }

      // Not authenticated
      if (!isAuthenticated || !token) {
        setIsLoading(false)
        setError('Not authenticated')
        return
      }

      setIsLoading(true)
      setError(null)

      try {
        const org = await organizationsApi.getOrganizationBySlug(token, orgSlug)
        setOrganization(org)

        // Set localStorage for API client compatibility
        // This ensures API calls include X-Organization-Id header
        if (typeof window !== 'undefined') {
          localStorage.setItem(ORG_CONTEXT_KEY, org.id)
        }
      } catch (err: unknown) {
        console.error('Failed to fetch organization:', err)

        const httpErr = err as { status?: number }
        if (httpErr?.status === 404) {
          setError('Organization not found')
        } else if (httpErr?.status === 403) {
          setError('Access denied to this organization')
        } else {
          setError('Failed to load organization')
        }

        // Redirect to appropriate page on error
        if (isAdmin) {
          router.push('/system')
        } else if (user?.organization_id) {
          // Try to get user's org slug and redirect there
          // For now, just redirect to root which will handle the redirect
          router.push('/')
        } else {
          router.push('/')
        }
      } finally {
        setIsLoading(false)
      }
    }

    fetchOrganization()
  }, [orgSlug, token, isAuthenticated, authLoading, isAdmin, user, router])

  // Get organization ID for API headers
  const getOrganizationId = (): string | null => {
    return organization?.id || null
  }

  const value: OrgUrlContextType = {
    organization,
    orgSlug,
    isLoading,
    error,
    getOrganizationId,
  }

  return (
    <OrgUrlContext.Provider value={value}>
      {children}
    </OrgUrlContext.Provider>
  )
}

export function useOrgUrl() {
  const context = useContext(OrgUrlContext)
  if (context === undefined) {
    throw new Error('useOrgUrl must be used within an OrgUrlProvider')
  }
  return context
}

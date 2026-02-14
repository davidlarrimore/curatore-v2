'use client'

/**
 * System Organizations page.
 *
 * Lists all organizations in the system for admin management.
 */

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import {
  Building2,
  Plus,
  Search,
  CheckCircle,
  XCircle,
  Users,
  ExternalLink,
} from 'lucide-react'
import { organizationsApi, Organization } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import { useOrganization } from '@/lib/organization-context'

export default function SystemOrganizationsPage() {
  const router = useRouter()
  const { token } = useAuth()
  const { switchOrganization } = useOrganization()
  const [organizations, setOrganizations] = useState<Organization[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const loadOrganizations = async () => {
      if (!token) return

      try {
        const response = await organizationsApi.listOrganizations(token)
        setOrganizations(response.organizations || [])
      } catch (error) {
        console.error('Failed to load organizations:', error)
      } finally {
        setIsLoading(false)
      }
    }

    loadOrganizations()
  }, [token])

  const filteredOrgs = searchQuery
    ? organizations.filter(
        (org) =>
          org.display_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          org.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          org.slug?.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : organizations

  const handleSwitchToOrg = (orgId: string) => {
    switchOrganization(orgId)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-600"></div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Organizations
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Manage all organizations in the system
          </p>
        </div>
        <button
          onClick={() => router.push('/system/organizations/new')}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-amber-600 rounded-lg hover:bg-amber-700 transition-colors"
        >
          <Plus className="h-4 w-4" />
          New Organization
        </button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400" />
        <input
          type="text"
          placeholder="Search organizations..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full pl-10 pr-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
        />
      </div>

      {/* Organizations Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filteredOrgs.map((org) => (
          <div
            key={org.id}
            className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 hover:border-amber-300 dark:hover:border-amber-700 transition-colors"
          >
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-amber-100 dark:bg-amber-900/30 rounded-lg">
                  <Building2 className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900 dark:text-white">
                    {org.display_name}
                  </h3>
                  {org.slug && (
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {org.slug}
                    </p>
                  )}
                </div>
              </div>
              {org.is_active ? (
                <span className="flex items-center gap-1 px-2 py-1 text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400 rounded-full">
                  <CheckCircle className="h-3 w-3" />
                  Active
                </span>
              ) : (
                <span className="flex items-center gap-1 px-2 py-1 text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400 rounded-full">
                  <XCircle className="h-3 w-3" />
                  Inactive
                </span>
              )}
            </div>

            <div className="flex items-center gap-4 text-sm text-gray-500 dark:text-gray-400 mb-4">
              <div className="flex items-center gap-1">
                <Users className="h-4 w-4" />
                <span>- users</span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => handleSwitchToOrg(org.id)}
                className="flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-amber-700 bg-amber-100 rounded-lg hover:bg-amber-200 transition-colors"
              >
                <ExternalLink className="h-4 w-4" />
                Switch to Org
              </button>
              <button
                onClick={() => router.push(`/orgs/${org.slug}/admin/settings`)}
                className="px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
              >
                Details
              </button>
            </div>
          </div>
        ))}
      </div>

      {filteredOrgs.length === 0 && (
        <div className="text-center py-12">
          <Building2 className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
          <p className="text-gray-500 dark:text-gray-400">
            {searchQuery
              ? 'No organizations match your search'
              : 'No organizations found'}
          </p>
        </div>
      )}
    </div>
  )
}

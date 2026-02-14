'use client'

/**
 * System Data Connections page.
 *
 * Manage per-org enablement of data source integrations (SAM.gov, SharePoint,
 * Salesforce, Forecasts, Web Scraping). Shows the data source catalog with
 * enablement counts and allows toggling connections per organization.
 */

import { useState, useEffect } from 'react'
import {
  Plug,
  Building2,
  FolderSync,
  Globe,
  TrendingUp,
  Database,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  CheckCircle,
  XCircle,
} from 'lucide-react'
import { useAuth } from '@/lib/auth-context'
import {
  dataConnectionsApi,
  organizationsApi,
  type DataConnectionCatalogEntry,
} from '@/lib/api'
import toast from 'react-hot-toast'

interface Organization {
  id: string
  name: string
  display_name: string
  slug: string
  is_active: boolean
}

interface OrgToggleState {
  [orgId: string]: boolean
}

const SOURCE_TYPE_ICONS: Record<string, { icon: React.ComponentType<{ className?: string }>; color: string }> = {
  sam_gov: { icon: Building2, color: 'text-blue-600 dark:text-blue-400 bg-blue-100 dark:bg-blue-900/30' },
  sharepoint: { icon: FolderSync, color: 'text-teal-600 dark:text-teal-400 bg-teal-100 dark:bg-teal-900/30' },
  web_scrape: { icon: Globe, color: 'text-indigo-600 dark:text-indigo-400 bg-indigo-100 dark:bg-indigo-900/30' },
  forecast_ag: { icon: TrendingUp, color: 'text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/30' },
  forecast_apfs: { icon: TrendingUp, color: 'text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/30' },
  forecast_state: { icon: TrendingUp, color: 'text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/30' },
  salesforce: { icon: Database, color: 'text-cyan-600 dark:text-cyan-400 bg-cyan-100 dark:bg-cyan-900/30' },
}

export default function SystemConnectionsPage() {
  const { token } = useAuth()
  const [catalog, setCatalog] = useState<DataConnectionCatalogEntry[]>([])
  const [organizations, setOrganizations] = useState<Organization[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [expandedSource, setExpandedSource] = useState<string | null>(null)
  const [orgStates, setOrgStates] = useState<Record<string, OrgToggleState>>({})
  const [loadingOrgs, setLoadingOrgs] = useState<Record<string, boolean>>({})
  const [togglingKey, setTogglingKey] = useState<string | null>(null)

  const loadData = async () => {
    if (!token) return

    try {
      const [catalogData, orgsData] = await Promise.all([
        dataConnectionsApi.getCatalog(token),
        organizationsApi.listOrganizations(token),
      ])
      setCatalog(catalogData.data_connections)
      setOrganizations(
        (orgsData.organizations as Organization[]).filter((o) => o.is_active)
      )
    } catch (error) {
      console.error('Failed to load data connections:', error)
      toast.error('Failed to load data connections')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [token])

  const loadOrgStates = async (sourceType: string) => {
    if (loadingOrgs[sourceType]) return
    setLoadingOrgs((prev) => ({ ...prev, [sourceType]: true }))

    try {
      const results: Record<string, boolean> = {}
      await Promise.all(
        organizations.map(async (org) => {
          const data = await dataConnectionsApi.getOrgStatus(token!, org.id)
          const dc = data.data_connections.find((d) => d.source_type === sourceType)
          results[org.id] = dc?.is_enabled ?? false
        })
      )
      setOrgStates((prev) => ({ ...prev, [sourceType]: results }))
    } catch (error) {
      console.error('Failed to load org states:', error)
      toast.error('Failed to load organization states')
    } finally {
      setLoadingOrgs((prev) => ({ ...prev, [sourceType]: false }))
    }
  }

  const handleExpand = (sourceType: string) => {
    if (expandedSource === sourceType) {
      setExpandedSource(null)
      return
    }
    setExpandedSource(sourceType)
    if (!orgStates[sourceType]) {
      loadOrgStates(sourceType)
    }
  }

  const handleToggle = async (sourceType: string, orgId: string, currentState: boolean) => {
    const key = `${sourceType}:${orgId}`
    if (togglingKey === key) return
    setTogglingKey(key)

    try {
      await dataConnectionsApi.toggleConnection(sourceType, orgId, !currentState, token!)
      setOrgStates((prev) => ({
        ...prev,
        [sourceType]: {
          ...prev[sourceType],
          [orgId]: !currentState,
        },
      }))

      // Update catalog counts
      setCatalog((prev) =>
        prev.map((entry) => {
          if (entry.source_type !== sourceType) return entry
          return {
            ...entry,
            enabled_org_count: entry.enabled_org_count + (currentState ? -1 : 1),
          }
        })
      )

      toast.success(
        `${sourceType} ${!currentState ? 'enabled' : 'disabled'} for ${organizations.find((o) => o.id === orgId)?.display_name}`
      )
    } catch (error) {
      console.error('Failed to toggle connection:', error)
      toast.error('Failed to toggle connection')
    } finally {
      setTogglingKey(null)
    }
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
            Data Connections
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Enable or disable data source integrations per organization
          </p>
        </div>
        <button
          onClick={() => {
            setIsLoading(true)
            loadData()
          }}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {/* Data Connection Cards */}
      <div className="space-y-3">
        {catalog.map((entry) => {
          const iconConfig = SOURCE_TYPE_ICONS[entry.source_type] || {
            icon: Plug,
            color: 'text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-900/30',
          }
          const Icon = iconConfig.icon
          const isExpanded = expandedSource === entry.source_type
          const states = orgStates[entry.source_type]
          const isLoadingStates = loadingOrgs[entry.source_type]

          return (
            <div
              key={entry.source_type}
              className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden"
            >
              {/* Card Header */}
              <button
                onClick={() => handleExpand(entry.source_type)}
                className="w-full flex items-center gap-4 p-4 hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors text-left"
              >
                <div className={`p-2.5 rounded-lg ${iconConfig.color}`}>
                  <Icon className="h-5 w-5" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-gray-900 dark:text-white">
                    {entry.display_name}
                  </h3>
                  {entry.description && (
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-1">
                      {entry.description}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <span
                    className={`px-2.5 py-1 text-xs font-medium rounded-full ${
                      entry.enabled_org_count > 0
                        ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400'
                        : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
                    }`}
                  >
                    {entry.enabled_org_count}/{entry.total_org_count} orgs
                  </span>
                  {isExpanded ? (
                    <ChevronUp className="h-4 w-4 text-gray-400" />
                  ) : (
                    <ChevronDown className="h-4 w-4 text-gray-400" />
                  )}
                </div>
              </button>

              {/* Expanded: Org Toggle Table */}
              {isExpanded && (
                <div className="border-t border-gray-200 dark:border-gray-700">
                  {isLoadingStates ? (
                    <div className="flex items-center justify-center py-8">
                      <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-amber-600"></div>
                      <span className="ml-2 text-sm text-gray-500">Loading organizations...</span>
                    </div>
                  ) : (
                    <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                      <thead className="bg-gray-50 dark:bg-gray-900/50">
                        <tr>
                          <th className="px-6 py-2.5 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Organization
                          </th>
                          <th className="px-6 py-2.5 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Status
                          </th>
                          <th className="px-6 py-2.5 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Action
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                        {organizations.map((org) => {
                          const isOrgEnabled = states?.[org.id] ?? false
                          const toggleKey = `${entry.source_type}:${org.id}`
                          const isToggling = togglingKey === toggleKey

                          return (
                            <tr key={org.id} className="hover:bg-gray-50 dark:hover:bg-gray-900/30">
                              <td className="px-6 py-3 whitespace-nowrap">
                                <div className="flex items-center gap-2">
                                  <Building2 className="h-4 w-4 text-gray-400" />
                                  <span className="text-sm font-medium text-gray-900 dark:text-white">
                                    {org.display_name}
                                  </span>
                                  <span className="text-xs text-gray-400">({org.slug})</span>
                                </div>
                              </td>
                              <td className="px-6 py-3 whitespace-nowrap">
                                {isOrgEnabled ? (
                                  <span className="flex items-center gap-1.5 text-sm text-emerald-600 dark:text-emerald-400">
                                    <CheckCircle className="h-4 w-4" />
                                    Enabled
                                  </span>
                                ) : (
                                  <span className="flex items-center gap-1.5 text-sm text-gray-400 dark:text-gray-500">
                                    <XCircle className="h-4 w-4" />
                                    Disabled
                                  </span>
                                )}
                              </td>
                              <td className="px-6 py-3 whitespace-nowrap text-right">
                                <button
                                  onClick={() => handleToggle(entry.source_type, org.id, isOrgEnabled)}
                                  disabled={isToggling}
                                  className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                                    isOrgEnabled
                                      ? 'text-red-700 bg-red-50 hover:bg-red-100 dark:text-red-400 dark:bg-red-900/20 dark:hover:bg-red-900/30'
                                      : 'text-emerald-700 bg-emerald-50 hover:bg-emerald-100 dark:text-emerald-400 dark:bg-emerald-900/20 dark:hover:bg-emerald-900/30'
                                  } ${isToggling ? 'opacity-50 cursor-not-allowed' : ''}`}
                                >
                                  {isToggling ? '...' : isOrgEnabled ? 'Disable' : 'Enable'}
                                </button>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  )}

                  {/* Capabilities */}
                  {entry.capabilities && entry.capabilities.length > 0 && (
                    <div className="px-6 py-3 bg-gray-50 dark:bg-gray-900/30 border-t border-gray-200 dark:border-gray-700">
                      <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">
                        Capabilities
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {entry.capabilities.map((cap, i) => (
                          <span
                            key={i}
                            className="px-2 py-0.5 text-xs text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 rounded"
                          >
                            {cap}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {catalog.length === 0 && (
        <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
          <Plug className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
          <p className="text-gray-500 dark:text-gray-400 mb-2">
            No data connections available
          </p>
          <p className="text-sm text-gray-400 dark:text-gray-500">
            Data connections are defined in the system configuration.
          </p>
        </div>
      )}
    </div>
  )
}

'use client'

/**
 * System Dashboard page.
 *
 * Shows cross-organization metrics, system health, and admin overview.
 */

import { useState, useEffect } from 'react'
import {
  Building2,
  Users,
  Server,
  Activity,
  CheckCircle,
  AlertTriangle,
  XCircle,
  RefreshCw,
} from 'lucide-react'
import { systemApi, organizationsApi } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'

interface HealthComponent {
  name: string
  status: string
  message?: string
  version?: string
}

interface SystemHealth {
  status: string
  overall_status?: string
  components: HealthComponent[]
  version?: string
}

interface OrgSummary {
  total: number
  active: number
}

export default function SystemDashboardPage() {
  const { token } = useAuth()
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [orgSummary, setOrgSummary] = useState<OrgSummary>({ total: 0, active: 0 })
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)

  const loadData = async () => {
    if (!token) return

    try {
      const [healthResult, orgsResult] = await Promise.allSettled([
        systemApi.getComprehensiveHealth(),
        organizationsApi.listOrganizations(token),
      ])

      if (healthResult.status === 'fulfilled') {
        const healthData = healthResult.value
        // Transform components object to array
        const componentsArray: HealthComponent[] = healthData.components
          ? Object.entries(healthData.components as Record<string, Record<string, unknown>>).map(([name, data]) => ({
              name: (data.name as string) || name,
              status: (data.status as string) || 'unknown',
              message: (data.message as string) || (data.error as string),
              version: data.version as string | undefined,
            }))
          : []
        setHealth({
          status: healthData.overall_status || healthData.status || 'unknown',
          version: healthData.components?.backend?.version,
          components: componentsArray,
        })
      }

      if (orgsResult.status === 'fulfilled') {
        const orgs = orgsResult.value.organizations || []
        setOrgSummary({
          total: orgs.length,
          active: orgs.filter((o: { is_active: boolean }) => o.is_active).length,
        })
      }
    } catch (error) {
      console.error('Failed to load system data:', error)
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [token])

  const handleRefresh = () => {
    setIsRefreshing(true)
    loadData()
  }

  const getStatusIcon = (status: string) => {
    switch (status.toLowerCase()) {
      case 'healthy':
      case 'ok':
        return <CheckCircle className="h-5 w-5 text-green-500" />
      case 'degraded':
      case 'warning':
        return <AlertTriangle className="h-5 w-5 text-amber-500" />
      default:
        return <XCircle className="h-5 w-5 text-red-500" />
    }
  }

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'healthy':
      case 'ok':
        return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
      case 'degraded':
      case 'warning':
        return 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400'
      default:
        return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
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
            System Dashboard
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Cross-organization metrics and system health
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={isRefreshing}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-amber-700 bg-amber-100 rounded-lg hover:bg-amber-200 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-gray-800 rounded-xl p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-amber-100 dark:bg-amber-900/30 rounded-lg">
              <Building2 className="h-6 w-6 text-amber-600 dark:text-amber-400" />
            </div>
            <div>
              <p className="text-sm text-gray-500 dark:text-gray-400">Organizations</p>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">
                {orgSummary.total}
              </p>
              <p className="text-xs text-gray-400">{orgSummary.active} active</p>
            </div>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
              <Users className="h-6 w-6 text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-sm text-gray-500 dark:text-gray-400">Total Users</p>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">-</p>
              <p className="text-xs text-gray-400">across all orgs</p>
            </div>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-green-100 dark:bg-green-900/30 rounded-lg">
              <Server className="h-6 w-6 text-green-600 dark:text-green-400" />
            </div>
            <div>
              <p className="text-sm text-gray-500 dark:text-gray-400">Services</p>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">
                {health?.components?.length || 0}
              </p>
              <p className="text-xs text-gray-400">monitored</p>
            </div>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-4">
            <div className={`p-3 rounded-lg ${
              health?.status === 'healthy'
                ? 'bg-green-100 dark:bg-green-900/30'
                : 'bg-amber-100 dark:bg-amber-900/30'
            }`}>
              <Activity className={`h-6 w-6 ${
                health?.status === 'healthy'
                  ? 'text-green-600 dark:text-green-400'
                  : 'text-amber-600 dark:text-amber-400'
              }`} />
            </div>
            <div>
              <p className="text-sm text-gray-500 dark:text-gray-400">System Status</p>
              <p className="text-2xl font-bold text-gray-900 dark:text-white capitalize">
                {health?.status || 'Unknown'}
              </p>
              {health?.version && (
                <p className="text-xs text-gray-400">v{health.version}</p>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Health Components */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            System Components
          </h2>
        </div>
        <div className="divide-y divide-gray-200 dark:divide-gray-700">
          {health?.components?.map((component) => (
            <div
              key={component.name}
              className="px-6 py-4 flex items-center justify-between"
            >
              <div className="flex items-center gap-3">
                {getStatusIcon(component.status)}
                <div>
                  <p className="font-medium text-gray-900 dark:text-white">
                    {component.name}
                  </p>
                  {component.message && (
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {component.message}
                    </p>
                  )}
                </div>
              </div>
              <span className={`px-2.5 py-1 text-xs font-medium rounded-full ${getStatusColor(component.status)}`}>
                {component.status}
              </span>
            </div>
          ))}
          {(!health?.components || health.components.length === 0) && (
            <div className="px-6 py-8 text-center text-gray-500 dark:text-gray-400">
              No component data available
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

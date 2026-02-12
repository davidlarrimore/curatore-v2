'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { forecastsApi, ForecastSync } from '@/lib/api'
import { useActiveJobs } from '@/lib/context-shims'
import { useJobProgressByType } from '@/lib/useJobProgress'
import { JobProgressPanelByType } from '@/components/ui/JobProgressPanel'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  TrendingUp,
  Plus,
  RefreshCw,
  Clock,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Play,
  Settings,
  ChevronLeft,
  Pause,
  Calendar,
} from 'lucide-react'

// Source type display config
const sourceTypeConfig: Record<string, { label: string; color: string }> = {
  ag: {
    label: 'Acquisition Gateway',
    color: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
  },
  apfs: {
    label: 'DHS APFS',
    color: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400',
  },
  state: {
    label: 'State Dept',
    color: 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400',
  },
}

const frequencyLabels: Record<string, string> = {
  manual: 'Manual',
  hourly: 'Hourly',
  daily: 'Daily',
}

function SyncListContent() {
  const { token } = useAuth()
  const router = useRouter()
  const { addJob, getJobsForResource } = useActiveJobs()
  const [syncs, setSyncs] = useState<ForecastSync[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [triggeringSync, setTriggeringSync] = useState<string | null>(null)

  const loadSyncs = useCallback(async (silent = false) => {
    if (!token) return
    if (!silent) {
      setLoading(true)
      setError(null)
    }

    try {
      const data = await forecastsApi.listSyncs(token, { limit: 100 })
      setSyncs(data.items)
    } catch (err: any) {
      if (!silent) {
        setError(err.message || 'Failed to load syncs')
      }
    } finally {
      if (!silent) {
        setLoading(false)
      }
    }
  }, [token])

  useEffect(() => {
    loadSyncs()
  }, [loadSyncs])

  // Track forecast sync jobs and auto-refresh on completion
  useJobProgressByType('forecast_sync', { onComplete: () => loadSyncs(true) })

  const handleTriggerSync = async (sync: ForecastSync) => {
    if (!token || triggeringSync) return

    setTriggeringSync(sync.id)
    try {
      const result = await forecastsApi.triggerSyncPull(token, sync.id)
      addJob({
        runId: result.run_id,
        jobType: 'forecast_sync',
        displayName: sync.name,
        resourceId: sync.id,
        resourceType: 'forecast_sync',
      })
      // Refresh to show syncing status
      await loadSyncs()
    } catch (err: any) {
      alert(err.message || 'Failed to trigger sync')
    } finally {
      setTriggeringSync(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-emerald-500" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            href="/forecasts"
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <ChevronLeft className="w-5 h-5 text-gray-500" />
          </Link>
          <div>
            <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">
              Forecast Syncs
            </h1>
            <p className="text-gray-500 dark:text-gray-400">
              Manage your acquisition forecast data connections
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button onClick={() => loadSyncs()} variant="outline" size="sm">
            <RefreshCw className="w-4 h-4 mr-2" />
            Refresh
          </Button>
          <Link href="/forecasts/syncs/new">
            <Button variant="primary" size="sm">
              <Plus className="w-4 h-4 mr-2" />
              New Sync
            </Button>
          </Link>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 rounded-lg flex items-center gap-2 text-red-600 dark:text-red-400">
          <AlertTriangle className="w-5 h-5" />
          <span>{error}</span>
        </div>
      )}

      <JobProgressPanelByType jobType="forecast_sync" variant="compact" className="space-y-2" />

      {/* Sync List */}
      {syncs.length === 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-12 text-center">
          <TrendingUp className="w-12 h-12 mx-auto text-gray-300 dark:text-gray-600 mb-4" />
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
            No syncs configured
          </h3>
          <p className="text-gray-500 dark:text-gray-400 mb-6">
            Create a sync to start pulling acquisition forecasts
          </p>
          <Link href="/forecasts/syncs/new">
            <Button variant="primary">
              <Plus className="w-4 h-4 mr-2" />
              Create First Sync
            </Button>
          </Link>
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50 dark:bg-gray-700/50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Sync
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Source
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Frequency
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Forecasts
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {syncs.map((sync) => {
                const config = sourceTypeConfig[sync.source_type]
                // Include WebSocket-tracked jobs for immediate UI feedback
                const hasActiveJob = getJobsForResource('forecast_sync', sync.id).length > 0
                const isSyncing = sync.is_syncing || triggeringSync === sync.id || hasActiveJob

                return (
                  <tr key={sync.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/30">
                    <td className="px-6 py-4">
                      <Link
                        href={`/forecasts/syncs/${sync.id}`}
                        className="font-medium text-gray-900 dark:text-white hover:text-emerald-600 dark:hover:text-emerald-400"
                      >
                        {sync.name}
                      </Link>
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        {sync.slug}
                      </p>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex px-2 py-1 text-xs font-medium rounded ${config?.color || 'bg-gray-100 text-gray-800'}`}>
                        {config?.label || sync.source_type.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-1 text-sm text-gray-600 dark:text-gray-400">
                        <Calendar className="w-4 h-4" />
                        {frequencyLabels[sync.sync_frequency] || sync.sync_frequency}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-sm font-medium text-gray-900 dark:text-white">
                        {sync.forecast_count.toLocaleString()}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      {isSyncing ? (
                        <span className="flex items-center gap-1 text-sm text-amber-600 dark:text-amber-400">
                          <Loader2 className="w-4 h-4 animate-spin" />
                          Syncing...
                        </span>
                      ) : !sync.is_active ? (
                        <span className="flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400">
                          <Pause className="w-4 h-4" />
                          Paused
                        </span>
                      ) : sync.last_sync_status === 'success' ? (
                        <span className="flex items-center gap-1 text-sm text-emerald-600 dark:text-emerald-400">
                          <CheckCircle2 className="w-4 h-4" />
                          {sync.last_sync_at
                            ? new Date(sync.last_sync_at).toLocaleString()
                            : 'Ready'}
                        </span>
                      ) : sync.last_sync_status === 'failed' ? (
                        <span className="flex items-center gap-1 text-sm text-red-600 dark:text-red-400">
                          <AlertTriangle className="w-4 h-4" />
                          Failed
                        </span>
                      ) : (
                        <span className="text-sm text-gray-500 dark:text-gray-400">
                          Not synced
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleTriggerSync(sync)}
                          disabled={isSyncing || !sync.is_active}
                        >
                          {isSyncing ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <Play className="w-4 h-4" />
                          )}
                        </Button>
                        <Link href={`/forecasts/syncs/${sync.id}`}>
                          <Button variant="outline" size="sm">
                            <Settings className="w-4 h-4" />
                          </Button>
                        </Link>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function ForecastSyncsPage() {
  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <SyncListContent />
        </div>
      </div>
    </ProtectedRoute>
  )
}

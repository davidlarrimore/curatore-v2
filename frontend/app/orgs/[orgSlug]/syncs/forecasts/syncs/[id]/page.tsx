'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter, useParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { useOrgUrl } from '@/lib/org-url-context'
import { forecastsApi, ForecastSync, Forecast } from '@/lib/api'
import { useActiveJobs } from '@/lib/context-shims'
import { useJobProgress } from '@/lib/useJobProgress'
import { JobProgressPanel } from '@/components/ui/JobProgressPanel'
import { Button } from '@/components/ui/Button'
import {
  TrendingUp,
  ChevronLeft,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Play,
  Pause,
  Trash2,
  Calendar,
  Building2,
  Clock,
  ExternalLink,
  FileText,
  Filter,
  Pencil,
  Eraser,
} from 'lucide-react'

// AG Agency ID to name mapping
const AG_AGENCIES: Record<number, string> = {
  2: 'General Services Administration',
  4: 'Department of the Interior',
  5: 'Department of Commerce',
  6: 'Department of Veterans Affairs',
  7: 'Department of the Treasury',
  8: 'Social Security Administration',
  12: 'Small Business Administration',
  13: 'Department of Transportation',
  22: 'Office of Personnel Management',
  24: 'Department of Labor',
  38: 'Environmental Protection Agency',
  39: 'Department of Homeland Security',
  63: 'Department of Health and Human Services',
}

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

function SyncDetailContent() {
  const { token } = useAuth()
  const { orgSlug } = useOrgUrl()
  const router = useRouter()
  const params = useParams()
  const syncId = params.id as string
  const { addJob } = useActiveJobs()

  // Helper for org-scoped URLs
  const orgUrl = (path: string) => `/orgs/${orgSlug}${path}`

  const [sync, setSync] = useState<ForecastSync | null>(null)
  const [forecasts, setForecasts] = useState<Forecast[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [triggeringSync, setTriggeringSync] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [showClearConfirm, setShowClearConfirm] = useState(false)

  const loadData = useCallback(async (silent = false) => {
    if (!token || !syncId) return
    if (!silent) {
      setLoading(true)
      setError(null)
    }

    try {
      const [syncData, forecastsData] = await Promise.all([
        forecastsApi.getSync(token, syncId),
        forecastsApi.listForecasts(token, { sync_id: syncId, limit: 50 }),
      ])
      setSync(syncData)
      setForecasts(forecastsData.items)
    } catch (err: unknown) {
      if (!silent) {
        const message = err instanceof Error ? err.message : 'Failed to load sync'
        setError(message)
      }
    } finally {
      if (!silent) {
        setLoading(false)
      }
    }
  }, [token, syncId])

  // Track jobs for this sync and auto-refresh on completion
  const { isActive: isSyncJobActive } = useJobProgress('forecast_sync', syncId, {
    onComplete: () => loadData(true),
  })

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleTriggerSync = async () => {
    if (!token || !sync || triggeringSync) return

    setTriggeringSync(true)
    try {
      const result = await forecastsApi.triggerSyncPull(token, sync.id)
      addJob({
        runId: result.run_id,
        jobType: 'forecast_sync',
        displayName: sync.name,
        resourceId: sync.id,
        resourceType: 'forecast_sync',
      })
      await loadData()
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to trigger sync'
      alert(message)
    } finally {
      setTriggeringSync(false)
    }
  }

  const handleTogglePause = async () => {
    if (!token || !sync) return

    try {
      await forecastsApi.updateSync(token, sync.id, {
        is_active: !sync.is_active,
        status: sync.is_active ? 'paused' : 'active',
      })
      await loadData()
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to update sync'
      alert(message)
    }
  }

  const handleDelete = async () => {
    if (!token || !sync) return
    if (!confirm(`Are you sure you want to delete "${sync.name}"? This will also delete all associated forecasts.`)) {
      return
    }

    setDeleting(true)
    try {
      await forecastsApi.deleteSync(token, sync.id)
      router.push(orgUrl('/syncs/forecasts/syncs'))
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to delete sync'
      alert(message)
      setDeleting(false)
    }
  }

  const handleClearForecasts = async () => {
    if (!token || !sync) return

    setClearing(true)
    setShowClearConfirm(false)
    try {
      const result = await forecastsApi.clearSyncForecasts(token, sync.id)
      alert(`Cleared ${result.deleted_count} forecasts`)
      await loadData()
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to clear forecasts'
      alert(message)
    } finally {
      setClearing(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-emerald-500" />
      </div>
    )
  }

  if (error || !sync) {
    return (
      <div className="p-6 bg-red-50 dark:bg-red-900/20 rounded-lg">
        <div className="flex items-center gap-2 text-red-600 dark:text-red-400">
          <AlertTriangle className="w-5 h-5" />
          <span>{error || 'Sync not found'}</span>
        </div>
        <Link href={orgUrl('/syncs/forecasts/syncs')}>
          <Button variant="outline" className="mt-4">
            Back to Syncs
          </Button>
        </Link>
      </div>
    )
  }

  const config = sourceTypeConfig[sync.source_type]
  // Include WebSocket-tracked jobs for immediate UI feedback
  const isSyncing = sync.is_syncing || triggeringSync || isSyncJobActive

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            href={orgUrl('/syncs/forecasts/syncs')}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <ChevronLeft className="w-5 h-5 text-gray-500" />
          </Link>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">
                {sync.name}
              </h1>
              <span className={`px-2 py-1 text-xs font-medium rounded ${config?.color || 'bg-gray-100 text-gray-800'}`}>
                {config?.label || sync.source_type.toUpperCase()}
              </span>
              {!sync.is_active && (
                <span className="px-2 py-1 text-xs font-medium rounded bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400">
                  Paused
                </span>
              )}
            </div>
            <p className="text-gray-500 dark:text-gray-400">
              {sync.forecast_count.toLocaleString()} forecasts
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Link href={orgUrl(`/syncs/forecasts/syncs/${sync.id}/edit`)}>
            <Button variant="outline" size="sm">
              <Pencil className="w-4 h-4 mr-2" />
              Edit
            </Button>
          </Link>
          <Button
            variant="outline"
            size="sm"
            onClick={handleTogglePause}
          >
            {sync.is_active ? (
              <>
                <Pause className="w-4 h-4 mr-2" />
                Pause
              </>
            ) : (
              <>
                <Play className="w-4 h-4 mr-2" />
                Resume
              </>
            )}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleTriggerSync}
            disabled={isSyncing || !sync.is_active}
          >
            {isSyncing ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Syncing...
              </>
            ) : (
              <>
                <RefreshCw className="w-4 h-4 mr-2" />
                Sync Now
              </>
            )}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowClearConfirm(true)}
            disabled={clearing || sync.forecast_count === 0}
            className="text-amber-600 hover:text-amber-700 hover:border-amber-300"
          >
            {clearing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <>
                <Eraser className="w-4 h-4 mr-2" />
                Clear
              </>
            )}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleDelete}
            disabled={deleting}
            className="text-red-600 hover:text-red-700 hover:border-red-300"
          >
            {deleting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Trash2 className="w-4 h-4" />
            )}
          </Button>
        </div>
      </div>

      {/* Job Progress */}
      <JobProgressPanel
        resourceType="forecast_sync"
        resourceId={syncId}
        variant="default"
      />

      {/* Clear Confirmation Dialog */}
      {showClearConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 max-w-md w-full mx-4 shadow-xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 rounded-full bg-amber-100 dark:bg-amber-900/30">
                <AlertTriangle className="w-6 h-6 text-amber-600 dark:text-amber-400" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Clear All Forecasts?
              </h3>
            </div>
            <p className="text-gray-600 dark:text-gray-400 mb-6">
              This will permanently delete all <strong>{sync.forecast_count.toLocaleString()}</strong> forecasts
              from this sync. The sync configuration will remain intact and you can re-sync to pull fresh data.
            </p>
            <div className="flex gap-3 justify-end">
              <Button variant="outline" onClick={() => setShowClearConfirm(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleClearForecasts}
                className="bg-amber-600 hover:bg-amber-700"
              >
                Clear All Forecasts
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Status Card */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Sync Status
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          <div>
            <p className="text-sm text-gray-500 dark:text-gray-400">Status</p>
            {isSyncing ? (
              <p className="flex items-center gap-2 text-amber-600 dark:text-amber-400 font-medium">
                <Loader2 className="w-4 h-4 animate-spin" />
                Syncing...
              </p>
            ) : sync.last_sync_status === 'success' ? (
              <p className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400 font-medium">
                <CheckCircle2 className="w-4 h-4" />
                Healthy
              </p>
            ) : sync.last_sync_status === 'failed' ? (
              <p className="flex items-center gap-2 text-red-600 dark:text-red-400 font-medium">
                <AlertTriangle className="w-4 h-4" />
                Failed
              </p>
            ) : (
              <p className="text-gray-600 dark:text-gray-400 font-medium">
                Not synced yet
              </p>
            )}
          </div>
          <div>
            <p className="text-sm text-gray-500 dark:text-gray-400">Last Sync</p>
            <p className="text-gray-900 dark:text-white font-medium flex items-center gap-2">
              <Clock className="w-4 h-4 text-gray-400" />
              {sync.last_sync_at
                ? new Date(sync.last_sync_at).toLocaleString()
                : 'Never'}
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-500 dark:text-gray-400">Frequency</p>
            <p className="text-gray-900 dark:text-white font-medium flex items-center gap-2">
              <Calendar className="w-4 h-4 text-gray-400" />
              {sync.sync_frequency.charAt(0).toUpperCase() + sync.sync_frequency.slice(1)}
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-500 dark:text-gray-400">Forecasts</p>
            <p className="text-gray-900 dark:text-white font-medium flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-gray-400" />
              {sync.forecast_count.toLocaleString()}
            </p>
          </div>
        </div>
      </div>

      {/* Filters Card */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
          <Filter className="w-5 h-5 text-gray-400" />
          Filters
        </h2>
        {(() => {
          const filterConfig = sync.filter_config || {}
          const agencyIds = (filterConfig.agency_ids || []) as number[]
          const naicsCodes = (filterConfig.naics_codes || []) as string[]
          const hasFilters = agencyIds.length > 0 || naicsCodes.length > 0

          const sourceLabel = sync.source_type === 'ag' ? 'Acquisition Gateway'
            : sync.source_type === 'apfs' ? 'DHS APFS'
            : 'State Department'

          if (!hasFilters) {
            return (
              <p className="text-gray-500 dark:text-gray-400 text-sm">
                No filters configured. All forecasts from {sourceLabel} will be synced.
              </p>
            )
          }

          return (
            <div className="space-y-4">
              {/* Agency Filter (AG only) */}
              {sync.source_type === 'ag' && agencyIds.length > 0 && (
                <div>
                  <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Agency
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {agencyIds.map((id: number) => (
                      <span
                        key={id}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 rounded-lg text-sm"
                      >
                        <Building2 className="w-3.5 h-3.5" />
                        {AG_AGENCIES[id] || `Agency ID: ${id}`}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* NAICS Filter */}
              {naicsCodes.length > 0 && (
                <div>
                  <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    NAICS Codes (client-side filter)
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {naicsCodes.map((code: string) => (
                      <span
                        key={code}
                        className="inline-flex items-center px-3 py-1.5 bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400 rounded-lg text-sm font-mono"
                      >
                        {code}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        })()}
      </div>

      {/* Forecasts List */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Recent Forecasts
          </h2>
          <span className="text-sm text-gray-500 dark:text-gray-400">
            Showing {forecasts.length} of {sync.forecast_count}
          </span>
        </div>

        {forecasts.length === 0 ? (
          <div className="p-12 text-center">
            <FileText className="w-12 h-12 mx-auto text-gray-300 dark:text-gray-600 mb-4" />
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
              No forecasts yet
            </h3>
            <p className="text-gray-500 dark:text-gray-400 mb-6">
              Run a sync to pull forecasts from this source
            </p>
            <Button
              variant="primary"
              onClick={handleTriggerSync}
              disabled={isSyncing || !sync.is_active}
            >
              {isSyncing ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Syncing...
                </>
              ) : (
                <>
                  <RefreshCw className="w-4 h-4 mr-2" />
                  Sync Now
                </>
              )}
            </Button>
          </div>
        ) : (
          <div className="divide-y divide-gray-200 dark:divide-gray-700">
            {forecasts.map((forecast) => (
              <div
                key={forecast.id}
                onClick={() => router.push(orgUrl(`/syncs/forecasts/${forecast.id}`))}
                className="px-6 py-4 hover:bg-gray-50 dark:hover:bg-gray-700/30 cursor-pointer transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-gray-900 dark:text-white truncate">
                      {forecast.title}
                    </h3>
                    <div className="flex flex-wrap items-center gap-3 mt-2 text-sm text-gray-500 dark:text-gray-400">
                      {forecast.agency_name && (
                        <span className="flex items-center gap-1">
                          <Building2 className="w-3.5 h-3.5" />
                          {forecast.agency_name}
                        </span>
                      )}
                      {forecast.naics_codes && forecast.naics_codes.length > 0 && (
                        <span>
                          NAICS: {forecast.naics_codes[0].code}
                        </span>
                      )}
                      {forecast.fiscal_year && (
                        <span>FY{forecast.fiscal_year}</span>
                      )}
                      {forecast.estimated_award_quarter && (
                        <span>{forecast.estimated_award_quarter}</span>
                      )}
                    </div>
                  </div>
                  {forecast.source_url && (
                    <a
                      href={forecast.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="ml-4 p-2 text-gray-400 hover:text-emerald-500 transition-colors"
                    >
                      <ExternalLink className="w-4 h-4" />
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function ForecastSyncDetailPage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <SyncDetailContent />
      </div>
    </div>
  )
}

'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { useDeletionJobs, useActiveJobs } from '@/lib/context-shims'
import { sharepointSyncApi, SharePointSyncConfig } from '@/lib/api'
import { formatDateTime } from '@/lib/date-utils'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  FolderSync,
  RefreshCw,
  AlertTriangle,
  Plus,
  CheckCircle2,
  XCircle,
  Clock,
  Pause,
  Archive,
  Play,
  FileText,
  Folder,
  Calendar,
  ArrowRight,
  Loader2,
  X,
  Info,
  Trash2,
} from 'lucide-react'

// Toast notification type
interface Toast {
  id: string
  type: 'success' | 'error' | 'info' | 'warning'
  message: string
  configId?: string
}

export default function SharePointSyncPage() {
  return (
    <ProtectedRoute>
      <SharePointSyncContent />
    </ProtectedRoute>
  )
}

function SharePointSyncContent() {
  const router = useRouter()
  const { token } = useAuth()
  const { isDeleting } = useDeletionJobs()
  const { addJob } = useActiveJobs()

  const [configs, setConfigs] = useState<SharePointSyncConfig[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [syncingConfigs, setSyncingConfigs] = useState<Set<string>>(new Set())
  const [toasts, setToasts] = useState<Toast[]>([])

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const previousSyncingRef = useRef<Set<string>>(new Set())

  // Toast helper functions
  const addToast = useCallback((type: Toast['type'], message: string, configId?: string) => {
    const id = Date.now().toString()
    setToasts(prev => [...prev, { id, type, message, configId }])
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, 5000)
  }, [])

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  const loadConfigs = useCallback(async (showLoading = true) => {
    if (!token) return

    if (showLoading) setIsLoading(true)
    setError('')

    try {
      const response = await sharepointSyncApi.listConfigs(token, { limit: 100 })
      const newConfigs = response.configs

      // Track which configs are syncing
      const currentSyncing = new Set<string>()
      newConfigs.forEach(config => {
        if (config.is_syncing) {
          currentSyncing.add(config.id)
        }
      })

      // Check for completed syncs
      previousSyncingRef.current.forEach(configId => {
        if (!currentSyncing.has(configId)) {
          // This config finished syncing
          const config = newConfigs.find(c => c.id === configId)
          if (config) {
            if (config.last_sync_status === 'success') {
              addToast('success', `"${config.name}" sync completed`, configId)
            } else if (config.last_sync_status === 'failed') {
              addToast('error', `"${config.name}" sync failed`, configId)
            } else if (config.last_sync_status === 'partial') {
              addToast('warning', `"${config.name}" sync completed with errors`, configId)
            }
          }
        }
      })

      previousSyncingRef.current = currentSyncing
      setSyncingConfigs(currentSyncing)
      setConfigs(newConfigs)

      // Start or stop polling based on syncing status
      if (currentSyncing.size > 0) {
        startPolling()
      } else {
        stopPolling()
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load sync configurations')
    } finally {
      if (showLoading) setIsLoading(false)
    }
  }, [token, addToast])

  const startPolling = useCallback(() => {
    if (pollIntervalRef.current) return // Already polling

    pollIntervalRef.current = setInterval(() => {
      loadConfigs(false)
    }, 5000)
  }, [loadConfigs])

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
  }, [])

  // Cleanup on unmount
  useEffect(() => {
    return () => stopPolling()
  }, [stopPolling])

  useEffect(() => {
    if (token) {
      loadConfigs()
    }
  }, [token, loadConfigs])

  const handleSync = async (configId: string, configName: string) => {
    if (!token) return

    // Optimistically add to syncing set
    setSyncingConfigs(prev => new Set(prev).add(configId))
    previousSyncingRef.current.add(configId)
    addToast('info', `Starting sync for "${configName}"...`, configId)

    try {
      const result = await sharepointSyncApi.triggerSync(token, configId)

      // Track the job in the activity monitor
      if (result.run_id) {
        addJob({
          runId: result.run_id,
          jobType: 'sharepoint_sync',
          displayName: configName,
          resourceId: configId,
          resourceType: 'sharepoint_config',
        })
      }

      // Start polling for status updates
      startPolling()
      // Refresh to show syncing status
      await loadConfigs(false)
    } catch (err: any) {
      addToast('error', `Failed to start sync: ${err.message}`, configId)
      setSyncingConfigs(prev => {
        const next = new Set(prev)
        next.delete(configId)
        return next
      })
      previousSyncingRef.current.delete(configId)
    }
  }

  // Use formatDateTime from date-utils for consistent EST display
  const formatDate = (dateStr: string | null) => formatDateTime(dateStr)

  const getStatusBadge = (config: SharePointSyncConfig) => {
    // Check if this config is being deleted (from context or DB status)
    if (config.status === 'deleting' || isDeleting(config.id)) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
          <Loader2 className="w-3 h-3 animate-spin" />
          Deleting...
        </span>
      )
    }

    if (config.is_syncing || syncingConfigs.has(config.id)) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
          <Loader2 className="w-3 h-3 animate-spin" />
          Syncing
        </span>
      )
    }

    if (config.status === 'archived') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">
          <Archive className="w-3 h-3" />
          Archived
        </span>
      )
    }

    if (config.status === 'paused' || !config.is_active) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
          <Pause className="w-3 h-3" />
          Paused
        </span>
      )
    }

    if (config.last_sync_status === 'failed') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
          <XCircle className="w-3 h-3" />
          Failed
        </span>
      )
    }

    if (config.last_sync_status === 'partial') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
          <AlertTriangle className="w-3 h-3" />
          Partial
        </span>
      )
    }

    if (config.last_sync_status === 'success') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
          <CheckCircle2 className="w-3 h-3" />
          Synced
        </span>
      )
    }

    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">
        <Clock className="w-3 h-3" />
        Pending
      </span>
    )
  }

  // Count syncing configs
  const activeSyncCount = configs.filter(c => c.is_syncing || syncingConfigs.has(c.id)).length

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      {/* Toast Notifications */}
      <div className="fixed top-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg max-w-sm animate-slide-in ${
              toast.type === 'success'
                ? 'bg-emerald-500 text-white'
                : toast.type === 'error'
                ? 'bg-red-500 text-white'
                : toast.type === 'warning'
                ? 'bg-amber-500 text-white'
                : 'bg-blue-500 text-white'
            }`}
          >
            {toast.type === 'success' && <CheckCircle2 className="w-5 h-5 flex-shrink-0" />}
            {toast.type === 'error' && <XCircle className="w-5 h-5 flex-shrink-0" />}
            {toast.type === 'warning' && <AlertTriangle className="w-5 h-5 flex-shrink-0" />}
            {toast.type === 'info' && <Info className="w-5 h-5 flex-shrink-0" />}
            <p className="text-sm font-medium flex-1">{toast.message}</p>
            <button
              onClick={() => removeToast(toast.id)}
              className="p-1 hover:bg-white/20 rounded transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25">
                <FolderSync className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  SharePoint Sync
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  Synchronize documents from SharePoint folders
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {activeSyncCount > 0 && (
                <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {activeSyncCount} syncing
                </span>
              )}
              <Button
                variant="secondary"
                onClick={() => loadConfigs()}
                disabled={isLoading}
                className="gap-2"
              >
                <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
              <Link href="/sharepoint-sync/new">
                <Button variant="primary" className="gap-2">
                  <Plus className="w-4 h-4" />
                  New Sync
                </Button>
              </Link>
            </div>
          </div>
        </div>

        {/* Error State */}
        {error && (
          <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
            <div className="flex items-center gap-3">
              <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
              <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
            </div>
          </div>
        )}

        {/* Loading State */}
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin" />
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading sync configurations...</p>
          </div>
        ) : configs.length === 0 ? (
          /* Empty State */
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-12 text-center">
            <div className="flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500/10 to-purple-500/10 mx-auto mb-4">
              <FolderSync className="w-8 h-8 text-indigo-600 dark:text-indigo-400" />
            </div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
              No sync configurations yet
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 max-w-md mx-auto mb-6">
              Connect to SharePoint and configure folder synchronization to automatically import and keep documents up to date.
            </p>
            <Link href="/sharepoint-sync/new">
              <Button variant="primary" className="gap-2">
                <Plus className="w-4 h-4" />
                Create Your First Sync
              </Button>
            </Link>
          </div>
        ) : (
          /* Sync Configs List */
          <div className="space-y-4">
            {configs.map((config) => (
              <div
                key={config.id}
                className={`bg-white dark:bg-gray-800 rounded-xl border overflow-hidden transition-colors ${
                  config.is_syncing || syncingConfigs.has(config.id)
                    ? 'border-blue-300 dark:border-blue-700 ring-2 ring-blue-100 dark:ring-blue-900/30'
                    : 'border-gray-200 dark:border-gray-700 hover:border-indigo-300 dark:hover:border-indigo-700'
                }`}
              >
                <div className="p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-4 min-w-0">
                      <div className={`flex items-center justify-center w-10 h-10 rounded-lg flex-shrink-0 ${
                        config.is_syncing || syncingConfigs.has(config.id)
                          ? 'bg-blue-100 dark:bg-blue-900/30'
                          : 'bg-gradient-to-br from-indigo-500/10 to-purple-500/10'
                      }`}>
                        {config.is_syncing || syncingConfigs.has(config.id) ? (
                          <Loader2 className="w-5 h-5 text-blue-600 dark:text-blue-400 animate-spin" />
                        ) : (
                          <Folder className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                        )}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-3">
                          <Link
                            href={`/sharepoint-sync/${config.id}`}
                            className="text-base font-semibold text-gray-900 dark:text-white hover:text-indigo-600 dark:hover:text-indigo-400 truncate"
                          >
                            {config.name}
                          </Link>
                          {getStatusBadge(config)}
                        </div>
                        {config.description && (
                          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 line-clamp-1">
                            {config.description}
                          </p>
                        )}
                        <p className="text-xs text-gray-400 dark:text-gray-500 mt-2 truncate">
                          {config.folder_url}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {config.status === 'active' && config.is_active && !isDeleting(config.id) && (
                        <div className="relative group">
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => handleSync(config.id, config.name)}
                            disabled={config.is_syncing || syncingConfigs.has(config.id) || !config.has_delta_token}
                            className="gap-1.5"
                          >
                            {config.is_syncing || syncingConfigs.has(config.id) ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <Play className="w-3.5 h-3.5" />
                            )}
                            {config.is_syncing || syncingConfigs.has(config.id) ? 'Syncing...' : 'Incremental Sync'}
                          </Button>
                          {/* Tooltip for disabled state - needs full sync first */}
                          {!config.has_delta_token && !config.is_syncing && !syncingConfigs.has(config.id) && (
                            <div className="absolute z-50 px-2 py-1.5 text-xs font-normal text-white bg-gray-900 dark:bg-gray-700 rounded-lg shadow-lg whitespace-nowrap left-1/2 -translate-x-1/2 bottom-full mb-2 pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity">
                              Run a full sync first
                              <div className="absolute left-1/2 -translate-x-1/2 top-full border-4 border-transparent border-t-gray-900 dark:border-t-gray-700" />
                            </div>
                          )}
                        </div>
                      )}
                      {config.status !== 'deleting' && !isDeleting(config.id) && (
                        <Link href={`/sharepoint-sync/${config.id}`}>
                          <Button variant="ghost" size="sm" className="gap-1.5">
                            View
                            <ArrowRight className="w-3.5 h-3.5" />
                          </Button>
                        </Link>
                      )}
                    </div>
                  </div>

                  {/* Stats Row */}
                  <div className="mt-4 flex items-center gap-6 text-sm">
                    <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
                      <FileText className="w-4 h-4" />
                      <span>{config.stats?.synced_files || 0} files</span>
                    </div>
                    {(config.stats?.deleted_count || 0) > 0 && (
                      <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
                        <AlertTriangle className="w-4 h-4" />
                        <span>{config.stats.deleted_count} deleted</span>
                      </div>
                    )}
                    <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
                      <Calendar className="w-4 h-4" />
                      <span>
                        {config.last_sync_at
                          ? `Last sync: ${formatDate(config.last_sync_at)}`
                          : 'Never synced'}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
                      <Clock className="w-4 h-4" />
                      <span className="capitalize">{config.sync_frequency}</span>
                    </div>
                  </div>

                  {/* Show last sync errors summary */}
                  {config.last_sync_status === 'partial' && config.stats?.last_sync_results?.failed_files > 0 && (
                    <div className="mt-3 p-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 text-xs text-amber-700 dark:text-amber-400">
                      Last sync had {config.stats.last_sync_results.failed_files} failed file{config.stats.last_sync_results.failed_files > 1 ? 's' : ''}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* CSS for toast animation */}
      <style jsx>{`
        @keyframes slide-in {
          from {
            transform: translateX(100%);
            opacity: 0;
          }
          to {
            transform: translateX(0);
            opacity: 1;
          }
        }
        .animate-slide-in {
          animation: slide-in 0.3s ease-out;
        }
      `}</style>
    </div>
  )
}

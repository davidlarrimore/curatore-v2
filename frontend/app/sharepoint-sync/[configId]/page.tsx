'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter, useParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { sharepointSyncApi, SharePointSyncConfig, SharePointSyncedDocument } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  FolderSync,
  ArrowLeft,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  Pause,
  Archive,
  Play,
  FileText,
  Folder,
  Calendar,
  Trash2,
  ExternalLink,
  Loader2,
  History,
  Settings,
  Edit3,
  AlertCircle,
  X,
  Info,
  HardDrive,
  Power,
  ToggleLeft,
  ToggleRight,
} from 'lucide-react'

// Format bytes to human readable
function formatBytes(bytes: number, decimals = 1): string {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(decimals)) + ' ' + sizes[i]
}

// Toast notification type
interface Toast {
  id: string
  type: 'success' | 'error' | 'info' | 'warning'
  message: string
}

// Run status from history
interface SyncRun {
  id: string
  status: string
  config: Record<string, any>
  progress: Record<string, any> | null
  results_summary: Record<string, any> | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export default function SharePointSyncConfigPage() {
  return (
    <ProtectedRoute>
      <SharePointSyncConfigContent />
    </ProtectedRoute>
  )
}

function SharePointSyncConfigContent() {
  const router = useRouter()
  const params = useParams()
  const configId = params.configId as string
  const { token } = useAuth()

  const [config, setConfig] = useState<SharePointSyncConfig | null>(null)
  const [documents, setDocuments] = useState<SharePointSyncedDocument[]>([])
  const [documentsTotal, setDocumentsTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [isSyncing, setIsSyncing] = useState(false)
  const [activeTab, setActiveTab] = useState<'documents' | 'deleted' | 'history'>('documents')
  const [syncHistory, setSyncHistory] = useState<SyncRun[]>([])
  const [toasts, setToasts] = useState<Toast[]>([])
  const [currentRun, setCurrentRun] = useState<SyncRun | null>(null)

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)

  // Toast helper functions
  const addToast = useCallback((type: Toast['type'], message: string) => {
    const id = Date.now().toString()
    setToasts(prev => [...prev, { id, type, message }])
    // Auto-remove after 6 seconds
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, 6000)
  }, [])

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
      }
    }
  }, [])

  const loadConfig = useCallback(async () => {
    if (!token || !configId) return

    try {
      const configData = await sharepointSyncApi.getConfig(token, configId)
      setConfig(configData)

      // Check if currently syncing
      if (configData.is_syncing) {
        setIsSyncing(true)
        startPolling()
      } else {
        setIsSyncing(false)
        stopPolling()
      }

      return configData
    } catch (err: any) {
      setError(err.message || 'Failed to load sync configuration')
      return null
    }
  }, [token, configId])

  const loadDocuments = useCallback(async (syncStatus?: string) => {
    if (!token || !configId) return

    try {
      const response = await sharepointSyncApi.listDocuments(token, configId, {
        sync_status: syncStatus,
        limit: 100,
      })
      setDocuments(response.documents)
      setDocumentsTotal(response.total)
    } catch (err: any) {
      console.error('Failed to load documents:', err)
    }
  }, [token, configId])

  const loadHistory = useCallback(async () => {
    if (!token || !configId) return

    try {
      const response = await sharepointSyncApi.getHistory(token, configId, { limit: 20 })
      setSyncHistory(response.runs)

      // Find current running/pending run
      const activeRun = response.runs.find(r => r.status === 'running' || r.status === 'pending')
      if (activeRun) {
        setCurrentRun(activeRun)
        setIsSyncing(true)
        startPolling()
      } else {
        setCurrentRun(null)
      }

      return response.runs
    } catch (err: any) {
      console.error('Failed to load history:', err)
      return []
    }
  }, [token, configId])

  const startPolling = useCallback(() => {
    // Clear any existing polling
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
    }

    // Poll every 3 seconds
    pollIntervalRef.current = setInterval(async () => {
      if (!token || !configId) return

      try {
        // Fetch latest config and history
        const [configData, historyResponse] = await Promise.all([
          sharepointSyncApi.getConfig(token, configId),
          sharepointSyncApi.getHistory(token, configId, { limit: 5 }),
        ])

        setConfig(configData)

        // Find the most recent run
        const latestRun = historyResponse.runs[0]
        if (latestRun) {
          setCurrentRun(latestRun)

          // Check if completed or failed
          if (latestRun.status === 'completed' || latestRun.status === 'failed') {
            setIsSyncing(false)
            stopPolling()

            // Refresh all data
            await loadDocuments(activeTab === 'deleted' ? 'deleted_in_source' : 'synced')
            setSyncHistory(historyResponse.runs)

            // Show completion toast
            if (latestRun.status === 'completed') {
              const summary = latestRun.results_summary
              if (summary) {
                const newFiles = summary.new_files || 0
                const updated = summary.updated_files || 0
                const failed = summary.failed_files || 0

                if (failed > 0) {
                  addToast('warning', `Sync completed with errors: ${newFiles} new, ${updated} updated, ${failed} failed`)
                } else {
                  addToast('success', `Sync completed: ${newFiles} new, ${updated} updated files`)
                }
              } else {
                addToast('success', 'Sync completed successfully')
              }
            } else {
              addToast('error', `Sync failed: ${latestRun.error_message || 'Unknown error'}`)
            }
          }
        }

        // Also check config.is_syncing
        if (!configData.is_syncing) {
          setIsSyncing(false)
          stopPolling()
        }
      } catch (err) {
        console.error('Failed to poll status:', err)
      }
    }, 3000)
  }, [token, configId, activeTab, addToast, loadDocuments])

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
  }, [])

  // Initial load
  useEffect(() => {
    if (token && configId) {
      setIsLoading(true)
      Promise.all([
        loadConfig(),
        loadDocuments(),
        loadHistory(),
      ]).finally(() => setIsLoading(false))
    }
  }, [token, configId])

  // Load documents based on active tab
  useEffect(() => {
    if (activeTab === 'documents') {
      loadDocuments('synced')
    } else if (activeTab === 'deleted') {
      loadDocuments('deleted_in_source')
    }
  }, [activeTab, loadDocuments])

  // Check for active sync on config load
  useEffect(() => {
    if (config?.is_syncing) {
      setIsSyncing(true)
      startPolling()
    }
  }, [config?.is_syncing, startPolling])

  const handleSync = async (fullSync: boolean = false) => {
    if (!token || !configId || isSyncing) return

    setIsSyncing(true)
    addToast('info', fullSync ? 'Starting full sync...' : 'Starting sync...')

    try {
      const result = await sharepointSyncApi.triggerSync(token, configId, fullSync)

      // Start polling for status
      startPolling()

      // Refresh history to show new run
      await loadHistory()
    } catch (err: any) {
      addToast('error', `Failed to start sync: ${err.message}`)
      setIsSyncing(false)
    }
  }

  const handleCleanup = async (deleteAssets: boolean = false) => {
    if (!token || !configId) return

    if (!confirm(
      deleteAssets
        ? 'This will remove deleted document records AND soft-delete the associated assets. Continue?'
        : 'This will remove deleted document records. The assets will remain. Continue?'
    )) {
      return
    }

    try {
      const result = await sharepointSyncApi.cleanupDeleted(token, configId, deleteAssets)
      addToast('success', result.message)
      loadDocuments('deleted_in_source')
      loadConfig()
    } catch (err: any) {
      addToast('error', `Failed to cleanup: ${err.message}`)
    }
  }

  const handleToggleActive = async () => {
    if (!token || !configId || !config) return

    const newState = !config.is_active

    try {
      await sharepointSyncApi.updateConfig(token, configId, { is_active: newState })
      addToast('success', `Sync ${newState ? 'enabled' : 'disabled'}`)
      loadConfig()
    } catch (err: any) {
      addToast('error', `Failed to ${newState ? 'enable' : 'disable'} sync: ${err.message}`)
    }
  }

  const handleArchive = async () => {
    if (!token || !configId || !config) return

    if (config.is_active) {
      addToast('warning', 'Disable sync first before archiving')
      return
    }

    const docCount = config.stats?.synced_files || config.stats?.storage?.synced_count || 0

    if (!confirm(
      `Archive this sync configuration?\n\n` +
      `This will:\n` +
      `- Remove ${docCount} documents from the search index\n` +
      `- Stop all syncing\n` +
      `- Keep all assets intact\n\n` +
      `After archiving, you can permanently delete this configuration.`
    )) {
      return
    }

    try {
      const result = await sharepointSyncApi.archiveConfig(token, configId)
      addToast('success', `Archived: ${result.archive_stats.opensearch_removed} documents removed from search`)
      loadConfig()
    } catch (err: any) {
      addToast('error', `Failed to archive: ${err.message}`)
    }
  }

  const handleDelete = async () => {
    if (!token || !configId || !config) return

    // Must be archived to delete
    if (config.status !== 'archived') {
      addToast('warning', 'Archive the sync configuration first before deleting')
      return
    }

    const syncedCount = config.stats?.synced_files || config.stats?.storage?.synced_count || 0
    const storageBytes = config.stats?.storage?.total_bytes || 0
    const storageMB = (storageBytes / (1024 * 1024)).toFixed(1)

    const message = `This will PERMANENTLY DELETE this sync configuration and perform the following cleanup:

- Delete ${syncedCount} synced assets
- Remove ${storageMB} MB from storage
- Remove documents from search index
- Delete all sync history/runs

This action cannot be undone. Are you sure?`

    if (!confirm(message)) {
      return
    }

    try {
      await sharepointSyncApi.deleteConfig(token, configId)
      addToast('success', 'Sync configuration deleted successfully')
      router.push('/sharepoint-sync')
    } catch (err: any) {
      addToast('error', `Failed to delete: ${err.message}`)
    }
  }

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-'
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const getStatusBadge = () => {
    if (!config) return null

    if (config.is_syncing || isSyncing) {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
          <Loader2 className="w-4 h-4 animate-spin" />
          Syncing
        </span>
      )
    }

    if (config.status === 'archived') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">
          <Archive className="w-4 h-4" />
          Archived
        </span>
      )
    }

    if (config.status === 'paused' || !config.is_active) {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
          <Pause className="w-4 h-4" />
          Paused
        </span>
      )
    }

    if (config.last_sync_status === 'failed') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
          <XCircle className="w-4 h-4" />
          Last Sync Failed
        </span>
      )
    }

    if (config.last_sync_status === 'success') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
          <CheckCircle2 className="w-4 h-4" />
          Synced
        </span>
      )
    }

    if (config.last_sync_status === 'partial') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
          <AlertTriangle className="w-4 h-4" />
          Partial Sync
        </span>
      )
    }

    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">
        <Clock className="w-4 h-4" />
        Pending
      </span>
    )
  }

  // Get last sync errors from history
  const getLastSyncErrors = (): string[] => {
    const lastRun = syncHistory[0]
    if (!lastRun?.results_summary?.errors) return []
    return lastRun.results_summary.errors.slice(0, 5).map((e: any) =>
      `${e.file}: ${e.error}`
    )
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950 flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin mx-auto" />
          <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading...</p>
        </div>
      </div>
    )
  }

  if (error || !config) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-6 text-center">
            <AlertTriangle className="w-12 h-12 text-red-500 mx-auto mb-4" />
            <h2 className="text-lg font-semibold text-red-800 dark:text-red-200 mb-2">
              {error || 'Configuration not found'}
            </h2>
            <Link href="/sharepoint-sync">
              <Button variant="secondary" className="gap-2">
                <ArrowLeft className="w-4 h-4" />
                Back to Sync Configs
              </Button>
            </Link>
          </div>
        </div>
      </div>
    )
  }

  const lastErrors = getLastSyncErrors()

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
          <Link
            href="/sharepoint-sync"
            className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 mb-4"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Sync Configs
          </Link>

          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="flex items-start gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25 flex-shrink-0">
                <Folder className="w-6 h-6" />
              </div>
              <div>
                <div className="flex items-center gap-3 flex-wrap">
                  <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                    {config.name}
                  </h1>
                  {getStatusBadge()}
                </div>
                {config.description && (
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                    {config.description}
                  </p>
                )}
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-2 break-all">
                  {config.folder_url}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3 flex-shrink-0">
              {/* Sync Toggle - only when status is active */}
              {config.status === 'active' && (
                <button
                  onClick={handleToggleActive}
                  disabled={isSyncing}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-colors ${
                    config.is_active
                      ? 'bg-emerald-50 border-emerald-200 text-emerald-700 dark:bg-emerald-900/20 dark:border-emerald-800 dark:text-emerald-400'
                      : 'bg-gray-50 border-gray-200 text-gray-500 dark:bg-gray-800 dark:border-gray-700 dark:text-gray-400'
                  } ${isSyncing ? 'opacity-50 cursor-not-allowed' : 'hover:opacity-80'}`}
                  title={config.is_active ? 'Disable sync' : 'Enable sync'}
                >
                  {config.is_active ? (
                    <ToggleRight className="w-5 h-5" />
                  ) : (
                    <ToggleLeft className="w-5 h-5" />
                  )}
                  <span className="text-sm font-medium">
                    {config.is_active ? 'Enabled' : 'Disabled'}
                  </span>
                </button>
              )}

              {/* Sync Buttons - only when active and enabled */}
              {config.status === 'active' && config.is_active && (
                <>
                  <Button
                    variant="primary"
                    onClick={() => handleSync(false)}
                    disabled={isSyncing}
                    className="gap-2"
                  >
                    {isSyncing ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Play className="w-4 h-4" />
                    )}
                    {isSyncing ? 'Syncing...' : 'Sync Now'}
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => handleSync(true)}
                    disabled={isSyncing}
                    className="gap-2"
                  >
                    <RefreshCw className={`w-4 h-4 ${isSyncing ? 'animate-spin' : ''}`} />
                    Full Sync
                  </Button>
                </>
              )}

              {/* Archive Button - only when disabled but not yet archived */}
              {config.status === 'active' && !config.is_active && (
                <Button
                  variant="secondary"
                  onClick={handleArchive}
                  disabled={isSyncing}
                  className="gap-2"
                  title="Archive this sync configuration"
                >
                  <Archive className="w-4 h-4" />
                  Archive
                </Button>
              )}

              {/* Delete Button - only when archived */}
              {config.status === 'archived' && (
                <Button
                  variant="ghost"
                  onClick={handleDelete}
                  className="gap-2 text-red-600 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-900/20"
                  title="Permanently delete sync configuration and all assets"
                >
                  <Trash2 className="w-4 h-4" />
                  Delete
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* Archived Info Banner */}
        {config.status === 'archived' && (
          <div className="mb-6 rounded-xl bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center">
                  <Archive className="w-5 h-5 text-gray-500 dark:text-gray-400" />
                </div>
              </div>
              <div className="flex-1">
                <p className="text-sm font-medium text-gray-800 dark:text-gray-200">
                  This sync configuration is archived
                </p>
                <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                  Syncing is stopped and documents have been removed from the search index.
                  Assets ({config.stats?.synced_files || config.stats?.storage?.synced_count || 0} files) are still accessible but won't appear in search results.
                </p>
                <p className="text-xs text-gray-600 dark:text-gray-400 mt-2">
                  To permanently delete all assets and free up storage, click the <strong>Delete</strong> button above.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Disabled Info Banner */}
        {config.status === 'active' && !config.is_active && (
          <div className="mb-6 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 p-4">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 rounded-full bg-amber-100 dark:bg-amber-800 flex items-center justify-center">
                  <Pause className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                </div>
              </div>
              <div className="flex-1">
                <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
                  Sync is disabled
                </p>
                <p className="text-xs text-amber-700 dark:text-amber-400 mt-1">
                  No new files will be synced from SharePoint. Enable sync to resume, or archive if you want to delete this configuration.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Sync Progress Banner */}
        {isSyncing && currentRun && (
          <div className="mb-6 rounded-xl bg-blue-50 dark:bg-blue-900/20 border border-blue-100 dark:border-blue-800 p-4">
            <div className="flex items-center gap-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 rounded-full bg-blue-100 dark:bg-blue-800 flex items-center justify-center">
                  <Loader2 className="w-5 h-5 text-blue-600 dark:text-blue-400 animate-spin" />
                </div>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-blue-800 dark:text-blue-200">
                  {currentRun.config?.full_sync ? 'Full sync' : 'Incremental sync'} in progress...
                </p>
                <p className="text-xs text-blue-600 dark:text-blue-400 mt-0.5">
                  Started {formatDate(currentRun.started_at || currentRun.created_at)}
                </p>
                {currentRun.progress && (
                  <p className="text-xs text-blue-600 dark:text-blue-400 mt-1">
                    {currentRun.progress.message || 'Processing files...'}
                  </p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Error Banner for Last Sync */}
        {!isSyncing && lastErrors.length > 0 && (
          <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-800 p-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-red-800 dark:text-red-200">
                  Last sync completed with {lastErrors.length} error{lastErrors.length > 1 ? 's' : ''}
                </p>
                <ul className="mt-2 space-y-1">
                  {lastErrors.map((err, idx) => (
                    <li key={idx} className="text-xs text-red-600 dark:text-red-400 truncate">
                      {err}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        )}

        {/* Stats Cards - Show live progress during sync */}
        {isSyncing && config.stats?.phase === 'syncing' && config.stats?.total_files > 0 ? (
          <div className="mb-6">
            {/* Live Sync Progress */}
            <div className="bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-xl border border-indigo-200 dark:border-indigo-700 p-6">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-indigo-100 dark:bg-indigo-800 flex items-center justify-center">
                    <Loader2 className="w-5 h-5 text-indigo-600 dark:text-indigo-400 animate-spin" />
                  </div>
                  <div>
                    <p className="text-lg font-semibold text-gray-900 dark:text-white">
                      Syncing Files...
                    </p>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {config.stats?.processed_files || 0} of {config.stats?.total_files || 0} files processed
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-2xl font-bold text-indigo-600 dark:text-indigo-400">
                    {config.stats?.total_files > 0
                      ? Math.round(((config.stats?.processed_files || 0) / config.stats?.total_files) * 100)
                      : 0}%
                  </p>
                </div>
              </div>

              {/* Progress Bar */}
              <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-3 mb-4">
                <div
                  className="bg-gradient-to-r from-indigo-500 to-purple-500 h-3 rounded-full transition-all duration-500"
                  style={{
                    width: `${config.stats?.total_files > 0
                      ? ((config.stats?.processed_files || 0) / config.stats?.total_files) * 100
                      : 0}%`
                  }}
                />
              </div>

              {/* Current File */}
              {config.stats?.current_file && (
                <p className="text-sm text-gray-600 dark:text-gray-400 truncate mb-4">
                  Processing: <span className="font-medium">{config.stats.current_file}</span>
                </p>
              )}

              {/* Live Stats Grid */}
              <div className="grid grid-cols-4 gap-4">
                <div className="text-center p-3 bg-white/50 dark:bg-gray-800/50 rounded-lg">
                  <p className="text-xl font-bold text-emerald-600 dark:text-emerald-400">
                    {config.stats?.new_files || 0}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">New</p>
                </div>
                <div className="text-center p-3 bg-white/50 dark:bg-gray-800/50 rounded-lg">
                  <p className="text-xl font-bold text-blue-600 dark:text-blue-400">
                    {config.stats?.updated_files || 0}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Updated</p>
                </div>
                <div className="text-center p-3 bg-white/50 dark:bg-gray-800/50 rounded-lg">
                  <p className="text-xl font-bold text-gray-600 dark:text-gray-400">
                    {config.stats?.unchanged_files || 0}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Unchanged</p>
                </div>
                <div className="text-center p-3 bg-white/50 dark:bg-gray-800/50 rounded-lg">
                  <p className="text-xl font-bold text-red-600 dark:text-red-400">
                    {config.stats?.failed_files || 0}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Failed</p>
                </div>
              </div>
            </div>
          </div>
        ) : isSyncing && config.stats?.phase === 'detecting_deletions' ? (
          <div className="mb-6">
            {/* Detecting Deletions Phase */}
            <div className="bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/20 rounded-xl border border-amber-200 dark:border-amber-700 p-6">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-amber-100 dark:bg-amber-800 flex items-center justify-center">
                  <Loader2 className="w-5 h-5 text-amber-600 dark:text-amber-400 animate-spin" />
                </div>
                <div>
                  <p className="text-lg font-semibold text-gray-900 dark:text-white">
                    Detecting Deleted Files...
                  </p>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    Checking for files removed from SharePoint
                  </p>
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* Standard Stats Cards (not syncing) */
          <div className="space-y-4 mb-6">
            {/* Main Stats Row */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center">
                    <FileText className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                  </div>
                  <div>
                    <p className="text-2xl font-bold text-gray-900 dark:text-white">
                      {config.stats?.synced_files || config.stats?.storage?.synced_count || 0}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Synced Files</p>
                  </div>
                </div>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
                    <Trash2 className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                  </div>
                  <div>
                    <p className="text-2xl font-bold text-gray-900 dark:text-white">
                      {config.stats?.deleted_count || config.stats?.storage?.deleted_count || 0}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Deleted</p>
                  </div>
                </div>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-gray-100 dark:bg-gray-700 flex items-center justify-center">
                    <Clock className="w-5 h-5 text-gray-600 dark:text-gray-400" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-gray-900 dark:text-white capitalize">
                      {config.sync_frequency}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Frequency</p>
                  </div>
                </div>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-gray-100 dark:bg-gray-700 flex items-center justify-center">
                    <Calendar className="w-5 h-5 text-gray-600 dark:text-gray-400" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-gray-900 dark:text-white">
                      {config.last_sync_at ? formatDate(config.last_sync_at).split(',')[0] : 'Never'}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Last Sync</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Storage Impact Card */}
            {config.stats?.storage && (
              <div className="bg-gradient-to-r from-blue-50 to-cyan-50 dark:from-blue-900/20 dark:to-cyan-900/20 rounded-xl border border-blue-200 dark:border-blue-800 p-4">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-8 h-8 rounded-lg bg-blue-100 dark:bg-blue-800 flex items-center justify-center">
                    <HardDrive className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                  </div>
                  <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Storage Impact</h4>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  <div>
                    <p className="text-xl font-bold text-gray-900 dark:text-white">
                      {formatBytes(config.stats.storage.total_bytes || 0)}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Total Storage Used</p>
                  </div>
                  <div>
                    <p className="text-xl font-bold text-gray-900 dark:text-white">
                      {config.stats.storage.total_documents || 0}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Total Documents</p>
                  </div>
                  <div>
                    <p className="text-xl font-bold text-gray-900 dark:text-white">
                      {config.stats.storage.total_documents > 0
                        ? formatBytes((config.stats.storage.total_bytes || 0) / config.stats.storage.total_documents)
                        : '0 B'}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Avg File Size</p>
                  </div>
                  <div>
                    <p className="text-xl font-bold text-emerald-600 dark:text-emerald-400">
                      {config.stats.storage.synced_count || 0}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Active / Synced</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tabs */}
        <div className="border-b border-gray-200 dark:border-gray-700 mb-6">
          <div className="flex gap-6">
            <button
              onClick={() => setActiveTab('documents')}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'documents'
                  ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                  : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4" />
                Documents
                {documentsTotal > 0 && activeTab !== 'documents' && (
                  <span className="px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400">
                    {documentsTotal}
                  </span>
                )}
              </div>
            </button>
            <button
              onClick={() => setActiveTab('deleted')}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'deleted'
                  ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                  : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <Trash2 className="w-4 h-4" />
                Deleted
                {(config.stats?.deleted_count || 0) > 0 && (
                  <span className="px-2 py-0.5 text-xs rounded-full bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                    {config.stats?.deleted_count}
                  </span>
                )}
              </div>
            </button>
            <button
              onClick={() => { setActiveTab('history'); loadHistory(); }}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'history'
                  ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                  : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <History className="w-4 h-4" />
                History
              </div>
            </button>
          </div>
        </div>

        {/* Tab Content */}
        {activeTab === 'documents' && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            {documents.length === 0 ? (
              <div className="p-12 text-center">
                <FileText className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                  No synced documents yet
                </h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 max-w-md mx-auto mb-4">
                  Run a sync to import documents from SharePoint.
                </p>
                {config.status === 'active' && config.is_active && !isSyncing && (
                  <Button
                    variant="primary"
                    onClick={() => handleSync(false)}
                    className="gap-2"
                  >
                    <Play className="w-4 h-4" />
                    Start First Sync
                  </Button>
                )}
              </div>
            ) : (
              <div className="divide-y divide-gray-100 dark:divide-gray-700">
                {documents.map((doc) => (
                  <div key={doc.id} className="px-5 py-4 hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors">
                    <div className="flex items-center justify-between gap-4">
                      <div className="flex items-center gap-3 min-w-0">
                        <FileText className="w-5 h-5 text-gray-400 flex-shrink-0" />
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                            {doc.original_filename || 'Unknown'}
                          </p>
                          {doc.sharepoint_path && (
                            <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                              {doc.sharepoint_path}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-4 flex-shrink-0">
                        {doc.file_size && (
                          <span className="text-xs text-gray-500 dark:text-gray-400">
                            {(doc.file_size / 1024).toFixed(1)} KB
                          </span>
                        )}
                        <span className="text-xs text-gray-400 dark:text-gray-500">
                          {formatDate(doc.last_synced_at)}
                        </span>
                        {doc.sharepoint_web_url && (
                          <a
                            href={doc.sharepoint_web_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-indigo-600 hover:text-indigo-700 dark:text-indigo-400"
                          >
                            <ExternalLink className="w-4 h-4" />
                          </a>
                        )}
                        <Link href={`/assets/${doc.asset_id}`}>
                          <Button variant="ghost" size="sm">
                            View Asset
                          </Button>
                        </Link>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'deleted' && (
          <div>
            {documents.length > 0 && (
              <div className="mb-4 flex items-center justify-between">
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  {documents.length} files have been deleted in SharePoint
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleCleanup(false)}
                    className="gap-2"
                  >
                    <Trash2 className="w-4 h-4" />
                    Remove Records
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleCleanup(true)}
                    className="gap-2 text-red-600 hover:text-red-700"
                  >
                    <Trash2 className="w-4 h-4" />
                    Remove + Delete Assets
                  </Button>
                </div>
              </div>
            )}

            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              {documents.length === 0 ? (
                <div className="p-12 text-center">
                  <CheckCircle2 className="w-12 h-12 text-emerald-500 mx-auto mb-4" />
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                    No deleted files
                  </h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    All synced files are still present in SharePoint.
                  </p>
                </div>
              ) : (
                <div className="divide-y divide-gray-100 dark:divide-gray-700">
                  {documents.map((doc) => (
                    <div key={doc.id} className="px-5 py-4 bg-red-50/50 dark:bg-red-900/10">
                      <div className="flex items-center justify-between gap-4">
                        <div className="flex items-center gap-3 min-w-0">
                          <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" />
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                              {doc.original_filename || 'Unknown'}
                            </p>
                            {doc.sharepoint_path && (
                              <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                                {doc.sharepoint_path}
                              </p>
                            )}
                          </div>
                        </div>
                        <div className="text-xs text-red-600 dark:text-red-400">
                          Deleted {formatDate(doc.deleted_detected_at)}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'history' && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            {syncHistory.length === 0 ? (
              <div className="p-12 text-center">
                <History className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                  No sync history yet
                </h3>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Run a sync to see history here.
                </p>
              </div>
            ) : (
              <div className="divide-y divide-gray-100 dark:divide-gray-700">
                {syncHistory.map((run) => (
                  <div key={run.id} className="px-5 py-4">
                    <div className="flex items-center justify-between gap-4">
                      <div className="flex items-center gap-3">
                        {run.status === 'completed' ? (
                          <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                        ) : run.status === 'failed' ? (
                          <XCircle className="w-5 h-5 text-red-500" />
                        ) : run.status === 'running' || run.status === 'pending' ? (
                          <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
                        ) : (
                          <Clock className="w-5 h-5 text-gray-400" />
                        )}
                        <div>
                          <p className="text-sm font-medium text-gray-900 dark:text-white">
                            {run.config?.full_sync ? 'Full Sync' : 'Incremental Sync'}
                          </p>
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            {formatDate(run.created_at)}
                            {run.completed_at && ` • ${Math.round((new Date(run.completed_at).getTime() - new Date(run.started_at || run.created_at).getTime()) / 1000)}s`}
                          </p>
                        </div>
                      </div>
                      <div className="text-right">
                        {run.status === 'running' || run.status === 'pending' ? (
                          <span className="text-sm text-blue-600 dark:text-blue-400">
                            In progress...
                          </span>
                        ) : run.results_summary ? (
                          <div>
                            <p className="text-sm text-gray-600 dark:text-gray-300">
                              {run.results_summary.new_files || 0} new,{' '}
                              {run.results_summary.updated_files || 0} updated
                              {(run.results_summary.failed_files || 0) > 0 && (
                                <span className="text-red-600 dark:text-red-400">
                                  , {run.results_summary.failed_files} failed
                                </span>
                              )}
                            </p>
                            {run.results_summary.deleted_detected > 0 && (
                              <p className="text-xs text-amber-600 dark:text-amber-400">
                                {run.results_summary.deleted_detected} deleted detected
                              </p>
                            )}
                          </div>
                        ) : null}
                        {run.error_message && (
                          <p className="text-sm text-red-600 dark:text-red-400 truncate max-w-xs">
                            {run.error_message}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
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

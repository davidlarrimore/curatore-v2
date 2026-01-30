'use client'

import { HardDrive, Database, CheckCircle, XCircle, AlertCircle, Loader2, FileText, Archive, TrendingDown } from 'lucide-react'

interface StorageHealth {
  status: string
  enabled: boolean
  provider_connected: boolean | null
  buckets: string[] | null
  error: string | null
}

interface StorageStats {
  organization_id: string
  total_files: number
  total_size_bytes: number
  files_by_type: { uploaded: number; processed: number }
  deduplication: {
    unique_files: number
    total_references: number
    duplicate_references: number
    storage_used_bytes: number
    storage_saved_bytes: number
    savings_percentage: number
  }
}

interface StorageOverviewCardProps {
  storageHealth: StorageHealth | null
  storageStats: StorageStats | null
  assetCount: number | null
  isLoading: boolean
}

// Format bytes to human readable
function formatBytes(bytes: number, decimals = 1): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(decimals)) + ' ' + sizes[i]
}

export function StorageOverviewCard({ storageHealth, storageStats, assetCount, isLoading }: StorageOverviewCardProps) {
  const getStatusIcon = () => {
    if (!storageHealth) return <AlertCircle className="w-4 h-4 text-gray-400" />

    switch (storageHealth.status) {
      case 'healthy':
        return <CheckCircle className="w-4 h-4 text-emerald-500" />
      case 'unhealthy':
        return <XCircle className="w-4 h-4 text-red-500" />
      case 'not_enabled':
      case 'not_configured':
        return <AlertCircle className="w-4 h-4 text-amber-500" />
      default:
        return <AlertCircle className="w-4 h-4 text-gray-400" />
    }
  }

  const getStatusText = () => {
    if (!storageHealth) return 'Unknown'

    switch (storageHealth.status) {
      case 'healthy':
        return 'Healthy'
      case 'unhealthy':
        return 'Unhealthy'
      case 'not_enabled':
        return 'Not Enabled'
      case 'not_configured':
        return 'Not Configured'
      default:
        return storageHealth.status
    }
  }

  const getStatusColor = () => {
    if (!storageHealth) return 'bg-gray-50 dark:bg-gray-800 text-gray-600 dark:text-gray-400'

    switch (storageHealth.status) {
      case 'healthy':
        return 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400'
      case 'unhealthy':
        return 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400'
      default:
        return 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400'
    }
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden hover:shadow-lg hover:shadow-gray-200/50 dark:hover:shadow-gray-900/50 transition-all duration-200">
      {/* Status bar at top */}
      <div className={`h-1 bg-gradient-to-r ${
        storageHealth?.status === 'healthy' ? 'from-emerald-500 to-teal-500' :
        storageHealth?.status === 'unhealthy' ? 'from-red-500 to-rose-500' :
        'from-amber-500 to-orange-500'
      }`} />

      <div className="p-5">
        {/* Header */}
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center text-white shadow-lg shadow-blue-500/25">
            <HardDrive className="w-5 h-5" />
          </div>
          <div className="flex-1">
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">Storage Overview</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">Object storage (S3/MinIO)</p>
          </div>
          {/* Status Badge */}
          <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full ${getStatusColor()}`}>
            {getStatusIcon()}
            <span className="text-xs font-medium">{getStatusText()}</span>
          </div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 text-gray-400 animate-spin" />
          </div>
        ) : (
          <>
            {/* Storage Stats Grid */}
            {storageStats && (
              <div className="grid grid-cols-2 gap-3 mb-4">
                {/* Total Assets */}
                <div className="bg-gradient-to-br from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <FileText className="w-4 h-4 text-indigo-500 dark:text-indigo-400" />
                    <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Total Assets</span>
                  </div>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">
                    {assetCount !== null ? assetCount.toLocaleString() : '-'}
                  </p>
                </div>

                {/* Storage Used */}
                <div className="bg-gradient-to-br from-blue-50 to-cyan-50 dark:from-blue-900/20 dark:to-cyan-900/20 rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <Database className="w-4 h-4 text-blue-500 dark:text-blue-400" />
                    <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Storage Used</span>
                  </div>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">
                    {formatBytes(storageStats.total_size_bytes)}
                  </p>
                </div>

                {/* Total Files */}
                <div className="bg-gradient-to-br from-emerald-50 to-teal-50 dark:from-emerald-900/20 dark:to-teal-900/20 rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <Archive className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
                    <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Total Files</span>
                  </div>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">
                    {storageStats.total_files.toLocaleString()}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {storageStats.files_by_type.uploaded} raw, {storageStats.files_by_type.processed} processed
                  </p>
                </div>

                {/* Deduplication Savings */}
                <div className="bg-gradient-to-br from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/20 rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <TrendingDown className="w-4 h-4 text-amber-500 dark:text-amber-400" />
                    <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Space Saved</span>
                  </div>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">
                    {formatBytes(storageStats.deduplication.storage_saved_bytes)}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {storageStats.deduplication.savings_percentage.toFixed(1)}% dedup savings
                  </p>
                </div>
              </div>
            )}

            {/* Bucket List - Compact */}
            {storageHealth?.buckets && storageHealth.buckets.length > 0 && (
              <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
                <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                  Buckets ({storageHealth.buckets.length})
                </p>
                <div className="flex flex-wrap gap-2">
                  {storageHealth.buckets.map((bucket) => (
                    <div
                      key={bucket}
                      className="flex items-center gap-1.5 px-2 py-1 bg-gray-50 dark:bg-gray-900/50 rounded text-xs"
                    >
                      <Database className="w-3 h-3 text-gray-400" />
                      <span className="font-mono text-gray-600 dark:text-gray-400">
                        {bucket}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Error Message */}
            {storageHealth?.error && (
              <div className="mt-4 p-3 bg-red-50 dark:bg-red-900/20 rounded-lg">
                <p className="text-xs text-red-600 dark:text-red-400">
                  {storageHealth.error}
                </p>
              </div>
            )}

            {/* Not Configured Message */}
            {storageHealth?.status === 'not_configured' && (
              <div className="text-sm text-gray-500 dark:text-gray-400">
                Object storage is not configured. Check your environment settings.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

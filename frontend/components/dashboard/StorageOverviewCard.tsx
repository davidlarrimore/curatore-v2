'use client'

import { HardDrive, Database, CheckCircle, XCircle, AlertCircle, Loader2 } from 'lucide-react'

interface StorageHealth {
  status: string
  enabled: boolean
  provider_connected: boolean | null
  buckets: string[] | null
  error: string | null
}

interface StorageOverviewCardProps {
  storageHealth: StorageHealth | null
  isLoading: boolean
}

export function StorageOverviewCard({ storageHealth, isLoading }: StorageOverviewCardProps) {
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
          <div>
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">Storage Overview</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">Object storage (S3/MinIO)</p>
          </div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 text-gray-400 animate-spin" />
          </div>
        ) : (
          <>
            {/* Status Badge */}
            <div className="mb-4">
              <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full ${getStatusColor()}`}>
                {getStatusIcon()}
                <span className="text-sm font-medium">{getStatusText()}</span>
              </div>
            </div>

            {/* Bucket List */}
            {storageHealth?.buckets && storageHealth.buckets.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Buckets ({storageHealth.buckets.length})
                </p>
                <div className="space-y-1.5">
                  {storageHealth.buckets.map((bucket) => (
                    <div
                      key={bucket}
                      className="flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-900/50 rounded-lg"
                    >
                      <Database className="w-4 h-4 text-gray-400" />
                      <span className="text-sm font-mono text-gray-700 dark:text-gray-300 truncate">
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

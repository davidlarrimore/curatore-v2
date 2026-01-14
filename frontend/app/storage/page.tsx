'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@/lib/auth-context'
import { storageApi } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import { HardDrive, Database, FileArchive, Trash2, AlertCircle, CheckCircle } from 'lucide-react'

export default function StoragePage() {
  return (
    <ProtectedRoute requiredRole="org_admin">
      <StorageContent />
    </ProtectedRoute>
  )
}

// Helper functions
function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
}

function formatPercentage(percentage: number): string {
  return `${percentage.toFixed(1)}%`
}

function StorageContent() {
  const { token } = useAuth()
  const [stats, setStats] = useState<any>(null)
  const [retention, setRetention] = useState<any>(null)
  const [dedupe, setDedupe] = useState<any>(null)
  const [duplicates, setDuplicates] = useState<any>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [isCleaningUp, setIsCleaningUp] = useState(false)
  const [cleanupResult, setCleanupResult] = useState<any>(null)
  const [expandedDuplicate, setExpandedDuplicate] = useState<string | null>(null)
  const [duplicateDetails, setDuplicateDetails] = useState<Record<string, any>>({})

  useEffect(() => {
    if (token) {
      loadData()
    }
  }, [token])

  const loadData = async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const [statsData, retentionData, dedupeData, duplicatesData] = await Promise.all([
        storageApi.getStats(token),
        storageApi.getRetentionPolicy(token),
        storageApi.getDeduplicationStats(token),
        storageApi.listDuplicates(token),
      ])

      setStats(statsData)
      setRetention(retentionData)
      setDedupe(dedupeData)
      setDuplicates(duplicatesData)
    } catch (err: any) {
      setError(err.message || 'Failed to load storage data')
    } finally {
      setIsLoading(false)
    }
  }

  const handleCleanup = async (dryRun: boolean) => {
    if (!token) return

    if (!dryRun) {
      if (!confirm('Are you sure you want to delete expired files? This action cannot be undone.')) {
        return
      }
    }

    setIsCleaningUp(true)
    setCleanupResult(null)
    setError('')

    try {
      const result = await storageApi.triggerCleanup(token, dryRun)
      setCleanupResult(result)
      if (!dryRun) {
        // Reload data after actual cleanup
        await loadData()
      }
    } catch (err: any) {
      setError(err.message || 'Failed to trigger cleanup')
    } finally {
      setIsCleaningUp(false)
    }
  }

  const toggleDuplicateDetails = async (hash: string) => {
    if (expandedDuplicate === hash) {
      setExpandedDuplicate(null)
      return
    }

    if (!duplicateDetails[hash]) {
      try {
        const details = await storageApi.getDuplicateDetails(token!, hash)
        setDuplicateDetails(prev => ({ ...prev, [hash]: details }))
      } catch (err: any) {
        setError(err.message || 'Failed to load duplicate details')
        return
      }
    }

    setExpandedDuplicate(hash)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-gray-600 dark:text-gray-400">Loading storage data...</p>
      </div>
    )
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-7xl">
      {/* Header */}
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Storage Management</h1>
          <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
            Monitor storage usage, manage file retention, and view deduplication savings
          </p>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="mb-6 rounded-md bg-red-50 dark:bg-red-900/20 p-4 flex items-start">
          <AlertCircle className="h-5 w-5 text-red-600 dark:text-red-400 mr-3 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
        </div>
      )}

      {/* Storage Statistics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        {/* Total Storage Card */}
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Total Storage</h3>
            <HardDrive className="h-6 w-6 text-blue-600 dark:text-blue-400" />
          </div>
          <div className="text-center">
            <div className="text-3xl font-bold text-gray-900 dark:text-white">
              {stats ? formatBytes(stats.total_size_bytes) : '—'}
            </div>
            <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              {stats ? stats.total_files.toLocaleString() : '—'} files
            </div>
          </div>
          {stats && (
            <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
              <div className="flex justify-between text-sm">
                <span className="text-gray-600 dark:text-gray-400">Uploaded:</span>
                <span className="text-gray-900 dark:text-white font-medium">
                  {stats.files_by_type.uploaded.toLocaleString()}
                </span>
              </div>
              <div className="flex justify-between text-sm mt-1">
                <span className="text-gray-600 dark:text-gray-400">Processed:</span>
                <span className="text-gray-900 dark:text-white font-medium">
                  {stats.files_by_type.processed.toLocaleString()}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Deduplication Savings Card */}
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Deduplication</h3>
            <Database className="h-6 w-6 text-green-600 dark:text-green-400" />
          </div>
          <div className="text-center">
            <div className="text-3xl font-bold text-green-600 dark:text-green-400">
              {dedupe && dedupe.enabled ? formatPercentage(dedupe.savings_percentage) : 'Disabled'}
            </div>
            <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              {dedupe && dedupe.enabled ? 'Storage Saved' : 'Deduplication Off'}
            </div>
          </div>
          {dedupe && dedupe.enabled && (
            <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
              <div className="flex justify-between text-sm">
                <span className="text-gray-600 dark:text-gray-400">Unique Files:</span>
                <span className="text-gray-900 dark:text-white font-medium">
                  {dedupe.unique_files.toLocaleString()}
                </span>
              </div>
              <div className="flex justify-between text-sm mt-1">
                <span className="text-gray-600 dark:text-gray-400">Duplicates:</span>
                <span className="text-gray-900 dark:text-white font-medium">
                  {dedupe.duplicate_references.toLocaleString()}
                </span>
              </div>
              <div className="flex justify-between text-sm mt-1">
                <span className="text-gray-600 dark:text-gray-400">Saved:</span>
                <span className="text-green-600 dark:text-green-400 font-medium">
                  {formatBytes(dedupe.storage_saved_bytes)}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Retention Policy Card */}
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Retention Policy</h3>
            <FileArchive className="h-6 w-6 text-orange-600 dark:text-orange-400" />
          </div>
          <div className="text-center mb-4">
            <Badge variant={retention?.enabled ? 'success' : 'secondary'}>
              {retention?.enabled ? 'Enabled' : 'Disabled'}
            </Badge>
          </div>
          {retention && retention.enabled && (
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-gray-600 dark:text-gray-400">Uploaded:</span>
                <span className="text-gray-900 dark:text-white font-medium">
                  {retention.retention_periods.uploaded_days}d
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-600 dark:text-gray-400">Processed:</span>
                <span className="text-gray-900 dark:text-white font-medium">
                  {retention.retention_periods.processed_days}d
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-600 dark:text-gray-400">Batches:</span>
                <span className="text-gray-900 dark:text-white font-medium">
                  {retention.retention_periods.batch_days}d
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-600 dark:text-gray-400">Temp:</span>
                <span className="text-gray-900 dark:text-white font-medium">
                  {retention.retention_periods.temp_hours}h
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Cleanup Controls */}
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6 mb-8">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Cleanup Operations</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Remove expired files based on retention policy
            </p>
          </div>
          <Trash2 className="h-6 w-6 text-red-600 dark:text-red-400" />
        </div>

        <div className="flex gap-3 mb-4">
          <Button
            onClick={() => handleCleanup(true)}
            disabled={isCleaningUp}
            variant="secondary"
          >
            {isCleaningUp ? 'Processing...' : 'Dry Run (Preview)'}
          </Button>
          <Button
            onClick={() => handleCleanup(false)}
            disabled={isCleaningUp}
            variant="destructive"
          >
            {isCleaningUp ? 'Deleting...' : 'Cleanup Now'}
          </Button>
        </div>

        {/* Cleanup Results */}
        {cleanupResult && (
          <div className={`rounded-md p-4 ${
            cleanupResult.dry_run
              ? 'bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800'
              : 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800'
          }`}>
            <div className="flex items-start">
              <CheckCircle className={`h-5 w-5 mt-0.5 mr-3 flex-shrink-0 ${
                cleanupResult.dry_run
                  ? 'text-blue-600 dark:text-blue-400'
                  : 'text-green-600 dark:text-green-400'
              }`} />
              <div className="flex-1">
                <h4 className={`font-semibold text-sm ${
                  cleanupResult.dry_run
                    ? 'text-blue-900 dark:text-blue-100'
                    : 'text-green-900 dark:text-green-100'
                }`}>
                  {cleanupResult.dry_run ? 'Dry Run Complete' : 'Cleanup Complete'}
                </h4>
                <div className="mt-2 text-sm space-y-1">
                  <div className={cleanupResult.dry_run ? 'text-blue-800 dark:text-blue-200' : 'text-green-800 dark:text-green-200'}>
                    <span className="font-medium">Duration:</span> {cleanupResult.duration_seconds}s
                  </div>
                  <div className={cleanupResult.dry_run ? 'text-blue-800 dark:text-blue-200' : 'text-green-800 dark:text-green-200'}>
                    <span className="font-medium">Total Expired:</span> {cleanupResult.total_expired}
                  </div>
                  {cleanupResult.dry_run ? (
                    <div className="text-blue-800 dark:text-blue-200">
                      <span className="font-medium">Would Delete:</span> {cleanupResult.would_delete_count} files
                    </div>
                  ) : (
                    <div className="text-green-800 dark:text-green-200">
                      <span className="font-medium">Deleted:</span> {cleanupResult.deleted_count} files
                    </div>
                  )}
                  <div className={cleanupResult.dry_run ? 'text-blue-800 dark:text-blue-200' : 'text-green-800 dark:text-green-200'}>
                    <span className="font-medium">Skipped (Active):</span> {cleanupResult.skipped_count}
                  </div>
                  {cleanupResult.error_count > 0 && (
                    <div className="text-red-600 dark:text-red-400">
                      <span className="font-medium">Errors:</span> {cleanupResult.error_count}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Duplicate Files List */}
      {duplicates && duplicates.duplicates.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Duplicate Files</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              {duplicates.duplicate_groups} groups saving {formatBytes(duplicates.total_storage_saved)}
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
              <thead className="bg-gray-50 dark:bg-gray-900">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Hash
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    File Count
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Storage Saved
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                {duplicates.duplicates.map((dup: any) => (
                  <>
                    <tr key={dup.hash} className="hover:bg-gray-50 dark:hover:bg-gray-900">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <code className="text-xs text-gray-600 dark:text-gray-400 font-mono">
                          {dup.hash.substring(0, 12)}...
                        </code>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                        {dup.file_count}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-green-600 dark:text-green-400 font-medium">
                        {formatBytes(dup.storage_saved)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => toggleDuplicateDetails(dup.hash)}
                        >
                          {expandedDuplicate === dup.hash ? 'Hide Details' : 'View Details'}
                        </Button>
                      </td>
                    </tr>
                    {expandedDuplicate === dup.hash && duplicateDetails[dup.hash] && (
                      <tr>
                        <td colSpan={4} className="px-6 py-4 bg-gray-50 dark:bg-gray-900">
                          <div className="text-sm space-y-2">
                            <div>
                              <span className="font-medium text-gray-900 dark:text-white">Original Filename:</span>{' '}
                              <span className="text-gray-600 dark:text-gray-400">
                                {duplicateDetails[dup.hash].original_filename}
                              </span>
                            </div>
                            <div>
                              <span className="font-medium text-gray-900 dark:text-white">File Size:</span>{' '}
                              <span className="text-gray-600 dark:text-gray-400">
                                {formatBytes(duplicateDetails[dup.hash].file_size)}
                              </span>
                            </div>
                            <div>
                              <span className="font-medium text-gray-900 dark:text-white">References ({duplicateDetails[dup.hash].reference_count}):</span>
                              <div className="mt-2 space-y-1">
                                {duplicateDetails[dup.hash].references.map((ref: any, idx: number) => (
                                  <div key={idx} className="text-xs text-gray-600 dark:text-gray-400 pl-4">
                                    • Document: <code className="font-mono">{ref.document_id}</code>
                                    {' '}- Created: {new Date(ref.created_at).toLocaleString()}
                                  </div>
                                ))}
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty State for No Duplicates */}
      {duplicates && duplicates.duplicates.length === 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-600 p-12 text-center">
          <CheckCircle className="h-12 w-12 text-green-600 dark:text-green-400 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">No Duplicate Files</h3>
          <p className="text-gray-600 dark:text-gray-400">
            All files are unique. No storage is being wasted on duplicates.
          </p>
        </div>
      )}
    </div>
  )
}

'use client'

/**
 * Organization-scoped assets page.
 * Re-exports the assets page component with org context from URL.
 */

import { useState, useEffect, useCallback } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { useOrgUrl } from '@/lib/org-url-context'
import { assetsApi, type CollectionHealth } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { ExtractionStatus } from '@/components/ui/ExtractionStatus'
import {
  FileText,
  RefreshCw,
  Search,
  ChevronLeft,
  ChevronRight,
  Loader2,
  FolderOpen,
  FileCode,
  Upload,
} from 'lucide-react'
import UploadModal from '@/components/UploadModal'

interface Asset {
  id: string
  organization_id: string
  source_type: string
  source_metadata: Record<string, unknown>
  original_filename: string
  content_type: string | null
  file_size: number | null
  file_hash: string | null
  raw_bucket: string
  raw_object_key: string
  status: string
  current_version_number: number | null
  created_at: string
  updated_at: string
  created_by: string | null
}

export default function OrgAssetsPage() {
  const { orgSlug, organization } = useOrgUrl()
  const router = useRouter()
  const searchParams = useSearchParams()
  const { token } = useAuth()

  const [assets, setAssets] = useState<Asset[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>(searchParams.get('status') || 'all')
  const [sourceTypeFilter, setSourceTypeFilter] = useState<string>('all')
  const [page, setPage] = useState(1)
  const [limit] = useState(20)
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false)
  const [collectionHealth, setCollectionHealth] = useState<CollectionHealth | null>(null)

  // Helper to build org-scoped URLs
  const orgUrl = (path: string) => `/orgs/${orgSlug}${path}`

  const loadAssets = useCallback(async (silent = false) => {
    if (!token) return

    if (!silent) {
      setIsLoading(true)
    }
    setError('')

    try {
      const params: {
        skip: number
        limit: number
        search?: string
        status?: string
        source_type?: string
      } = {
        skip: (page - 1) * limit,
        limit,
      }

      if (searchTerm.trim()) {
        params.search = searchTerm.trim()
      }

      if (statusFilter !== 'all') {
        params.status = statusFilter
      }

      if (sourceTypeFilter !== 'all') {
        params.source_type = sourceTypeFilter
      }

      const response = await assetsApi.listAssets(token, params)
      setAssets(response.items || [])
      setTotal(response.total || 0)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load assets'
      setError(message)
    } finally {
      setIsLoading(false)
    }
  }, [token, page, limit, searchTerm, statusFilter, sourceTypeFilter])

  const loadCollectionHealth = useCallback(async () => {
    if (!token) return

    try {
      const health = await assetsApi.getCollectionHealth(token)
      setCollectionHealth(health)
    } catch (err) {
      console.error('Failed to load collection health:', err)
    }
  }, [token])

  useEffect(() => {
    loadAssets()
  }, [loadAssets])

  useEffect(() => {
    loadCollectionHealth()
  }, [loadCollectionHealth])

  const handleUploadComplete = () => {
    setIsUploadModalOpen(false)
    setSuccessMessage('Upload complete! Processing will begin shortly.')
    loadAssets()
    loadCollectionHealth()
    setTimeout(() => setSuccessMessage(''), 5000)
  }

  const getSourceTypeIcon = (sourceType: string) => {
    switch (sourceType) {
      case 'upload':
        return <Upload className="w-4 h-4 text-violet-500" />
      case 'sam_gov':
        return <FileText className="w-4 h-4 text-blue-500" />
      case 'sharepoint':
        return <FolderOpen className="w-4 h-4 text-teal-500" />
      default:
        return <FileCode className="w-4 h-4 text-gray-500" />
    }
  }

  const formatFileSize = (bytes: number | null) => {
    if (bytes === null) return '-'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const totalPages = Math.ceil(total / limit)

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-violet-500 to-purple-600 text-white shadow-lg shadow-violet-500/25">
                <FileText className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  Assets
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  {total} documents in {organization?.display_name || 'organization'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button
                onClick={() => loadAssets()}
                disabled={isLoading}
                variant="outline"
                size="sm"
              >
                <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
              <Button
                onClick={() => setIsUploadModalOpen(true)}
                variant="primary"
                size="sm"
              >
                <Upload className="w-4 h-4 mr-2" />
                Upload
              </Button>
            </div>
          </div>
        </div>

        {/* Collection Health Summary */}
        {collectionHealth && (
          <div className="mb-6 grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
              <div className="text-2xl font-bold text-gray-900 dark:text-white">
                {collectionHealth.total_assets}
              </div>
              <div className="text-sm text-gray-500 dark:text-gray-400">Total Assets</div>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
              <div className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
                {collectionHealth.status_breakdown.ready}
              </div>
              <div className="text-sm text-gray-500 dark:text-gray-400">Ready</div>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
              <div className="text-2xl font-bold text-amber-600 dark:text-amber-400">
                {collectionHealth.status_breakdown.pending}
              </div>
              <div className="text-sm text-gray-500 dark:text-gray-400">Pending</div>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
              <div className="text-2xl font-bold text-red-600 dark:text-red-400">
                {collectionHealth.status_breakdown.failed}
              </div>
              <div className="text-sm text-gray-500 dark:text-gray-400">Failed</div>
            </div>
          </div>
        )}

        {/* Filters */}
        <div className="mb-6 flex flex-col sm:flex-row gap-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search by filename..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && loadAssets()}
              className="w-full pl-10 pr-4 py-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div className="flex gap-3">
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value)
                setPage(1)
              }}
              className="px-3 py-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="all">All Status</option>
              <option value="ready">Ready</option>
              <option value="processing">Processing</option>
              <option value="pending">Pending</option>
              <option value="failed">Failed</option>
            </select>
            <select
              value={sourceTypeFilter}
              onChange={(e) => {
                setSourceTypeFilter(e.target.value)
                setPage(1)
              }}
              className="px-3 py-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="all">All Sources</option>
              <option value="upload">Upload</option>
              <option value="sam_gov">SAM.gov</option>
              <option value="sharepoint">SharePoint</option>
              <option value="scrape">Web Scrape</option>
            </select>
          </div>
        </div>

        {/* Success Message */}
        {successMessage && (
          <div className="mb-6 p-4 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-lg text-emerald-700 dark:text-emerald-400">
            {successMessage}
          </div>
        )}

        {/* Error Message */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-400">
            {error}
          </div>
        )}

        {/* Assets List */}
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-indigo-600" />
          </div>
        ) : assets.length === 0 ? (
          <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
            <FileText className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
              No assets found
            </h3>
            <p className="text-gray-500 dark:text-gray-400 mb-4">
              {searchTerm || statusFilter !== 'all' || sourceTypeFilter !== 'all'
                ? 'Try adjusting your filters'
                : 'Upload your first document to get started'}
            </p>
            {!searchTerm && statusFilter === 'all' && sourceTypeFilter === 'all' && (
              <Button onClick={() => setIsUploadModalOpen(true)} variant="primary">
                <Upload className="w-4 h-4 mr-2" />
                Upload Document
              </Button>
            )}
          </div>
        ) : (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50 dark:bg-gray-900/50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      File
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Source
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Size
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Created
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {assets.map((asset) => (
                    <tr
                      key={asset.id}
                      className="hover:bg-gray-50 dark:hover:bg-gray-900/50 cursor-pointer"
                      onClick={() => router.push(orgUrl(`/assets/${asset.id}`))}
                    >
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-3">
                          <FileText className="w-5 h-5 text-gray-400" />
                          <div>
                            <div className="text-sm font-medium text-gray-900 dark:text-white truncate max-w-xs">
                              {asset.original_filename}
                            </div>
                            <div className="text-xs text-gray-500 dark:text-gray-400">
                              {asset.content_type || 'Unknown type'}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-2">
                          {getSourceTypeIcon(asset.source_type)}
                          <span className="text-sm text-gray-600 dark:text-gray-300 capitalize">
                            {asset.source_type.replace('_', ' ')}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-4 text-sm text-gray-600 dark:text-gray-300">
                        {formatFileSize(asset.file_size)}
                      </td>
                      <td className="px-4 py-4">
                        <ExtractionStatus status={asset.status} />
                      </td>
                      <td className="px-4 py-4 text-sm text-gray-600 dark:text-gray-300">
                        {new Date(asset.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 dark:border-gray-700">
                <div className="text-sm text-gray-500 dark:text-gray-400">
                  Showing {(page - 1) * limit + 1} to {Math.min(page * limit, total)} of {total}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                    variant="outline"
                    size="sm"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </Button>
                  <span className="text-sm text-gray-600 dark:text-gray-300">
                    Page {page} of {totalPages}
                  </span>
                  <Button
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    variant="outline"
                    size="sm"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Upload Modal */}
      <UploadModal
        isOpen={isUploadModalOpen}
        onClose={() => setIsUploadModalOpen(false)}
        onSuccess={handleUploadComplete}
        token={token || undefined}
      />
    </div>
  )
}

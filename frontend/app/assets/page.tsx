'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { assetsApi } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import {
  FileText,
  RefreshCw,
  Search,
  Filter,
  ChevronLeft,
  ChevronRight,
  Loader2,
  CheckCircle,
  XCircle,
  Clock,
  FolderOpen,
  FileCode,
  AlertTriangle,
  Upload,
  FolderUp,
} from 'lucide-react'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import BulkUploadModal from '@/components/BulkUploadModal'

interface Asset {
  id: string
  organization_id: string
  source_type: string
  source_metadata: Record<string, any>
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

export default function AssetsPage() {
  return (
    <ProtectedRoute>
      <AssetsContent />
    </ProtectedRoute>
  )
}

function AssetsContent() {
  const router = useRouter()
  const { token } = useAuth()

  const [assets, setAssets] = useState<Asset[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [sourceTypeFilter, setSourceTypeFilter] = useState<string>('all')
  const [page, setPage] = useState(1)
  const [limit] = useState(20)
  const [isUploading, setIsUploading] = useState(false)
  const [isBulkUploadOpen, setIsBulkUploadOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadAssets = useCallback(async (silent = false) => {
    if (!token) return

    if (!silent) {
      setIsLoading(true)
    }
    setError('')

    try {
      const response = await assetsApi.listAssets(token, {
        status: statusFilter === 'all' ? undefined : statusFilter,
        source_type: sourceTypeFilter === 'all' ? undefined : sourceTypeFilter,
        limit,
        offset: (page - 1) * limit,
      })

      setAssets(response.items)
      setTotal(response.total)
    } catch (err: any) {
      if (!silent) {
        setError(err.message || 'Failed to load assets')
      }
    } finally {
      if (!silent) {
        setIsLoading(false)
      }
    }
  }, [token, statusFilter, sourceTypeFilter, page, limit])

  useEffect(() => {
    loadAssets()
  }, [loadAssets])

  // Auto-poll when there are pending assets
  useEffect(() => {
    const hasPendingAssets = assets.some(asset => asset.status === 'pending')

    if (hasPendingAssets) {
      const intervalId = setInterval(() => {
        loadAssets(true) // Silent polling - don't show loading spinner
      }, 3000) // Poll every 3 seconds

      return () => clearInterval(intervalId)
    }
  }, [assets, loadAssets])

  const handleRefresh = () => {
    loadAssets()
  }

  const handleUploadClick = () => {
    fileInputRef.current?.click()
  }

  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (!files || files.length === 0 || !token) return

    setIsUploading(true)
    setError('')
    setSuccessMessage('')
    let successCount = 0
    let failCount = 0

    try {
      for (const file of Array.from(files)) {
        try {
          // Upload file using the proxy upload endpoint
          const formData = new FormData()
          formData.append('file', file)

          const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/storage/upload/proxy`, {
            method: 'POST',
            headers: {
              Authorization: `Bearer ${token}`,
            },
            body: formData,
          })

          if (!response.ok) {
            throw new Error(`Upload failed: ${response.statusText}`)
          }

          successCount++
        } catch (err: any) {
          console.error(`Failed to upload ${file.name}:`, err)
          failCount++
        }
      }

      // Show result
      if (successCount > 0) {
        setSuccessMessage(`Successfully uploaded ${successCount} file(s)${failCount > 0 ? `. ${failCount} failed` : ''}`)
        // Reload assets to show new uploads
        await loadAssets()
        // Clear success message after 5 seconds
        setTimeout(() => setSuccessMessage(''), 5000)
      } else {
        setError('Failed to upload files')
      }
    } finally {
      setIsUploading(false)
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const handleViewAsset = (assetId: string) => {
    router.push(`/assets/${assetId}`)
  }

  const getStatusConfig = (status: string) => {
    switch (status) {
      case 'ready':
        return {
          label: 'Extraction Complete',
          shortLabel: 'Ready',
          description: 'Content extracted and ready to use',
          icon: <CheckCircle className="w-4 h-4" />,
          bgColor: 'bg-emerald-50 dark:bg-emerald-900/20',
          textColor: 'text-emerald-700 dark:text-emerald-400',
          borderColor: 'border-emerald-200 dark:border-emerald-800',
        }
      case 'pending':
        return {
          label: 'Extracting Content',
          shortLabel: 'Processing',
          description: 'Converting document to markdown',
          icon: <Loader2 className="w-4 h-4 animate-spin" />,
          bgColor: 'bg-blue-50 dark:bg-blue-900/20',
          textColor: 'text-blue-700 dark:text-blue-400',
          borderColor: 'border-blue-200 dark:border-blue-800',
        }
      case 'failed':
        return {
          label: 'Needs Attention',
          shortLabel: 'Failed',
          description: 'Extraction failed - click to view details',
          icon: <AlertTriangle className="w-4 h-4" />,
          bgColor: 'bg-amber-50 dark:bg-amber-900/20',
          textColor: 'text-amber-700 dark:text-amber-400',
          borderColor: 'border-amber-200 dark:border-amber-800',
        }
      default:
        return {
          label: status,
          shortLabel: status,
          description: 'Unknown status',
          icon: <AlertTriangle className="w-4 h-4" />,
          bgColor: 'bg-gray-50 dark:bg-gray-900/20',
          textColor: 'text-gray-700 dark:text-gray-400',
          borderColor: 'border-gray-200 dark:border-gray-700',
        }
    }
  }

  const formatBytes = (bytes: number | null) => {
    if (!bytes) return 'Unknown'
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(1024))
    return `${(bytes / Math.pow(1024, i)).toFixed(2)} ${sizes[i]}`
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const seconds = Math.floor(diff / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)
    const days = Math.floor(hours / 24)

    if (days > 0) return `${days}d ago`
    if (hours > 0) return `${hours}h ago`
    if (minutes > 0) return `${minutes}m ago`
    return 'Just now'
  }

  const filteredAssets = assets.filter(asset =>
    searchTerm ? asset.original_filename.toLowerCase().includes(searchTerm.toLowerCase()) : true
  )

  const totalPages = Math.ceil(total / limit)

  // Calculate stats
  const stats = {
    total: total,
    ready: assets.filter(a => a.status === 'ready').length,
    processing: assets.filter(a => a.status === 'pending').length,
    failed: assets.filter(a => a.status === 'failed').length,
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25">
                <FileText className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  Assets
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  View and manage all your documents
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button
                onClick={() => setIsBulkUploadOpen(true)}
                className="gap-2 shadow-lg shadow-purple-500/25"
              >
                <FolderUp className="w-4 h-4" />
                <span className="hidden sm:inline">Bulk Upload</span>
                <span className="sm:hidden">Bulk</span>
              </Button>
              <Button
                onClick={handleUploadClick}
                disabled={isUploading}
                className="gap-2 shadow-lg shadow-indigo-500/25"
              >
                <Upload className={`w-4 h-4 ${isUploading ? 'animate-pulse' : ''}`} />
                <span className="hidden sm:inline">{isUploading ? 'Uploading...' : 'Upload'}</span>
                <span className="sm:hidden">+</span>
              </Button>
              <Button
                variant="secondary"
                onClick={handleRefresh}
                disabled={isLoading}
                className="gap-2"
              >
                <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                <span className="hidden sm:inline">Refresh</span>
              </Button>
            </div>

            {/* Hidden file input */}
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.doc,.docx,.txt,.md,.ppt,.pptx,.xls,.xlsx,.png,.jpg,.jpeg"
              onChange={handleFileSelect}
              className="hidden"
            />
          </div>

          {/* Stats Bar */}
          {!isLoading && assets.length > 0 && (
            <div className="mt-6 flex flex-wrap items-center gap-4 text-sm">
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300">
                <span className="font-medium">{stats.total}</span>
                <span>total assets</span>
              </div>
              {stats.ready > 0 && (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400">
                  <CheckCircle className="w-3.5 h-3.5" />
                  <span className="font-medium">{stats.ready}</span>
                  <span>extracted</span>
                </div>
              )}
              {stats.processing > 0 && (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span className="font-medium">{stats.processing}</span>
                  <span>extracting</span>
                </div>
              )}
              {stats.failed > 0 && (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span className="font-medium">{stats.failed}</span>
                  <span>need attention</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Filters */}
        <div className="mb-6 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Search */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="Search by filename..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-10 pr-4 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
              />
            </div>

            {/* Status Filter */}
            <div>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="w-full px-4 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
              >
                <option value="all">All Statuses</option>
                <option value="ready">✓ Extraction Complete</option>
                <option value="pending">↻ Extracting Content</option>
                <option value="failed">⚠ Needs Attention</option>
              </select>
            </div>

            {/* Source Type Filter */}
            <div>
              <select
                value={sourceTypeFilter}
                onChange={(e) => setSourceTypeFilter(e.target.value)}
                className="w-full px-4 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
              >
                <option value="all">All Sources</option>
                <option value="upload">Upload</option>
                <option value="sharepoint">SharePoint</option>
                <option value="web_scrape">Web Scrape</option>
                <option value="sam_gov">SAM.gov</option>
              </select>
            </div>
          </div>
        </div>

        {/* Success Message */}
        {successMessage && (
          <div className="mb-6 rounded-xl bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-100 dark:border-emerald-900/50 p-4">
            <div className="flex items-center gap-3">
              <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
                <CheckCircle className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
              </div>
              <p className="text-sm font-medium text-emerald-800 dark:text-emerald-200">{successMessage}</p>
            </div>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
            <div className="flex items-center gap-3">
              <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
              </div>
              <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
            </div>
          </div>
        )}

        {/* Loading State */}
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin"></div>
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading assets...</p>
          </div>
        ) : filteredAssets.length === 0 ? (
          /* Empty State */
          <div className="relative overflow-hidden rounded-2xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/50 px-6 py-16 text-center">
            <div className="absolute inset-0 pointer-events-none">
              <div className="absolute -top-24 -right-24 w-64 h-64 rounded-full bg-gradient-to-br from-indigo-500/5 to-purple-500/5 blur-3xl"></div>
              <div className="absolute -bottom-24 -left-24 w-64 h-64 rounded-full bg-gradient-to-br from-blue-500/5 to-cyan-500/5 blur-3xl"></div>
            </div>

            <div className="relative">
              <div className="mx-auto w-20 h-20 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-xl shadow-indigo-500/25 mb-6">
                <FileText className="w-10 h-10 text-white" />
              </div>
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                {searchTerm || statusFilter !== 'all' || sourceTypeFilter !== 'all'
                  ? 'No assets found'
                  : 'No assets yet'}
              </h3>
              <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto mb-8">
                {searchTerm || statusFilter !== 'all' || sourceTypeFilter !== 'all'
                  ? 'Try adjusting your filters or search term.'
                  : 'Upload documents or connect data sources to get started.'}
              </p>
              {!searchTerm && statusFilter === 'all' && sourceTypeFilter === 'all' && (
                <Button
                  onClick={handleUploadClick}
                  size="lg"
                  className="gap-2 shadow-lg shadow-indigo-500/25"
                  disabled={isUploading}
                >
                  <Upload className="w-5 h-5" />
                  {isUploading ? 'Uploading...' : 'Upload your first document'}
                </Button>
              )}
            </div>
          </div>
        ) : (
          <>
            {/* Assets Table */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                  <thead className="bg-gray-50 dark:bg-gray-900/50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Document
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Extraction Status
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Content
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Source
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Size
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Created
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                    {filteredAssets.map((asset) => {
                      const statusConfig = getStatusConfig(asset.status)
                      return (
                        <tr
                          key={asset.id}
                          onClick={() => handleViewAsset(asset.id)}
                          className="hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer transition-colors group"
                        >
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-3">
                              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 border border-indigo-100 dark:border-indigo-800 flex items-center justify-center flex-shrink-0">
                                <FileText className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                              </div>
                              <div className="min-w-0 flex-1">
                                <div className="text-sm font-medium text-gray-900 dark:text-white truncate group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors">
                                  {asset.original_filename}
                                </div>
                                <div className="flex items-center gap-2 mt-0.5">
                                  <div className="text-xs text-gray-500 dark:text-gray-400 font-mono">
                                    {asset.id.substring(0, 8)}
                                  </div>
                                  {asset.current_version_number && (
                                    <>
                                      <span className="text-gray-300 dark:text-gray-600">•</span>
                                      <div className="text-xs text-gray-500 dark:text-gray-400">
                                        v{asset.current_version_number}
                                      </div>
                                    </>
                                  )}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex flex-col gap-1.5">
                              <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${statusConfig.bgColor} ${statusConfig.textColor} w-fit`}>
                                {statusConfig.icon}
                                <span>{statusConfig.shortLabel}</span>
                              </div>
                              <div className="text-xs text-gray-500 dark:text-gray-400">
                                {statusConfig.description}
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div className="flex flex-col gap-1.5">
                              {/* Raw file indicator */}
                              <div className="flex items-center gap-2">
                                <div className="w-1.5 h-1.5 rounded-full bg-gray-400 dark:bg-gray-500"></div>
                                <span className="text-xs text-gray-600 dark:text-gray-400">Raw file</span>
                              </div>
                              {/* Extracted content indicator */}
                              {asset.status === 'ready' ? (
                                <div className="flex items-center gap-2">
                                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-500"></div>
                                  <span className="text-xs text-emerald-700 dark:text-emerald-400 font-medium">Markdown</span>
                                </div>
                              ) : asset.status === 'pending' ? (
                                <div className="flex items-center gap-2">
                                  <div className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse"></div>
                                  <span className="text-xs text-blue-600 dark:text-blue-400">Extracting...</span>
                                </div>
                              ) : (
                                <div className="flex items-center gap-2">
                                  <div className="w-1.5 h-1.5 rounded-full bg-gray-300 dark:bg-gray-600"></div>
                                  <span className="text-xs text-gray-400 dark:text-gray-500">Not extracted</span>
                                </div>
                              )}
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div className="flex items-center gap-2">
                              <div className="text-sm text-gray-900 dark:text-white capitalize">
                                {asset.source_type.replace('_', ' ')}
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div className="text-sm text-gray-500 dark:text-gray-400">
                              {formatBytes(asset.file_size)}
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div className="text-sm text-gray-500 dark:text-gray-400">
                              {formatDate(asset.created_at)}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="mt-6 flex items-center justify-between">
                <div className="text-sm text-gray-500 dark:text-gray-400">
                  Showing {(page - 1) * limit + 1} to {Math.min(page * limit, total)} of {total} assets
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="gap-2"
                  >
                    <ChevronLeft className="w-4 h-4" />
                    Previous
                  </Button>
                  <div className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300">
                    Page {page} of {totalPages}
                  </div>
                  <Button
                    variant="secondary"
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    className="gap-2"
                  >
                    Next
                    <ChevronRight className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Bulk Upload Modal */}
      <BulkUploadModal
        isOpen={isBulkUploadOpen}
        onClose={() => setIsBulkUploadOpen(false)}
        onSuccess={loadAssets}
        token={token}
      />
    </div>
  )
}

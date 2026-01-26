'use client'

import React, { useState, useEffect } from 'react'
import { useAuth } from '@/lib/auth-context'
import { objectStorageApi, utils } from '@/lib/api'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import FilePreview from '@/components/storage/FilePreview'
import StorageFolderBrowser from '@/components/storage/StorageFolderBrowser'
import {
  Database,
  HardDrive,
  CheckCircle,
  XCircle,
  AlertCircle,
  Loader2,
  Download,
  Trash2,
  RefreshCw,
  FolderOpen,
  File,
  FileText,
  Upload,
  Edit3,
  X,
  Eye,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Search,
  List,
  Grid,
} from 'lucide-react'

export default function StoragePage() {
  return (
    <ProtectedRoute requiredRole="org_admin">
      <StorageContent />
    </ProtectedRoute>
  )
}

function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
}

function formatDate(dateString: string | null): string {
  if (!dateString) return 'N/A'
  const date = new Date(dateString)
  return date.toLocaleString()
}

interface Artifact {
  id: string
  document_id: string
  artifact_type: string
  bucket: string
  object_key: string
  original_filename: string
  content_type: string | null
  file_size: number | null
  status: string
  created_at: string
}

function StorageContent() {
  const { token } = useAuth()
  const [healthData, setHealthData] = useState<any>(null)
  const [selectedBucket, setSelectedBucket] = useState<string | null>(null)
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isLoadingArtifacts, setIsLoadingArtifacts] = useState(false)
  const [error, setError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const [downloadingId, setDownloadingId] = useState<string | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const [editingArtifactId, setEditingArtifactId] = useState<string | null>(null)
  const [newFilename, setNewFilename] = useState('')
  const [selectedArtifacts, setSelectedArtifacts] = useState<Set<string>>(new Set())
  const [isDeletingBulk, setIsDeletingBulk] = useState(false)
  const [previewArtifact, setPreviewArtifact] = useState<Artifact | null>(null)
  const [previewBlob, setPreviewBlob] = useState<Blob | null>(null)
  const [isLoadingPreview, setIsLoadingPreview] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [sortColumn, setSortColumn] = useState<'filename' | 'type' | 'size' | 'status' | 'created'>('created')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')
  const [searchQuery, setSearchQuery] = useState('')
  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const [uploadTargetBucket, setUploadTargetBucket] = useState<string | null>(null)
  const [uploadTargetPrefix, setUploadTargetPrefix] = useState<string>('')
  const [showUploadModal, setShowUploadModal] = useState(false)

  useEffect(() => {
    if (token) {
      loadHealthData()
    }
  }, [token])

  const loadHealthData = async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const health = await objectStorageApi.getHealth()
      setHealthData(health)
    } catch (err: any) {
      setError(err.message || 'Failed to load storage health')
    } finally {
      setIsLoading(false)
    }
  }

  const loadArtifactsForBucket = async (bucket: string) => {
    if (!token) return

    setIsLoadingArtifacts(true)
    setSelectedBucket(bucket)
    setError('')
    setSuccessMessage('')
    setArtifacts([])
    setSelectedArtifacts(new Set()) // Clear selection when switching buckets

    try {
      // Load all artifacts and filter by bucket
      const allArtifacts = await objectStorageApi.listArtifacts(undefined, 1000, 0, token)
      const bucketArtifacts = allArtifacts.filter(a => a.bucket === bucket)
      setArtifacts(bucketArtifacts)
    } catch (err: any) {
      console.error('Failed to load artifacts:', err)
      setError(err.message || 'Failed to load artifacts')
    } finally {
      setIsLoadingArtifacts(false)
    }
  }

  const handleDownloadArtifact = async (artifact: Artifact) => {
    if (!token) return

    setDownloadingId(artifact.id)
    setError('')
    setSuccessMessage('')
    try {
      // Use presigned URL for download
      const blob = await objectStorageApi.downloadFile(artifact.document_id, artifact.artifact_type as any)
      utils.downloadBlob(blob, artifact.original_filename)
      setSuccessMessage(`Downloaded ${artifact.original_filename}`)
    } catch (err: any) {
      console.error('Download failed:', err)
      setError(`Failed to download: ${err.message}`)
    } finally {
      setDownloadingId(null)
    }
  }

  const handleDeleteArtifact = async (artifact: Artifact) => {
    if (!token) return

    const confirmed = window.confirm(`Delete ${artifact.original_filename}? This cannot be undone.`)
    if (!confirmed) return

    setError('')
    setSuccessMessage('')
    try {
      await objectStorageApi.deleteArtifact(artifact.id, token)
      setSuccessMessage(`Deleted ${artifact.original_filename}`)
      // Reload artifacts for the current bucket
      if (selectedBucket) {
        await loadArtifactsForBucket(selectedBucket)
      }
    } catch (err: any) {
      console.error('Delete failed:', err)
      setError(`Failed to delete: ${err.message}`)
    }
  }

  const handleFileUpload = async (files: FileList | File[]) => {
    if (!token || !uploadTargetBucket) return

    setIsUploading(true)
    setError('')
    setSuccessMessage('')

    const fileArray = Array.from(files)
    let successCount = 0
    let failCount = 0

    try {
      // Upload files sequentially to avoid overwhelming the system
      for (const file of fileArray) {
        try {
          // Use folder upload API with target bucket and prefix
          await objectStorageApi.uploadToFolder(uploadTargetBucket, uploadTargetPrefix, file, token)
          successCount++
        } catch (err: any) {
          console.error(`Failed to upload ${file.name}:`, err)
          failCount++
        }
      }

      // Show results
      if (successCount > 0 && failCount === 0) {
        setSuccessMessage(`Successfully uploaded ${successCount} file(s) to ${uploadTargetBucket}/${uploadTargetPrefix || 'root'}`)
      } else if (successCount > 0 && failCount > 0) {
        setSuccessMessage(`Uploaded ${successCount} file(s), ${failCount} failed`)
      } else if (failCount > 0) {
        setError(`Failed to upload ${failCount} file(s)`)
      }

      // Reload artifacts
      if (selectedBucket) {
        await loadArtifactsForBucket(selectedBucket)
      }

      // Close modal
      setShowUploadModal(false)

      // Refresh folder view (trigger event or reload)
      window.location.reload()
    } finally {
      setIsUploading(false)
    }
  }

  const handleOpenUpload = (bucket: string, prefix: string) => {
    setUploadTargetBucket(bucket)
    setUploadTargetPrefix(prefix)
    setShowUploadModal(true)
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)

    const files = e.dataTransfer.files
    if (files && files.length > 0) {
      handleFileUpload(files)
    }
  }

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      handleFileUpload(files)
    }
    // Reset input value to allow re-selecting the same file
    e.target.value = ''
  }

  const handleToggleArtifact = (artifactId: string) => {
    setSelectedArtifacts(prev => {
      const newSet = new Set(prev)
      if (newSet.has(artifactId)) {
        newSet.delete(artifactId)
      } else {
        newSet.add(artifactId)
      }
      return newSet
    })
  }

  const handleSelectAll = () => {
    if (selectedArtifacts.size === artifacts.length) {
      setSelectedArtifacts(new Set())
    } else {
      setSelectedArtifacts(new Set(artifacts.map(a => a.id)))
    }
  }

  const handleBulkDelete = async () => {
    if (!token || selectedArtifacts.size === 0) return

    const confirmed = window.confirm(
      `Delete ${selectedArtifacts.size} file(s)? This will permanently remove them from storage and delete artifact records. This cannot be undone.`
    )
    if (!confirmed) return

    setIsDeletingBulk(true)
    setError('')
    setSuccessMessage('')

    try {
      // Use bulk delete API for better performance
      const result = await objectStorageApi.bulkDeleteArtifacts(
        Array.from(selectedArtifacts),
        token
      )

      // Show results
      if (result.succeeded > 0 && result.failed === 0) {
        setSuccessMessage(`Successfully deleted ${result.succeeded} file(s) and artifact records`)
      } else if (result.succeeded > 0 && result.failed > 0) {
        setSuccessMessage(`Deleted ${result.succeeded} file(s), ${result.failed} failed`)
      } else if (result.failed > 0) {
        setError(`Failed to delete ${result.failed} file(s)`)
      }

      // Clear selection and reload
      setSelectedArtifacts(new Set())
      if (selectedBucket) {
        await loadArtifactsForBucket(selectedBucket)
      }
    } finally {
      setIsDeletingBulk(false)
    }
  }

  const handlePreviewArtifact = async (artifact: Artifact) => {
    if (!token) return

    setPreviewArtifact(artifact)
    setIsLoadingPreview(true)
    setPreviewBlob(null)
    setPreviewError(null)

    try {
      const blob = await objectStorageApi.downloadFile(artifact.document_id, artifact.artifact_type as any)
      setPreviewBlob(blob)
    } catch (err: any) {
      console.error('Preview failed:', err)
      setPreviewError(err.message || 'Failed to load preview')
    } finally {
      setIsLoadingPreview(false)
    }
  }

  const handleClosePreview = () => {
    setPreviewArtifact(null)
    setPreviewBlob(null)
    setPreviewError(null)
  }

  const handleRefresh = () => {
    loadHealthData()
    if (selectedBucket) {
      loadArtifactsForBucket(selectedBucket)
    }
  }

  const handleSort = (column: 'filename' | 'type' | 'size' | 'status' | 'created') => {
    if (sortColumn === column) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortColumn(column)
      setSortDirection('asc')
    }
  }

  // Filter and sort artifacts
  const filteredAndSortedArtifacts = React.useMemo(() => {
    let filtered = artifacts

    // Apply search filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase()
      filtered = filtered.filter(artifact =>
        artifact.original_filename.toLowerCase().includes(query) ||
        artifact.artifact_type.toLowerCase().includes(query) ||
        artifact.status.toLowerCase().includes(query)
      )
    }

    // Apply sorting
    const sorted = [...filtered].sort((a, b) => {
      let comparison = 0

      switch (sortColumn) {
        case 'filename':
          comparison = a.original_filename.localeCompare(b.original_filename)
          break
        case 'type':
          comparison = a.artifact_type.localeCompare(b.artifact_type)
          break
        case 'size':
          comparison = (a.file_size || 0) - (b.file_size || 0)
          break
        case 'status':
          comparison = a.status.localeCompare(b.status)
          break
        case 'created':
          comparison = new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
          break
      }

      return sortDirection === 'asc' ? comparison : -comparison
    })

    return sorted
  }, [artifacts, searchQuery, sortColumn, sortDirection])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="text-center">
          <Loader2 className="h-12 w-12 text-indigo-600 dark:text-indigo-400 animate-spin mx-auto" />
          <p className="mt-4 text-gray-600 dark:text-gray-400">Loading storage data...</p>
        </div>
      </div>
    )
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'healthy':
        return 'from-emerald-500 to-teal-600'
      case 'unhealthy':
        return 'from-red-500 to-rose-600'
      case 'disabled':
        return 'from-gray-400 to-gray-500'
      default:
        return 'from-gray-400 to-gray-500'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'healthy':
        return <CheckCircle className="h-5 h-5 text-emerald-600 dark:text-emerald-400" />
      case 'unhealthy':
        return <XCircle className="h-5 h-5 text-red-600 dark:text-red-400" />
      case 'disabled':
        return <AlertCircle className="h-5 h-5 text-gray-600 dark:text-gray-400" />
      default:
        return <AlertCircle className="h-5 h-5 text-gray-600 dark:text-gray-400" />
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-4">
            <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25">
              <Database className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                Object Storage
              </h1>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                S3-compatible object storage management (MinIO/AWS S3)
              </p>
            </div>
          </div>

          <button
            onClick={handleRefresh}
            className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors shadow-sm"
          >
            <RefreshCw className="w-4 h-4" />
            <span className="text-sm font-medium hidden sm:inline">Refresh</span>
          </button>
        </div>

        {/* Success Banner */}
        {successMessage && (
          <div className="mb-6 rounded-xl bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-100 dark:border-emerald-900/50 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
                  <CheckCircle className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                </div>
                <p className="text-sm font-medium text-emerald-800 dark:text-emerald-200">{successMessage}</p>
              </div>
              <button
                onClick={() => setSuccessMessage('')}
                className="text-emerald-600 dark:text-emerald-400 hover:text-emerald-700 dark:hover:text-emerald-300"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>
        )}

        {/* Error Banner */}
        {error && (
          <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                  <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
                </div>
                <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
              </div>
              <button
                onClick={() => setError('')}
                className="text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>
        )}

        {/* Storage Not Enabled Message */}
        {healthData && !healthData.enabled && (
          <div className="relative overflow-hidden rounded-2xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/50 px-6 py-16 text-center">
            <div className="absolute inset-0 pointer-events-none">
              <div className="absolute -top-24 -right-24 w-64 h-64 rounded-full bg-gradient-to-br from-indigo-500/5 to-purple-500/5 blur-3xl"></div>
            </div>
            <div className="relative">
              <div className="mx-auto w-20 h-20 rounded-2xl bg-gradient-to-br from-gray-400 to-gray-500 flex items-center justify-center shadow-xl shadow-gray-500/25 mb-6">
                <Database className="w-10 h-10 text-white" />
              </div>
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                Object Storage Not Enabled
              </h3>
              <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto mb-4">
                Object storage is currently disabled. Enable it in your configuration to use S3-compatible storage.
              </p>
              <p className="text-sm text-gray-400 dark:text-gray-500">
                Set <code className="px-2 py-0.5 bg-gray-100 dark:bg-gray-800 rounded">USE_OBJECT_STORAGE=true</code> in your environment
              </p>
            </div>
          </div>
        )}

        {/* Storage Enabled Content */}
        {healthData && healthData.enabled && (
          <>
            {/* Folder Browser View */}
            <div className="mb-8">
              <StorageFolderBrowser
                onFileUpload={handleOpenUpload}
                onFilePreview={async (bucket, key, filename) => {
                    try {
                      console.log('Preview request:', { bucket, key, filename })
                      setIsLoadingPreview(true)
                      setPreviewBlob(null)
                      setPreviewError(null)

                      // Direct proxy download with inline=true
                      const blob = await objectStorageApi.downloadObject(bucket, key, true, token ?? undefined)

                      // Set preview artifact (mock structure for preview modal)
                      setPreviewArtifact({
                        id: key, // Use key as ID for non-artifact files
                        document_id: '',
                        artifact_type: 'uploaded',
                        bucket: bucket,
                        object_key: key,
                        original_filename: filename,
                        content_type: blob.type || 'application/octet-stream',
                        file_size: blob.size,
                        status: 'available',
                        created_at: new Date().toISOString(),
                      })

                      setPreviewBlob(blob)
                    } catch (err: any) {
                      console.error('Preview failed:', err)
                      setPreviewError(err.message || 'Failed to load preview')
                    } finally {
                      setIsLoadingPreview(false)
                    }
                  }}
                  onFileDownload={async (bucket, key, filename) => {
                    try {
                      // Direct proxy download
                      const blob = await objectStorageApi.downloadObject(bucket, key, false, token ?? undefined)
                      utils.downloadBlob(blob, filename)
                    } catch (err: any) {
                      console.error('Download failed:', err)
                      setError(`Failed to download: ${err.message}`)
                    }
                  }}
                />
            </div>
          </>
        )}

      {/* Preview Modal */}
      {previewArtifact && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="relative bg-white dark:bg-gray-800 rounded-2xl shadow-2xl max-w-5xl w-full max-h-[90vh] flex flex-col overflow-hidden">
            {/* Modal Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-600">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-white/20 flex items-center justify-center">
                  <Eye className="w-5 h-5 text-white" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-white">
                    {previewArtifact.original_filename}
                  </h3>
                  <p className="text-xs text-indigo-100 mt-0.5">
                    {formatBytes(previewArtifact.file_size || 0)} • {previewArtifact.artifact_type}
                  </p>
                </div>
              </div>
              <button
                onClick={handleClosePreview}
                className="text-white hover:bg-white/20 rounded-lg p-2 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Content */}
            <div className="flex-1 overflow-auto p-6">
              {isLoadingPreview ? (
                <div className="flex flex-col items-center justify-center py-12">
                  <Loader2 className="h-12 w-12 text-indigo-600 dark:text-indigo-400 animate-spin mb-4" />
                  <p className="text-sm text-gray-500 dark:text-gray-400">Loading preview...</p>
                </div>
              ) : previewError ? (
                <div className="flex flex-col items-center justify-center py-12">
                  <div className="w-16 h-16 rounded-2xl bg-red-100 dark:bg-red-900/30 flex items-center justify-center mb-4">
                    <AlertCircle className="w-8 h-8 text-red-600 dark:text-red-400" />
                  </div>
                  <p className="text-sm font-medium text-red-800 dark:text-red-200 mb-2">Preview Failed</p>
                  <p className="text-sm text-gray-600 dark:text-gray-400">{previewError}</p>
                </div>
              ) : previewBlob ? (
                <FilePreview
                  blob={previewBlob}
                  filename={previewArtifact.original_filename}
                  contentType={previewArtifact.content_type}
                />
              ) : null}
            </div>

            {/* Modal Footer */}
            <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
              <div className="text-xs text-gray-500 dark:text-gray-400">
                Created: {formatDate(previewArtifact.created_at)}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => {
                    handleDownloadArtifact(previewArtifact)
                  }}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors"
                >
                  <Download className="w-4 h-4" />
                  Download
                </button>
                <button
                  onClick={handleClosePreview}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg transition-colors"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Upload Modal */}
      {showUploadModal && uploadTargetBucket && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="relative bg-white dark:bg-gray-800 rounded-2xl shadow-2xl max-w-lg w-full overflow-hidden">
            {/* Modal Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gradient-to-r from-emerald-600 via-teal-600 to-emerald-600">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-white/20 flex items-center justify-center">
                  <Upload className="w-5 h-5 text-white" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-white">Upload Files</h3>
                  <p className="text-xs text-emerald-100 mt-0.5">
                    {uploadTargetBucket} / {uploadTargetPrefix || '(root)'}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowUploadModal(false)}
                disabled={isUploading}
                className="text-white hover:bg-white/20 rounded-lg p-2 transition-colors disabled:opacity-50"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-6">
              <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                className={`relative bg-white dark:bg-gray-900 rounded-xl border-2 border-dashed transition-all ${
                  dragActive
                    ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20'
                    : 'border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500'
                }`}
              >
                <div className="px-6 py-10 text-center">
                  <div className="flex flex-col items-center">
                    <div className={`w-16 h-16 rounded-2xl flex items-center justify-center mb-4 transition-colors ${
                      dragActive
                        ? 'bg-emerald-100 dark:bg-emerald-900/30'
                        : 'bg-gray-100 dark:bg-gray-700'
                    }`}>
                      <Upload className={`w-8 h-8 ${
                        dragActive ? 'text-emerald-600 dark:text-emerald-400' : 'text-gray-400 dark:text-gray-500'
                      }`} />
                    </div>
                    <h4 className="text-base font-semibold text-gray-900 dark:text-white mb-2">
                      Drop files here
                    </h4>
                    <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                      or click to browse
                    </p>
                    <button
                      onClick={() => fileInputRef.current?.click()}
                      disabled={isUploading}
                      className="inline-flex items-center gap-2 px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg transition-colors shadow-lg shadow-emerald-500/25 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isUploading ? (
                        <>
                          <Loader2 className="w-5 h-5 animate-spin" />
                          Uploading...
                        </>
                      ) : (
                        <>
                          <Upload className="w-5 h-5" />
                          Select Files
                        </>
                      )}
                    </button>
                    <input
                      ref={fileInputRef}
                      type="file"
                      multiple
                      onChange={handleFileInputChange}
                      className="hidden"
                    />
                  </div>
                </div>
              </div>

              {uploadTargetPrefix && (
                <div className="mt-4 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                  <p className="text-xs text-blue-800 dark:text-blue-200">
                    <strong>Note:</strong> Files will be uploaded to: <span className="font-mono">{uploadTargetBucket}/{uploadTargetPrefix}</span>
                  </p>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
              <button
                onClick={() => setShowUploadModal(false)}
                disabled={isUploading}
                className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  )
}

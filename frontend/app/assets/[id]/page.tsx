'use client'

import { useState, useEffect } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { assetsApi } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import {
  FileText,
  RefreshCw,
  ArrowLeft,
  Download,
  Eye,
  Clock,
  AlertTriangle,
  CheckCircle,
  Loader2,
  XCircle,
  FolderOpen,
  FileCode,
  History,
  Tag,
} from 'lucide-react'
import ProtectedRoute from '@/components/auth/ProtectedRoute'

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

interface ExtractionResult {
  id: string
  asset_id: string
  run_id: string
  extractor_version: string
  status: string
  extraction_time_seconds: number | null
  extracted_bucket: string | null
  extracted_object_key: string | null
  structure_metadata: Record<string, any> | null
  warnings: string[]
  errors: string[]
  created_at: string
}

interface AssetVersion {
  id: string
  asset_id: string
  version_number: number
  raw_bucket: string
  raw_object_key: string
  file_size: number | null
  file_hash: string | null
  content_type: string | null
  is_current: boolean
  created_at: string
  created_by: string | null
}

interface Run {
  id: string
  organization_id: string
  run_type: string
  origin: string
  status: string
  input_asset_ids: string[]
  config: Record<string, any>
  progress: number | null
  results_summary: Record<string, any> | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  created_by: string | null
}

type TabType = 'original' | 'extracted' | 'metadata' | 'history'

export default function AssetDetailPage() {
  return (
    <ProtectedRoute>
      <AssetDetailContent />
    </ProtectedRoute>
  )
}

function AssetDetailContent() {
  const router = useRouter()
  const params = useParams()
  const { token } = useAuth()
  const assetId = params?.id as string

  const [asset, setAsset] = useState<Asset | null>(null)
  const [extraction, setExtraction] = useState<ExtractionResult | null>(null)
  const [versions, setVersions] = useState<AssetVersion[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [extractedContent, setExtractedContent] = useState<string>('')
  const [activeTab, setActiveTab] = useState<TabType>('original')
  const [isLoading, setIsLoading] = useState(true)
  const [isReextracting, setIsReextracting] = useState(false)
  const [isLoadingContent, setIsLoadingContent] = useState(false)
  const [error, setError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  // Load asset data
  useEffect(() => {
    if (token && assetId) {
      loadAssetData()
    }
  }, [token, assetId])

  // Auto-poll when asset is processing
  useEffect(() => {
    if (asset?.status === 'pending') {
      const intervalId = setInterval(() => {
        loadAssetData(true) // Silent polling - don't show loading spinner
      }, 5000) // Poll every 5 seconds (reduced from 3)

      return () => clearInterval(intervalId)
    }
  }, [asset?.status])

  const loadAssetData = async (silent = false) => {
    if (!token || !assetId) return

    if (!silent) {
      setIsLoading(true)
    }
    setError('')

    try {
      // Load asset with extraction
      const assetWithExtraction = await assetsApi.getAssetWithExtraction(token, assetId)
      setAsset(assetWithExtraction.asset)
      setExtraction(assetWithExtraction.extraction)

      // Load version history
      const versionHistory = await assetsApi.getAssetVersions(token, assetId)
      setVersions(versionHistory.versions)

      // Load runs
      const runsData = await assetsApi.getAssetRuns(token, assetId)
      setRuns(runsData)
    } catch (err: any) {
      if (!silent) {
        setError(err.message || 'Failed to load asset')
      }
    } finally {
      if (!silent) {
        setIsLoading(false)
      }
    }
  }

  // Load extracted content when tab is activated
  useEffect(() => {
    if (activeTab === 'extracted' && extraction && !extractedContent && !isLoadingContent) {
      loadExtractedContent()
    }
  }, [activeTab, extraction])

  const loadExtractedContent = async () => {
    if (!extraction?.extracted_object_key || !extraction?.extracted_bucket || !token) return

    setIsLoadingContent(true)
    try {
      // Download extracted content from object storage via proxy
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      // Manually encode the key to preserve special characters like +
      const url = `${apiUrl}/api/v1/storage/object/download?bucket=${encodeURIComponent(extraction.extracted_bucket)}&key=${encodeURIComponent(extraction.extracted_object_key)}`

      const response = await fetch(url, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      })

      if (!response.ok) {
        throw new Error(`Failed to download content: ${response.statusText}`)
      }

      const content = await response.text()
      setExtractedContent(content)
    } catch (err: any) {
      setExtractedContent(`# Error Loading Content\n\n${err.message}`)
    } finally {
      setIsLoadingContent(false)
    }
  }

  const handleReextract = async () => {
    if (!token || !assetId) return

    if (!confirm('Re-extract this document? This will create a new extraction run.')) {
      return
    }

    setIsReextracting(true)
    setError('')
    setSuccessMessage('')
    try {
      const run = await assetsApi.reextractAsset(token, assetId)

      // Show success message
      setSuccessMessage(`Re-extraction started successfully (Run ID: ${run.id.substring(0, 8)}...)`)

      // Reload asset data to show new run
      setTimeout(() => {
        loadAssetData()
        setSuccessMessage('')
      }, 3000)
    } catch (err: any) {
      setError(`Failed to trigger re-extraction: ${err.message}`)
    } finally {
      setIsReextracting(false)
    }
  }

  const handleBack = () => {
    router.push('/')
  }

  const getStatusConfig = (status: string) => {
    switch (status) {
      case 'ready':
        return {
          label: 'Ready',
          icon: <CheckCircle className="w-4 h-4" />,
          gradient: 'from-emerald-500 to-emerald-600',
          bgColor: 'bg-emerald-50 dark:bg-emerald-900/20',
          textColor: 'text-emerald-700 dark:text-emerald-400',
        }
      case 'pending':
        return {
          label: 'Processing',
          icon: <Loader2 className="w-4 h-4 animate-spin" />,
          gradient: 'from-blue-500 to-blue-600',
          bgColor: 'bg-blue-50 dark:bg-blue-900/20',
          textColor: 'text-blue-700 dark:text-blue-400',
        }
      case 'failed':
        return {
          label: 'Failed',
          icon: <XCircle className="w-4 h-4" />,
          gradient: 'from-red-500 to-red-600',
          bgColor: 'bg-red-50 dark:bg-red-900/20',
          textColor: 'text-red-700 dark:text-red-400',
        }
      default:
        return {
          label: status,
          icon: <AlertTriangle className="w-4 h-4" />,
          gradient: 'from-gray-500 to-gray-600',
          bgColor: 'bg-gray-50 dark:bg-gray-900/20',
          textColor: 'text-gray-700 dark:text-gray-400',
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
    return new Date(dateString).toLocaleString()
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin"></div>
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading asset...</p>
          </div>
        </div>
      </div>
    )
  }

  if (error || !asset) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
            <div className="flex items-center gap-3">
              <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
              </div>
              <p className="text-sm font-medium text-red-800 dark:text-red-200">{error || 'Asset not found'}</p>
            </div>
          </div>
          <Button variant="secondary" onClick={handleBack} className="gap-2">
            <ArrowLeft className="w-4 h-4" />
            Back to Documents
          </Button>
        </div>
      </div>
    )
  }

  const statusConfig = getStatusConfig(asset.status)

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-4 mb-6">
            <Button variant="secondary" onClick={handleBack} className="gap-2">
              <ArrowLeft className="w-4 h-4" />
              <span className="hidden sm:inline">Back</span>
            </Button>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="flex items-start gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25 flex-shrink-0">
                <FileText className="w-6 h-6" />
              </div>
              <div className="flex-1 min-w-0">
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white break-words">
                  {asset.original_filename}
                </h1>
                <div className="flex flex-wrap items-center gap-3 mt-2">
                  <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${statusConfig.bgColor} ${statusConfig.textColor}`}>
                    {statusConfig.icon}
                    <span>{statusConfig.label}</span>
                  </div>
                  {asset.status === 'pending' && (
                    <div className="inline-flex items-center gap-1.5 text-xs text-blue-600 dark:text-blue-400">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      <span className="font-medium">Extracting...</span>
                    </div>
                  )}
                  {asset.current_version_number && (
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      Version {asset.current_version_number}
                    </span>
                  )}
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {formatBytes(asset.file_size)}
                  </span>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                onClick={handleReextract}
                disabled={isReextracting || asset.status === 'pending'}
                className="gap-2 whitespace-nowrap opacity-100 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <RefreshCw className={`w-4 h-4 ${isReextracting || asset.status === 'pending' ? 'animate-spin' : ''}`} />
                <span className="whitespace-nowrap">
                  {isReextracting ? 'Starting...' : asset.status === 'pending' ? 'Processing...' : 'Re-extract'}
                </span>
              </Button>
            </div>
          </div>

          {/* Success Message */}
          {successMessage && (
            <div className="mt-6 rounded-xl bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-100 dark:border-emerald-900/50 p-4">
              <div className="flex items-center gap-3">
                <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
                  <CheckCircle className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                </div>
                <p className="text-sm font-medium text-emerald-800 dark:text-emerald-200">{successMessage}</p>
              </div>
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div className="mt-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
              <div className="flex items-center gap-3">
                <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                  <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
                </div>
                <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
              </div>
            </div>
          )}

          {/* Asset Info Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-6">
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
                  <FolderOpen className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Source</p>
                  <p className="text-sm font-medium text-gray-900 dark:text-white capitalize">{asset.source_type}</p>
                </div>
              </div>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-purple-50 dark:bg-purple-900/20 flex items-center justify-center">
                  <FileCode className="w-5 h-5 text-purple-600 dark:text-purple-400" />
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Type</p>
                  <p className="text-sm font-medium text-gray-900 dark:text-white">{asset.content_type || 'Unknown'}</p>
                </div>
              </div>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center">
                  <Clock className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Created</p>
                  <p className="text-sm font-medium text-gray-900 dark:text-white">{formatDate(asset.created_at)}</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="mb-6">
          <div className="border-b border-gray-200 dark:border-gray-700">
            <nav className="-mb-px flex space-x-8">
              <button
                onClick={() => setActiveTab('original')}
                className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                  activeTab === 'original'
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
                }`}
              >
                <div className="flex items-center gap-2">
                  <Eye className="w-4 h-4" />
                  Original
                </div>
              </button>
              <button
                onClick={() => setActiveTab('extracted')}
                className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                  activeTab === 'extracted'
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
                }`}
              >
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4" />
                  Extracted Content
                </div>
              </button>
              <button
                onClick={() => setActiveTab('metadata')}
                className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                  activeTab === 'metadata'
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
                }`}
              >
                <div className="flex items-center gap-2">
                  <Tag className="w-4 h-4" />
                  Metadata
                </div>
              </button>
              <button
                onClick={() => setActiveTab('history')}
                className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                  activeTab === 'history'
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
                }`}
              >
                <div className="flex items-center gap-2">
                  <History className="w-4 h-4" />
                  History
                  {versions.length > 1 && (
                    <span className="ml-1 px-1.5 py-0.5 text-xs font-medium rounded-full bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400">
                      {versions.length}
                    </span>
                  )}
                </div>
              </button>
            </nav>
          </div>
        </div>

        {/* Tab Content */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          {activeTab === 'original' && (
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Original File</h3>
              <div className="space-y-4">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-500 dark:text-gray-400">Storage Bucket</span>
                  <span className="font-mono text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/50 px-2 py-0.5 rounded">
                    {asset.raw_bucket}
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-500 dark:text-gray-400">Object Key</span>
                  <span className="font-mono text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/50 px-2 py-0.5 rounded truncate max-w-[300px]">
                    {asset.raw_object_key}
                  </span>
                </div>
                {asset.file_hash && (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-500 dark:text-gray-400">File Hash (SHA-256)</span>
                    <span className="font-mono text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/50 px-2 py-0.5 rounded truncate max-w-[300px]">
                      {asset.file_hash}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === 'extracted' && (
            <div>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Extracted Content</h3>
                {extraction && (
                  <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${getStatusConfig(extraction.status).bgColor} ${getStatusConfig(extraction.status).textColor}`}>
                    {getStatusConfig(extraction.status).icon}
                    <span>{getStatusConfig(extraction.status).label}</span>
                  </div>
                )}
              </div>
              {extraction ? (
                <div>
                  {isLoadingContent ? (
                    <div className="flex items-center justify-center py-8">
                      <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
                    </div>
                  ) : (
                    <div className="prose dark:prose-invert max-w-none">
                      <pre className="bg-gray-50 dark:bg-gray-900/50 p-4 rounded-lg overflow-x-auto text-sm">
                        {extractedContent || 'No content available'}
                      </pre>
                    </div>
                  )}
                  <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <span className="text-gray-500 dark:text-gray-400">Extractor Version</span>
                        <p className="font-mono text-xs text-gray-700 dark:text-gray-300 mt-1">
                          {extraction.extractor_version}
                        </p>
                      </div>
                      {extraction.extraction_time_seconds && (
                        <div>
                          <span className="text-gray-500 dark:text-gray-400">Processing Time</span>
                          <p className="font-mono text-xs text-gray-700 dark:text-gray-300 mt-1">
                            {extraction.extraction_time_seconds.toFixed(2)}s
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                  <FileText className="w-12 h-12 mx-auto mb-3 opacity-50" />
                  <p>No extraction result available</p>
                </div>
              )}
            </div>
          )}

          {activeTab === 'metadata' && (
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Metadata</h3>
              <div className="space-y-4">
                <div>
                  <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Asset Metadata</h4>
                  <pre className="bg-gray-50 dark:bg-gray-900/50 p-4 rounded-lg overflow-x-auto text-xs">
                    {JSON.stringify(asset.source_metadata, null, 2)}
                  </pre>
                </div>
                {extraction?.structure_metadata && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Extraction Metadata</h4>
                    <pre className="bg-gray-50 dark:bg-gray-900/50 p-4 rounded-lg overflow-x-auto text-xs">
                      {JSON.stringify(extraction.structure_metadata, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === 'history' && (
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Version History</h3>
              {versions.length > 0 ? (
                <div className="space-y-4">
                  {versions.map((version) => (
                    <div
                      key={version.id}
                      className={`p-4 rounded-lg border ${
                        version.is_current
                          ? 'border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-900/10'
                          : 'border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50'
                      }`}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex items-center gap-3">
                          <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                            version.is_current
                              ? 'bg-indigo-100 dark:bg-indigo-900/30'
                              : 'bg-gray-100 dark:bg-gray-800'
                          }`}>
                            <span className={`text-sm font-bold ${
                              version.is_current
                                ? 'text-indigo-600 dark:text-indigo-400'
                                : 'text-gray-600 dark:text-gray-400'
                            }`}>
                              v{version.version_number}
                            </span>
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <p className="text-sm font-medium text-gray-900 dark:text-white">
                                Version {version.version_number}
                              </p>
                              {version.is_current && (
                                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400">
                                  Current
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                              {formatDate(version.created_at)}
                            </p>
                          </div>
                        </div>
                        <div className="text-right">
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            {formatBytes(version.file_size)}
                          </p>
                          {version.file_hash && (
                            <p className="text-xs font-mono text-gray-400 dark:text-gray-500 mt-1 truncate max-w-[100px]">
                              {version.file_hash.substring(0, 8)}...
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}

                  {/* Runs Timeline */}
                  {runs.length > 0 && (
                    <div className="mt-8">
                      <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Processing Runs</h4>
                      <div className="space-y-3">
                        {runs.map((run) => (
                          <div
                            key={run.id}
                            className="flex items-start gap-3 p-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/50"
                          >
                            <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                              run.status === 'completed'
                                ? 'bg-emerald-100 dark:bg-emerald-900/30'
                                : run.status === 'failed'
                                ? 'bg-red-100 dark:bg-red-900/30'
                                : 'bg-blue-100 dark:bg-blue-900/30'
                            }`}>
                              {run.status === 'completed' ? (
                                <CheckCircle className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                              ) : run.status === 'failed' ? (
                                <XCircle className="w-4 h-4 text-red-600 dark:text-red-400" />
                              ) : (
                                <Loader2 className="w-4 h-4 text-blue-600 dark:text-blue-400 animate-spin" />
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <p className="text-sm font-medium text-gray-900 dark:text-white capitalize">
                                  {run.run_type}
                                </p>
                                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 capitalize">
                                  {run.origin}
                                </span>
                              </div>
                              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                                {formatDate(run.created_at)}
                              </p>
                              {run.error_message && (
                                <p className="text-xs text-red-600 dark:text-red-400 mt-1">
                                  {run.error_message}
                                </p>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                  <History className="w-12 h-12 mx-auto mb-3 opacity-50" />
                  <p>No version history available</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

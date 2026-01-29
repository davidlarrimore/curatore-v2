'use client'

import { useState, useEffect } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { assetsApi, type Run, type AssetMetadata, type AssetMetadataList } from '@/lib/api'
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
  Star,
  TestTube2,
  ArrowUp,
  Trash2,
  ChevronDown,
  ChevronRight,
  GitCompare,
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

  // Phase 3: Metadata state
  const [metadataList, setMetadataList] = useState<AssetMetadataList | null>(null)
  const [isLoadingMetadata, setIsLoadingMetadata] = useState(false)
  const [expandedExperimental, setExpandedExperimental] = useState(false)
  const [isPromoting, setIsPromoting] = useState<string | null>(null)
  const [selectedForCompare, setSelectedForCompare] = useState<string[]>([])
  const [compareResult, setCompareResult] = useState<any | null>(null)
  const [isComparing, setIsComparing] = useState(false)

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

  // Phase 3: Load metadata when metadata tab is active
  useEffect(() => {
    if (activeTab === 'metadata' && token && assetId && !metadataList && !isLoadingMetadata) {
      loadAssetMetadata()
    }
  }, [activeTab, token, assetId])

  const loadAssetMetadata = async () => {
    if (!token || !assetId) return

    setIsLoadingMetadata(true)
    try {
      const metadata = await assetsApi.getAssetMetadata(token, assetId)
      setMetadataList(metadata)
    } catch (err: any) {
      console.error('Failed to load asset metadata:', err)
    } finally {
      setIsLoadingMetadata(false)
    }
  }

  const handlePromoteMetadata = async (metadataId: string) => {
    if (!token || !assetId) return

    if (!confirm('Promote this metadata to canonical? This will supersede the current canonical metadata of this type.')) {
      return
    }

    setIsPromoting(metadataId)
    try {
      const result = await assetsApi.promoteMetadata(token, assetId, metadataId)
      setSuccessMessage(result.message)
      // Reload metadata
      await loadAssetMetadata()
      setTimeout(() => setSuccessMessage(''), 3000)
    } catch (err: any) {
      setError(`Failed to promote metadata: ${err.message}`)
      setTimeout(() => setError(''), 5000)
    } finally {
      setIsPromoting(null)
    }
  }

  const handleDeleteMetadata = async (metadataId: string, hardDelete: boolean = false) => {
    if (!token || !assetId) return

    const action = hardDelete ? 'permanently delete' : 'deprecate'
    if (!confirm(`Are you sure you want to ${action} this metadata?`)) {
      return
    }

    try {
      await assetsApi.deleteMetadata(token, assetId, metadataId, hardDelete)
      setSuccessMessage(hardDelete ? 'Metadata deleted' : 'Metadata deprecated')
      await loadAssetMetadata()
      setTimeout(() => setSuccessMessage(''), 3000)
    } catch (err: any) {
      setError(`Failed to ${action} metadata: ${err.message}`)
      setTimeout(() => setError(''), 5000)
    }
  }

  const handleCompareMetadata = async () => {
    if (!token || !assetId || selectedForCompare.length !== 2) return

    setIsComparing(true)
    try {
      const result = await assetsApi.compareMetadata(token, assetId, selectedForCompare[0], selectedForCompare[1])
      setCompareResult(result)
    } catch (err: any) {
      setError(`Failed to compare metadata: ${err.message}`)
      setTimeout(() => setError(''), 5000)
    } finally {
      setIsComparing(false)
    }
  }

  const toggleCompareSelection = (metadataId: string) => {
    setSelectedForCompare(prev => {
      if (prev.includes(metadataId)) {
        return prev.filter(id => id !== metadataId)
      }
      if (prev.length >= 2) {
        // Replace the first selected
        return [prev[1], metadataId]
      }
      return [...prev, metadataId]
    })
    setCompareResult(null) // Clear comparison when selection changes
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
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Original File</h3>
                <Button
                  variant="secondary"
                  onClick={() => {
                    if (!token) return
                    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
                    const url = `${apiUrl}/api/v1/storage/object/download?bucket=${encodeURIComponent(asset.raw_bucket)}&key=${encodeURIComponent(asset.raw_object_key)}`
                    window.open(url + `&inline=false`, '_blank')
                  }}
                  className="gap-2"
                >
                  <Download className="w-4 h-4" />
                  Download
                </Button>
              </div>

              {/* Preview based on content type */}
              <div className="mb-6">
                {asset.content_type?.startsWith('image/') ? (
                  <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                    <img
                      src={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/storage/object/download?bucket=${encodeURIComponent(asset.raw_bucket)}&key=${encodeURIComponent(asset.raw_object_key)}&inline=true`}
                      alt={asset.original_filename}
                      className="max-w-full h-auto"
                    />
                  </div>
                ) : asset.content_type === 'application/pdf' ? (
                  <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden" style={{ height: '600px' }}>
                    <iframe
                      src={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/storage/object/download?bucket=${encodeURIComponent(asset.raw_bucket)}&key=${encodeURIComponent(asset.raw_object_key)}&inline=true`}
                      className="w-full h-full"
                      title={asset.original_filename}
                    />
                  </div>
                ) : asset.content_type === 'text/html' ? (
                  <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden" style={{ height: '600px' }}>
                    <iframe
                      src={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/storage/object/download?bucket=${encodeURIComponent(asset.raw_bucket)}&key=${encodeURIComponent(asset.raw_object_key)}&inline=true`}
                      className="w-full h-full bg-white"
                      title={asset.original_filename}
                      sandbox="allow-same-origin"
                    />
                  </div>
                ) : asset.content_type === 'text/plain' || asset.content_type === 'text/csv' || asset.content_type === 'text/markdown' ? (
                  <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden" style={{ height: '600px' }}>
                    <iframe
                      src={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/storage/object/download?bucket=${encodeURIComponent(asset.raw_bucket)}&key=${encodeURIComponent(asset.raw_object_key)}&inline=true`}
                      className="w-full h-full bg-white dark:bg-gray-900"
                      title={asset.original_filename}
                    />
                  </div>
                ) : asset.content_type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' || asset.content_type === 'application/msword' ? (
                  <div className="p-8 text-center border-2 border-dashed border-gray-200 dark:border-gray-700 rounded-lg bg-gradient-to-br from-blue-50 to-indigo-50 dark:from-blue-900/10 dark:to-indigo-900/10">
                    <div className="w-16 h-16 mx-auto mb-4 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg">
                      <FileText className="w-8 h-8 text-white" />
                    </div>
                    <p className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
                      Microsoft Word Document
                    </p>
                    <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                      {asset.original_filename}
                    </p>
                    <div className="flex items-center justify-center gap-3">
                      <Button
                        variant="primary"
                        onClick={() => {
                          if (!token) return
                          const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
                          const url = `${apiUrl}/api/v1/storage/object/download?bucket=${encodeURIComponent(asset.raw_bucket)}&key=${encodeURIComponent(asset.raw_object_key)}&inline=false`
                          window.open(url, '_blank')
                        }}
                        className="gap-2"
                      >
                        <Download className="w-4 h-4" />
                        Download Document
                      </Button>
                    </div>
                    <p className="text-xs text-gray-400 dark:text-gray-500 mt-4">
                      View the extracted markdown in the "Extracted Content" tab
                    </p>
                  </div>
                ) : asset.content_type === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' || asset.content_type === 'application/vnd.ms-excel' ? (
                  <div className="p-8 text-center border-2 border-dashed border-gray-200 dark:border-gray-700 rounded-lg bg-gradient-to-br from-emerald-50 to-green-50 dark:from-emerald-900/10 dark:to-green-900/10">
                    <div className="w-16 h-16 mx-auto mb-4 rounded-xl bg-gradient-to-br from-emerald-500 to-green-600 flex items-center justify-center shadow-lg">
                      <FileText className="w-8 h-8 text-white" />
                    </div>
                    <p className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
                      Microsoft Excel Spreadsheet
                    </p>
                    <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                      {asset.original_filename}
                    </p>
                    <div className="flex items-center justify-center gap-3">
                      <Button
                        variant="primary"
                        onClick={() => {
                          if (!token) return
                          const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
                          const url = `${apiUrl}/api/v1/storage/object/download?bucket=${encodeURIComponent(asset.raw_bucket)}&key=${encodeURIComponent(asset.raw_object_key)}&inline=false`
                          window.open(url, '_blank')
                        }}
                        className="gap-2"
                      >
                        <Download className="w-4 h-4" />
                        Download Spreadsheet
                      </Button>
                    </div>
                    <p className="text-xs text-gray-400 dark:text-gray-500 mt-4">
                      View the extracted markdown in the "Extracted Content" tab
                    </p>
                  </div>
                ) : asset.content_type === 'application/vnd.openxmlformats-officedocument.presentationml.presentation' || asset.content_type === 'application/vnd.ms-powerpoint' ? (
                  <div className="p-8 text-center border-2 border-dashed border-gray-200 dark:border-gray-700 rounded-lg bg-gradient-to-br from-orange-50 to-red-50 dark:from-orange-900/10 dark:to-red-900/10">
                    <div className="w-16 h-16 mx-auto mb-4 rounded-xl bg-gradient-to-br from-orange-500 to-red-600 flex items-center justify-center shadow-lg">
                      <FileText className="w-8 h-8 text-white" />
                    </div>
                    <p className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
                      Microsoft PowerPoint Presentation
                    </p>
                    <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                      {asset.original_filename}
                    </p>
                    <div className="flex items-center justify-center gap-3">
                      <Button
                        variant="primary"
                        onClick={() => {
                          if (!token) return
                          const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
                          const url = `${apiUrl}/api/v1/storage/object/download?bucket=${encodeURIComponent(asset.raw_bucket)}&key=${encodeURIComponent(asset.raw_object_key)}&inline=false`
                          window.open(url, '_blank')
                        }}
                        className="gap-2"
                      >
                        <Download className="w-4 h-4" />
                        Download Presentation
                      </Button>
                    </div>
                    <p className="text-xs text-gray-400 dark:text-gray-500 mt-4">
                      View the extracted markdown in the "Extracted Content" tab
                    </p>
                  </div>
                ) : (
                  <div className="p-8 text-center border-2 border-dashed border-gray-200 dark:border-gray-700 rounded-lg">
                    <FileText className="w-12 h-12 mx-auto mb-3 text-gray-400" />
                    <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                      Preview not available for this file type
                    </p>
                    <Button
                      variant="secondary"
                      onClick={() => {
                        if (!token) return
                        const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
                        const url = `${apiUrl}/api/v1/storage/object/download?bucket=${encodeURIComponent(asset.raw_bucket)}&key=${encodeURIComponent(asset.raw_object_key)}`
                        window.open(url, '_blank')
                      }}
                      className="gap-2"
                    >
                      <Download className="w-4 h-4" />
                      Download File
                    </Button>
                  </div>
                )}
              </div>

              {/* File Details */}
              <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
                <h4 className="text-sm font-medium text-gray-900 dark:text-white mb-3">File Details</h4>
                <div className="space-y-3">
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
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-6">Document Metadata</h3>

              {/* Phase 3: Canonical vs Experimental Metadata */}
              {isLoadingMetadata ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
                  <span className="ml-2 text-sm text-gray-500 dark:text-gray-400">Loading metadata...</span>
                </div>
              ) : metadataList && (metadataList.canonical.length > 0 || metadataList.experimental.length > 0) ? (
                <div className="space-y-6">
                  {/* Canonical Metadata Section */}
                  <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-emerald-200 dark:border-emerald-800 overflow-hidden">
                    <div className="px-5 py-4 bg-emerald-50 dark:bg-emerald-900/20 border-b border-emerald-200 dark:border-emerald-800">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Star className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                          <h4 className="text-sm font-semibold text-emerald-800 dark:text-emerald-200">
                            Canonical Metadata
                          </h4>
                          <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">
                            {metadataList.total_canonical}
                          </span>
                        </div>
                        <span className="text-xs text-emerald-600 dark:text-emerald-400">Production / Trusted</span>
                      </div>
                    </div>
                    <div className="p-5">
                      {metadataList.canonical.length > 0 ? (
                        <div className="space-y-4">
                          {metadataList.canonical.map((metadata) => (
                            <div key={metadata.id} className="p-4 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
                              <div className="flex items-start justify-between mb-3">
                                <div>
                                  <div className="flex items-center gap-2">
                                    <span className="text-sm font-semibold text-gray-900 dark:text-white">
                                      {metadata.metadata_type}
                                    </span>
                                    <span className="px-1.5 py-0.5 text-xs rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">
                                      canonical
                                    </span>
                                  </div>
                                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                                    Schema v{metadata.schema_version} • Created {formatDate(metadata.created_at)}
                                    {metadata.promoted_at && ` • Promoted ${formatDate(metadata.promoted_at)}`}
                                  </p>
                                </div>
                                <div className="flex items-center gap-2">
                                  <input
                                    type="checkbox"
                                    checked={selectedForCompare.includes(metadata.id)}
                                    onChange={() => toggleCompareSelection(metadata.id)}
                                    className="w-4 h-4 text-indigo-600 rounded border-gray-300 focus:ring-indigo-500"
                                    title="Select for comparison"
                                  />
                                </div>
                              </div>
                              <div className="bg-gray-50 dark:bg-gray-900/50 p-3 rounded-lg">
                                <pre className="text-xs text-gray-700 dark:text-gray-300 overflow-x-auto max-h-32 overflow-y-auto">
                                  {JSON.stringify(metadata.metadata_content, null, 2)}
                                </pre>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-4">
                          No canonical metadata yet. Promote experimental metadata to create canonical versions.
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Experimental Metadata Section */}
                  <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-purple-200 dark:border-purple-800 overflow-hidden">
                    <button
                      onClick={() => setExpandedExperimental(!expandedExperimental)}
                      className="w-full px-5 py-4 bg-purple-50 dark:bg-purple-900/20 border-b border-purple-200 dark:border-purple-800 hover:bg-purple-100 dark:hover:bg-purple-900/30 transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <TestTube2 className="w-5 h-5 text-purple-600 dark:text-purple-400" />
                          <h4 className="text-sm font-semibold text-purple-800 dark:text-purple-200">
                            Experimental Metadata
                          </h4>
                          <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400">
                            {metadataList.total_experimental}
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-purple-600 dark:text-purple-400">Run-attributed / Promotable</span>
                          {expandedExperimental ? (
                            <ChevronDown className="w-4 h-4 text-purple-600 dark:text-purple-400" />
                          ) : (
                            <ChevronRight className="w-4 h-4 text-purple-600 dark:text-purple-400" />
                          )}
                        </div>
                      </div>
                    </button>
                    {expandedExperimental && (
                      <div className="p-5">
                        {metadataList.experimental.length > 0 ? (
                          <div className="space-y-4">
                            {metadataList.experimental.map((metadata) => (
                              <div key={metadata.id} className="p-4 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
                                <div className="flex items-start justify-between mb-3">
                                  <div>
                                    <div className="flex items-center gap-2">
                                      <span className="text-sm font-semibold text-gray-900 dark:text-white">
                                        {metadata.metadata_type}
                                      </span>
                                      <span className="px-1.5 py-0.5 text-xs rounded bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400">
                                        experimental
                                      </span>
                                    </div>
                                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                                      Schema v{metadata.schema_version} • Created {formatDate(metadata.created_at)}
                                      {metadata.producer_run_id && (
                                        <span> • Run: {metadata.producer_run_id.substring(0, 8)}...</span>
                                      )}
                                    </p>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <input
                                      type="checkbox"
                                      checked={selectedForCompare.includes(metadata.id)}
                                      onChange={() => toggleCompareSelection(metadata.id)}
                                      className="w-4 h-4 text-indigo-600 rounded border-gray-300 focus:ring-indigo-500"
                                      title="Select for comparison"
                                    />
                                    <button
                                      onClick={() => handlePromoteMetadata(metadata.id)}
                                      disabled={isPromoting === metadata.id}
                                      className="p-1.5 rounded-lg text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-colors disabled:opacity-50"
                                      title="Promote to canonical"
                                    >
                                      {isPromoting === metadata.id ? (
                                        <Loader2 className="w-4 h-4 animate-spin" />
                                      ) : (
                                        <ArrowUp className="w-4 h-4" />
                                      )}
                                    </button>
                                    <button
                                      onClick={() => handleDeleteMetadata(metadata.id, false)}
                                      className="p-1.5 rounded-lg text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                                      title="Deprecate metadata"
                                    >
                                      <Trash2 className="w-4 h-4" />
                                    </button>
                                  </div>
                                </div>
                                <div className="bg-gray-50 dark:bg-gray-900/50 p-3 rounded-lg">
                                  <pre className="text-xs text-gray-700 dark:text-gray-300 overflow-x-auto max-h-32 overflow-y-auto">
                                    {JSON.stringify(metadata.metadata_content, null, 2)}
                                  </pre>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-4">
                            No experimental metadata. Run experiments to generate metadata variants.
                          </p>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Comparison Section */}
                  {selectedForCompare.length > 0 && (
                    <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-indigo-200 dark:border-indigo-800 overflow-hidden">
                      <div className="px-5 py-4 bg-indigo-50 dark:bg-indigo-900/20 border-b border-indigo-200 dark:border-indigo-800">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <GitCompare className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                            <h4 className="text-sm font-semibold text-indigo-800 dark:text-indigo-200">
                              Compare Metadata
                            </h4>
                            <span className="text-xs text-indigo-600 dark:text-indigo-400">
                              {selectedForCompare.length} selected
                            </span>
                          </div>
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => setSelectedForCompare([])}
                              className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
                            >
                              Clear selection
                            </button>
                            <Button
                              variant="primary"
                              onClick={handleCompareMetadata}
                              disabled={selectedForCompare.length !== 2 || isComparing}
                              className="gap-2 text-xs py-1 px-3"
                            >
                              {isComparing ? (
                                <Loader2 className="w-3 h-3 animate-spin" />
                              ) : (
                                <GitCompare className="w-3 h-3" />
                              )}
                              Compare
                            </Button>
                          </div>
                        </div>
                      </div>
                      {compareResult && (
                        <div className="p-5">
                          <div className="grid grid-cols-2 gap-4 mb-4">
                            <div className="p-3 rounded-lg border border-gray-200 dark:border-gray-700">
                              <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Metadata A</p>
                              <p className="text-sm font-semibold text-gray-900 dark:text-white">{compareResult.metadata_a.metadata_type}</p>
                              <p className="text-xs text-gray-500 dark:text-gray-400">
                                {compareResult.metadata_a.is_canonical ? 'Canonical' : 'Experimental'}
                              </p>
                            </div>
                            <div className="p-3 rounded-lg border border-gray-200 dark:border-gray-700">
                              <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Metadata B</p>
                              <p className="text-sm font-semibold text-gray-900 dark:text-white">{compareResult.metadata_b.metadata_type}</p>
                              <p className="text-xs text-gray-500 dark:text-gray-400">
                                {compareResult.metadata_b.is_canonical ? 'Canonical' : 'Experimental'}
                              </p>
                            </div>
                          </div>
                          <div className="bg-gray-50 dark:bg-gray-900/50 p-4 rounded-lg">
                            <h5 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">Differences</h5>
                            <dl className="space-y-2 text-xs">
                              {compareResult.differences.values_differ.length > 0 && (
                                <div>
                                  <dt className="text-red-600 dark:text-red-400 font-medium">Changed keys:</dt>
                                  <dd className="text-gray-600 dark:text-gray-400">{compareResult.differences.values_differ.join(', ')}</dd>
                                </div>
                              )}
                              {compareResult.differences.keys_only_in_a.length > 0 && (
                                <div>
                                  <dt className="text-amber-600 dark:text-amber-400 font-medium">Only in A:</dt>
                                  <dd className="text-gray-600 dark:text-gray-400">{compareResult.differences.keys_only_in_a.join(', ')}</dd>
                                </div>
                              )}
                              {compareResult.differences.keys_only_in_b.length > 0 && (
                                <div>
                                  <dt className="text-amber-600 dark:text-amber-400 font-medium">Only in B:</dt>
                                  <dd className="text-gray-600 dark:text-gray-400">{compareResult.differences.keys_only_in_b.join(', ')}</dd>
                                </div>
                              )}
                              {compareResult.differences.values_differ.length === 0 &&
                               compareResult.differences.keys_only_in_a.length === 0 &&
                               compareResult.differences.keys_only_in_b.length === 0 && (
                                <p className="text-emerald-600 dark:text-emerald-400">Content is identical</p>
                              )}
                            </dl>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                  <Tag className="w-12 h-12 mx-auto mb-3 opacity-50" />
                  <p>No derived metadata available yet.</p>
                  <p className="text-xs mt-1">Run experiments to generate metadata.</p>
                </div>
              )}

              {/* Legacy Extraction Metadata (collapsed) */}
              <details className="mt-6 bg-white dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700">
                <summary className="px-5 py-4 cursor-pointer text-sm font-semibold text-gray-900 dark:text-white hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors">
                  Extraction Metadata (Technical)
                </summary>
                <div className="px-5 pb-5 space-y-4">
                  {/* Extraction Info */}
                  {extraction && (
                    <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4">
                      <h4 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
                        <FileCode className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                        Extraction Information
                      </h4>
                      <dl className="grid grid-cols-2 gap-3 text-xs">
                        <div>
                          <dt className="text-gray-500 dark:text-gray-400 mb-0.5">Extractor Version</dt>
                          <dd className="font-mono text-gray-900 dark:text-white">{extraction.extractor_version}</dd>
                        </div>
                        {extraction.extraction_time_seconds && (
                          <div>
                            <dt className="text-gray-500 dark:text-gray-400 mb-0.5">Processing Time</dt>
                            <dd className="text-gray-900 dark:text-white">{extraction.extraction_time_seconds.toFixed(2)}s</dd>
                          </div>
                        )}
                      </dl>
                    </div>
                  )}

                  {/* Content Statistics */}
                  {extraction?.structure_metadata?.content_info && (
                    <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4">
                      <h4 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
                        <Tag className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                        Content Statistics
                      </h4>
                      <dl className="grid grid-cols-3 gap-3 text-xs">
                        {extraction.structure_metadata.content_info.character_count !== undefined && (
                          <div>
                            <dt className="text-gray-500 dark:text-gray-400 mb-0.5">Characters</dt>
                            <dd className="font-semibold text-gray-900 dark:text-white">
                              {extraction.structure_metadata.content_info.character_count.toLocaleString()}
                            </dd>
                          </div>
                        )}
                        {extraction.structure_metadata.content_info.word_count !== undefined && (
                          <div>
                            <dt className="text-gray-500 dark:text-gray-400 mb-0.5">Words</dt>
                            <dd className="font-semibold text-gray-900 dark:text-white">
                              {extraction.structure_metadata.content_info.word_count.toLocaleString()}
                            </dd>
                          </div>
                        )}
                        {extraction.structure_metadata.content_info.line_count !== undefined && (
                          <div>
                            <dt className="text-gray-500 dark:text-gray-400 mb-0.5">Lines</dt>
                            <dd className="font-semibold text-gray-900 dark:text-white">
                              {extraction.structure_metadata.content_info.line_count.toLocaleString()}
                            </dd>
                          </div>
                        )}
                      </dl>
                    </div>
                  )}

                  {/* Raw Metadata */}
                  {extraction?.structure_metadata && (
                    <div>
                      <h4 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">Raw Metadata</h4>
                      <pre className="bg-gray-50 dark:bg-gray-900/50 p-4 rounded-lg overflow-x-auto text-xs text-gray-700 dark:text-gray-300 max-h-64 overflow-y-auto">
                        {JSON.stringify(extraction.structure_metadata, null, 2)}
                      </pre>
                    </div>
                  )}

                  {/* Source Metadata */}
                  {asset.source_metadata && Object.keys(asset.source_metadata).length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">Source Metadata</h4>
                      <pre className="bg-gray-50 dark:bg-gray-900/50 p-4 rounded-lg overflow-x-auto text-xs text-gray-700 dark:text-gray-300 max-h-64 overflow-y-auto">
                        {JSON.stringify(asset.source_metadata, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              </details>
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
                              <div className="flex items-center gap-2 flex-wrap">
                                <p className="text-sm font-medium text-gray-900 dark:text-white capitalize">
                                  {run.run_type}
                                </p>
                                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 capitalize">
                                  {run.origin}
                                </span>
                                {/* Show extraction system/method if available */}
                                {run.config?.extraction_method && (
                                  <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300">
                                    {run.config.extraction_method}
                                  </span>
                                )}
                                {run.config?.extractor_version && (
                                  <span className="px-2 py-0.5 text-xs font-mono rounded-full bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300">
                                    {run.config.extractor_version}
                                  </span>
                                )}
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

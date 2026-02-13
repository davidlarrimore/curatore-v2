'use client'

/**
 * Organization-scoped asset detail page.
 */

import { useState, useEffect } from 'react'
import { useRouter, useParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { useOrgUrl } from '@/lib/org-url-context'
import { assetsApi, API_BASE_URL, API_PATH_VERSION, type Run, type AssetMetadataList, type AssetQueueInfo, type Asset, type ExtractionResult, type AssetVersion } from '@/lib/api'
import { ExtractionStatus, isActiveStatus } from '@/components/ui/ExtractionStatus'
import { POLLING } from '@/lib/polling-config'
import { formatDateTime } from '@/lib/date-utils'
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
  Trash2,
  ChevronRight,
  Search,
  Sparkles,
  FileCheck,
  ExternalLink,
  Copy,
  Check,
} from 'lucide-react'

type TabType = 'original' | 'extracted' | 'metadata' | 'history'

// Helper to format source type for display
const formatSourceType = (sourceType: string): string => {
  const sourceTypeLabels: Record<string, string> = {
    upload: 'Upload',
    sharepoint: 'SharePoint',
    web_scrape: 'Web Scrape',
    sam_gov: 'SAM.gov',
  }
  return sourceTypeLabels[sourceType] || sourceType.replace('_', ' ')
}

export default function AssetDetailPage() {
  const router = useRouter()
  const params = useParams()
  const { token } = useAuth()
  const { orgSlug } = useOrgUrl()
  const assetId = params?.id as string

  const orgUrl = (path: string) => `/orgs/${orgSlug}${path}`

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

  // Queue info for pending assets
  const [queueInfo, setQueueInfo] = useState<AssetQueueInfo | null>(null)

  // Track extraction ID to detect when extraction result changes
  const [lastExtractionId, setLastExtractionId] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [copiedFolderPath, setCopiedFolderPath] = useState(false)
  const [contentLoadProgress, setContentLoadProgress] = useState<number>(0)

  // State for rendering .docx files
  const [docxHtml, setDocxHtml] = useState<string>('')
  const [isLoadingDocx, setIsLoadingDocx] = useState(false)
  const [docxError, setDocxError] = useState<string>('')

  // Blob URL for inline previews (images, PDFs, HTML, text)
  const [previewBlobUrl, setPreviewBlobUrl] = useState<string | null>(null)

  // Check if any run is actively processing
  const hasActiveRuns = runs.some((run) =>
    ['pending', 'submitted', 'running', 'queued', 'processing'].includes(run.status)
  )

  // Load asset data
  useEffect(() => {
    if (token && assetId) {
      loadAssetData()
    }
  }, [token, assetId])

  // Auto-poll when asset is processing OR when there are active runs
  useEffect(() => {
    const shouldPoll = asset?.status === 'pending' || hasActiveRuns
    if (shouldPoll) {
      const intervalId = setInterval(() => {
        loadAssetData(true) // Silent polling - don't show loading spinner
      }, POLLING.ASSET_DETAIL_MS)

      return () => clearInterval(intervalId)
    }
  }, [asset?.status, hasActiveRuns])

  // Fetch queue info when asset is pending or has active runs
  useEffect(() => {
    const shouldFetchQueueInfo = (asset?.status === 'pending' || hasActiveRuns) && token && assetId
    if (shouldFetchQueueInfo) {
      // Initial fetch
      loadQueueInfo()

      // Poll queue info using the same interval as asset detail
      const queuePollInterval = setInterval(() => {
        loadQueueInfo()
      }, POLLING.ASSET_DETAIL_MS)

      return () => clearInterval(queuePollInterval)
    } else if (!hasActiveRuns) {
      setQueueInfo(null)
    }
  }, [asset?.status, hasActiveRuns, token, assetId])

  const loadQueueInfo = async () => {
    if (!token || !assetId) return
    try {
      const info = await assetsApi.getAssetQueueInfo(token, assetId)
      setQueueInfo(info)
    } catch {
      // Silently fail - queue info is supplementary
      // Don't log to avoid console spam during polling
      setQueueInfo(null)
    }
  }

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
    } catch (err: unknown) {
      if (!silent) {
        const message = err instanceof Error ? err.message : 'Failed to load asset'
        setError(message)
      }
    } finally {
      if (!silent) {
        setIsLoading(false)
      }
    }
  }

  // Load extracted content when tab is activated or extraction result changes
  useEffect(() => {
    if (activeTab === 'extracted' && extraction && !isLoadingContent) {
      // Reload content if extraction ID changed (new extraction completed)
      // or if we don't have content yet
      const extractionChanged = extraction.id !== lastExtractionId
      const extractionCompleted = extraction.status === 'completed'
      const needsContent = !extractedContent || extractionChanged

      if (needsContent && extractionCompleted) {
        setLastExtractionId(extraction.id)
        loadExtractedContent()
      } else if (needsContent && !extractionCompleted && extraction.extracted_object_key) {
        // Extraction has content available even if status isn't 'completed' yet
        setLastExtractionId(extraction.id)
        loadExtractedContent()
      }
    }
  }, [activeTab, extraction?.id, extraction?.status, extraction?.extracted_object_key])

  // Load and convert .docx file when Original tab is active
  useEffect(() => {
    const isDocx = asset?.content_type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ||
                   asset?.content_type === 'application/msword'

    if (activeTab === 'original' && asset && isDocx && !docxHtml && !isLoadingDocx) {
      loadDocxContent()
    }
  }, [activeTab, asset?.id, asset?.content_type])

  // Load blob URL for inline previews (images, PDFs, HTML, text)
  useEffect(() => {
    if (activeTab !== 'original' || !asset?.id || !token) return

    const needsPreview =
      asset.content_type?.startsWith('image/') ||
      asset.content_type === 'application/pdf' ||
      asset.content_type === 'text/html' ||
      asset.content_type === 'text/plain' ||
      asset.content_type === 'text/csv' ||
      asset.content_type === 'text/markdown'

    if (!needsPreview) return

    let revoked = false
    assetsApi.downloadOriginal(token, asset.id, true).then((blob) => {
      if (revoked) return
      const url = URL.createObjectURL(blob)
      setPreviewBlobUrl(url)
    }).catch((err) => {
      console.error('Failed to load preview:', err)
    })

    return () => {
      revoked = true
      setPreviewBlobUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev)
        return null
      })
    }
  }, [activeTab, asset?.id, asset?.content_type, token])

  const loadDocxContent = async () => {
    if (!asset?.id || !token) return

    setIsLoadingDocx(true)
    setDocxError('')
    try {
      const blob = await assetsApi.downloadOriginal(token, asset.id)
      const arrayBuffer = await blob.arrayBuffer()

      // Dynamically import mammoth to avoid SSR issues
      const mammoth = await import('mammoth')
      const result = await mammoth.convertToHtml({ arrayBuffer })

      setDocxHtml(result.value)
    } catch (err) {
      console.error('Error loading docx:', err)
      setDocxError(err instanceof Error ? err.message : 'Failed to render document')
    } finally {
      setIsLoadingDocx(false)
    }
  }

  const handleDownloadOriginal = async () => {
    if (!asset?.id || !token) return
    try {
      const blob = await assetsApi.downloadOriginal(token, asset.id)
      const blobUrl = URL.createObjectURL(blob)
      window.open(blobUrl, '_blank')
      // Revoke after a delay to allow the new tab to load
      setTimeout(() => URL.revokeObjectURL(blobUrl), 60000)
    } catch (err) {
      console.error('Download failed:', err)
    }
  }

  const loadExtractedContent = async () => {
    if (!asset?.id || !extraction?.extracted_object_key || !token) return

    setIsLoadingContent(true)
    setContentLoadProgress(0)
    try {
      // Download extracted markdown via the asset download endpoint
      const url = `${API_BASE_URL}/api/${API_PATH_VERSION}/data/assets/${asset.id}/download`

      const response = await fetch(url, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      })

      if (!response.ok) {
        throw new Error(`Failed to download content: ${response.statusText}`)
      }

      // Get content length for progress tracking
      const contentLength = response.headers.get('Content-Length')
      const totalBytes = contentLength ? parseInt(contentLength, 10) : 0

      if (totalBytes && response.body) {
        // Stream the response to track progress
        const reader = response.body.getReader()
        const chunks: Uint8Array[] = []
        let receivedBytes = 0

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          chunks.push(value)
          receivedBytes += value.length
          setContentLoadProgress(Math.round((receivedBytes / totalBytes) * 100))
        }

        // Combine chunks and decode as text
        const allChunks = new Uint8Array(receivedBytes)
        let position = 0
        for (const chunk of chunks) {
          allChunks.set(chunk, position)
          position += chunk.length
        }
        const content = new TextDecoder().decode(allChunks)
        setExtractedContent(content)
      } else {
        // Fallback if no content-length header (indeterminate progress)
        const content = await response.text()
        setExtractedContent(content)
      }
      setContentLoadProgress(100)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setExtractedContent(`# Error Loading Content\n\n${message}`)
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
    } catch (err: unknown) {
      console.error('Failed to load asset metadata:', err)
    } finally {
      setIsLoadingMetadata(false)
    }
  }

  const handleDeleteMetadata = async (metadataId: string) => {
    if (!token || !assetId) return

    if (!confirm('Are you sure you want to delete this metadata?')) {
      return
    }

    try {
      await assetsApi.deleteMetadata(token, assetId, metadataId)
      setSuccessMessage('Metadata deleted')
      await loadAssetMetadata()
      setTimeout(() => setSuccessMessage(''), 3000)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError(`Failed to delete metadata: ${message}`)
      setTimeout(() => setError(''), 5000)
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
    // Clear old extracted content so it doesn't show stale data
    setExtractedContent('')
    setLastExtractionId(null)
    try {
      const run = await assetsApi.reextractAsset(token, assetId)

      // Show success message
      setSuccessMessage(`Re-extraction started successfully (Run ID: ${run.id.substring(0, 8)}...)`)

      // Reload asset data immediately to show new run and start polling
      await loadAssetData()

      // Clear success message after a few seconds
      setTimeout(() => {
        setSuccessMessage('')
      }, 3000)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError(`Failed to trigger re-extraction: ${message}`)
    } finally {
      setIsReextracting(false)
    }
  }

  const handleBack = () => {
    router.push(orgUrl('/assets'))
  }

  // Get unified status for display - prefer queueInfo.unified_status if available
  const getDisplayStatus = (): string => {
    if (queueInfo?.unified_status) {
      return queueInfo.unified_status
    }
    // Fall back to asset status
    return asset?.status === 'ready' ? 'completed' : (asset?.status || 'queued')
  }

  const formatBytes = (bytes: number | null) => {
    if (!bytes) return 'Unknown'
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(1024))
    return `${(bytes / Math.pow(1024, i)).toFixed(2)} ${sizes[i]}`
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

  const displayStatus = getDisplayStatus()

  // Helper to get source metadata safely
  const getSourceMetadata = (key: string): unknown => {
    if (!asset.source_metadata) return undefined
    return (asset.source_metadata as Record<string, unknown>)[key]
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          {/* Breadcrumb navigation to storage folder */}
          <nav className="flex items-center space-x-1 text-sm mb-6 overflow-x-auto">
            <Link
              href={orgUrl(`/storage/${asset.raw_bucket}`)}
              className="flex items-center gap-1.5 px-2 py-1 rounded-md text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-900 dark:hover:text-gray-200 transition-colors whitespace-nowrap"
            >
              <FolderOpen className="w-3.5 h-3.5" />
              <span>Storage</span>
            </Link>
            {asset.raw_object_key.split('/').slice(0, -1).map((segment, index, arr) => (
              <span key={index} className="flex items-center">
                <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0 mx-1" />
                <Link
                  href={orgUrl(`/storage/${asset.raw_bucket}/${arr.slice(0, index + 1).join('/')}`)}
                  className="flex items-center gap-1.5 px-2 py-1 rounded-md text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-900 dark:hover:text-gray-200 transition-colors whitespace-nowrap"
                >
                  <FolderOpen className="w-3.5 h-3.5" />
                  <span className="truncate max-w-[150px]">{segment}</span>
                </Link>
              </span>
            ))}
            <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0 mx-1" />
            <span className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 font-medium whitespace-nowrap">
              <FileText className="w-3.5 h-3.5" />
              <span className="truncate max-w-[200px]">{asset.original_filename}</span>
            </span>
          </nav>

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
                  <ExtractionStatus
                    status={displayStatus}
                    queuePosition={queueInfo?.queue_position}
                    totalPending={queueInfo?.total_pending}
                    estimatedWaitSeconds={queueInfo?.estimated_wait_seconds}
                    extractorVersion={queueInfo?.extractor_version}
                    showPosition={displayStatus === 'queued'}
                    showTooltip
                  />
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
              {/* Re-extract button disabled when extraction is pending/submitted/running */}
              {(() => {
                // Check queueInfo for unified status
                const isQueueActive = queueInfo && ['queued', 'submitted', 'processing'].includes(queueInfo.unified_status)
                // Also check if any runs are actively processing
                const hasActiveExtractionRuns = runs.some((run) =>
                  run.run_type === 'extraction' &&
                  ['pending', 'submitted', 'running', 'queued', 'processing'].includes(run.status)
                )
                const isExtractionActive = isQueueActive || hasActiveExtractionRuns
                const canReextract = !isReextracting && !isExtractionActive && asset.status !== 'pending'

                let buttonText = 'Re-extract'
                if (isReextracting) {
                  buttonText = 'Starting...'
                } else if (queueInfo?.unified_status === 'queued') {
                  buttonText = queueInfo.queue_position ? `Queued (#${queueInfo.queue_position})` : 'Queued'
                } else if (queueInfo?.unified_status === 'submitted') {
                  buttonText = 'Starting...'
                } else if (queueInfo?.unified_status === 'processing') {
                  buttonText = 'Processing...'
                } else if (hasActiveExtractionRuns) {
                  buttonText = 'Processing...'
                } else if (asset.status === 'pending') {
                  buttonText = 'Queued'
                }

                return (
                  <Button
                    variant="secondary"
                    onClick={handleReextract}
                    disabled={!canReextract}
                    className="gap-2 whitespace-nowrap opacity-100 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <RefreshCw className={`w-4 h-4 ${!canReextract ? 'animate-spin' : ''}`} />
                    <span className="whitespace-nowrap">{buttonText}</span>
                  </Button>
                )
              })()}
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

          {/* Timeout Warning */}
          {queueInfo?.unified_status === 'timed_out' && (
            <div className="mt-6 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-100 dark:border-amber-900/50 p-4">
              <div className="flex items-center gap-3">
                <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
                  <Clock className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                </div>
                <div>
                  <p className="text-sm font-medium text-amber-800 dark:text-amber-200">Extraction timed out</p>
                  <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">
                    The file may be too large or complex. Try re-extracting or contact support if the issue persists.
                  </p>
                </div>
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
                  {asset.source_type === 'sharepoint' && getSourceMetadata('sync_config_id') ? (
                    <Link
                      href={orgUrl(`/syncs/sharepoint/${getSourceMetadata('sync_config_id')}`)}
                      className="text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 hover:underline"
                    >
                      SharePoint
                    </Link>
                  ) : (
                    <p className="text-sm font-medium text-gray-900 dark:text-white">{formatSourceType(asset.source_type)}</p>
                  )}
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
                  <p className="text-sm font-medium text-gray-900 dark:text-white">{formatDateTime(asset.created_at)}</p>
                </div>
              </div>
            </div>
          </div>

          {/* Pipeline Status */}
          <div className="mt-4">
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">Processing Pipeline</p>
            <div className="flex flex-wrap items-center gap-2">
              {/* Extraction Status with Engine Info */}
              {(() => {
                const isExtracted = extraction?.status === 'completed'
                const isExtracting = extraction?.status === 'running' || extraction?.status === 'pending'
                const triageEngine = extraction?.triage_engine
                const needsOcr = extraction?.triage_needs_ocr

                // Format engine name for display
                const formatEngineName = (engine: string | null | undefined): string => {
                  if (!engine) return 'basic'
                  const names: Record<string, string> = {
                    'fast_pdf': 'Fast PDF',
                    'fast_office': 'Fast Office',
                    'docling': 'Docling',
                    'ocr_only': 'OCR',
                  }
                  return names[engine] || engine
                }

                // Get color based on engine
                const getEngineColor = (engine: string | null | undefined) => {
                  if (!engine) return 'emerald'
                  if (engine === 'docling' || engine === 'ocr_only') return 'purple'
                  return 'emerald'
                }

                if (isExtracting) {
                  return (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      Extracting...
                    </span>
                  )
                }

                if (!isExtracted) {
                  return (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
                      <FileText className="w-3 h-3" />
                      Not Extracted
                    </span>
                  )
                }

                // Extracted - show engine info if available
                const engineColor = getEngineColor(triageEngine)
                const engineName = triageEngine ? formatEngineName(triageEngine) : (asset.extraction_tier || 'basic')
                const colorClasses = {
                  emerald: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300',
                  purple: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300',
                }

                return (
                  <>
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full ${colorClasses[engineColor]}`}>
                      <FileCheck className="w-3 h-3" />
                      {engineName}
                    </span>
                    {needsOcr && (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300">
                        <Eye className="w-3 h-3" />
                        OCR
                      </span>
                    )}
                    {extraction?.triage_complexity === 'high' && (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400">
                        Complex
                      </span>
                    )}
                  </>
                )
              })()}

              {/* Indexing Status */}
              {(() => {
                const isIndexed = asset.indexed_at !== null

                return isIndexed ? (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300" title={`Indexed: ${formatDateTime(asset.indexed_at!)}`}>
                    <Search className="w-3 h-3" />
                    Indexed
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
                    <Search className="w-3 h-3" />
                    Not Indexed
                  </span>
                )
              })()}
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
                  onClick={handleDownloadOriginal}
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
                    {previewBlobUrl ? (
                      <img
                        src={previewBlobUrl}
                        alt={asset.original_filename}
                        className="max-w-full h-auto"
                      />
                    ) : (
                      <div className="flex items-center justify-center p-12">
                        <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
                      </div>
                    )}
                  </div>
                ) : asset.content_type === 'application/pdf' ? (
                  <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden" style={{ height: '600px' }}>
                    {previewBlobUrl ? (
                      <iframe
                        src={previewBlobUrl}
                        className="w-full h-full"
                        title={asset.original_filename}
                      />
                    ) : (
                      <div className="flex items-center justify-center h-full">
                        <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
                      </div>
                    )}
                  </div>
                ) : asset.content_type === 'text/html' ? (
                  <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden" style={{ height: '600px' }}>
                    {previewBlobUrl ? (
                      <iframe
                        src={previewBlobUrl}
                        className="w-full h-full bg-white"
                        title={asset.original_filename}
                        sandbox="allow-same-origin"
                      />
                    ) : (
                      <div className="flex items-center justify-center h-full">
                        <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
                      </div>
                    )}
                  </div>
                ) : asset.content_type === 'text/plain' || asset.content_type === 'text/csv' || asset.content_type === 'text/markdown' ? (
                  <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden" style={{ height: '600px' }}>
                    {previewBlobUrl ? (
                      <iframe
                        src={previewBlobUrl}
                        className="w-full h-full bg-white dark:bg-gray-900"
                        title={asset.original_filename}
                      />
                    ) : (
                      <div className="flex items-center justify-center h-full">
                        <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
                      </div>
                    )}
                  </div>
                ) : asset.content_type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' || asset.content_type === 'application/msword' ? (
                  <div>
                    {isLoadingDocx ? (
                      <div className="flex items-center justify-center p-12">
                        <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
                        <span className="ml-3 text-gray-600 dark:text-gray-400">Loading document...</span>
                      </div>
                    ) : docxError ? (
                      <div className="p-8 text-center border-2 border-dashed border-red-200 dark:border-red-700 rounded-lg bg-red-50 dark:bg-red-900/10">
                        <AlertTriangle className="w-12 h-12 mx-auto mb-4 text-red-500" />
                        <p className="text-red-600 dark:text-red-400 mb-4">{docxError}</p>
                        <Button
                          variant="secondary"
                          onClick={handleDownloadOriginal}
                          className="gap-2"
                        >
                          <Download className="w-4 h-4" />
                          Download Instead
                        </Button>
                      </div>
                    ) : docxHtml ? (
                      <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                        <div className="bg-gray-50 dark:bg-gray-800 px-4 py-2 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
                          <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                            <FileText className="w-4 h-4" />
                            <span>{asset.original_filename}</span>
                          </div>
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={handleDownloadOriginal}
                            className="gap-1"
                          >
                            <Download className="w-3 h-3" />
                            Download
                          </Button>
                        </div>
                        <div
                          className="p-6 bg-white dark:bg-gray-900 prose dark:prose-invert max-w-none overflow-auto"
                          style={{ maxHeight: '600px' }}
                          dangerouslySetInnerHTML={{ __html: docxHtml }}
                        />
                      </div>
                    ) : (
                      <div className="p-8 text-center border-2 border-dashed border-gray-200 dark:border-gray-700 rounded-lg">
                        <FileText className="w-12 h-12 mx-auto mb-4 text-gray-400" />
                        <p className="text-gray-500 dark:text-gray-400">Loading document preview...</p>
                      </div>
                    )}
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
                        onClick={handleDownloadOriginal}
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
                        onClick={handleDownloadOriginal}
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
                      onClick={handleDownloadOriginal}
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
                  {asset.raw_object_key && asset.raw_object_key.split('/').length > 2 && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-gray-500 dark:text-gray-400">Folder Path</span>
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/50 px-2 py-0.5 rounded truncate max-w-[260px]">
                          {asset.raw_object_key.split('/').slice(1, -1).join('/')}
                        </span>
                        <button
                          onClick={() => {
                            const folderPath = asset.raw_object_key!.split('/').slice(1, -1).join('/')
                            navigator.clipboard.writeText(folderPath)
                            setCopiedFolderPath(true)
                            setTimeout(() => setCopiedFolderPath(false), 2000)
                          }}
                          className="p-1 rounded-md text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 transition-colors"
                          title="Copy folder path for use in procedures"
                        >
                          {copiedFolderPath ? (
                            <Check className="w-3.5 h-3.5 text-emerald-500" />
                          ) : (
                            <Copy className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </div>
                    </div>
                  )}
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
                <div className="flex items-center gap-3">
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Extracted Content</h3>
                  {extractedContent && (
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(extractedContent)
                        setCopied(true)
                        setTimeout(() => setCopied(false), 2000)
                      }}
                      className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:text-gray-300 dark:hover:bg-gray-700 transition-colors"
                      title="Copy to clipboard"
                    >
                      {copied ? (
                        <Check className="w-4 h-4 text-emerald-500" />
                      ) : (
                        <Copy className="w-4 h-4" />
                      )}
                    </button>
                  )}
                </div>
                {extraction && (
                  <ExtractionStatus status={extraction.status} />
                )}
              </div>
              {extraction ? (
                <div>
                  {/* Show loading/processing state */}
                  {isLoadingContent ? (
                    <div className="flex flex-col items-center justify-center py-8">
                      <div className="w-64 mb-3">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm text-gray-500 dark:text-gray-400">Loading content...</span>
                          <span className="text-sm font-medium text-indigo-600 dark:text-indigo-400">
                            {contentLoadProgress > 0 ? `${contentLoadProgress}%` : ''}
                          </span>
                        </div>
                        <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2 overflow-hidden">
                          {contentLoadProgress > 0 ? (
                            <div
                              className="bg-indigo-500 h-2 rounded-full transition-all duration-300 ease-out"
                              style={{ width: `${contentLoadProgress}%` }}
                            />
                          ) : (
                            <div className="bg-indigo-500 h-2 rounded-full w-full animate-pulse" />
                          )}
                        </div>
                      </div>
                    </div>
                  ) : extraction.status === 'pending' || extraction.status === 'running' ? (
                    <div className="flex flex-col items-center justify-center py-8 text-gray-500 dark:text-gray-400">
                      <Loader2 className="w-8 h-8 animate-spin text-indigo-500 mb-3" />
                      <p className="text-sm font-medium">Extraction in progress</p>
                      <p className="text-xs mt-1">Content will appear automatically when ready</p>
                    </div>
                  ) : !extraction.extracted_object_key ? (
                    <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                      <FileText className="w-12 h-12 mx-auto mb-3 opacity-50" />
                      <p>No extracted content available yet</p>
                    </div>
                  ) : (
                    <div className="prose dark:prose-invert max-w-none">
                      <pre className="bg-gray-50 dark:bg-gray-900/50 p-4 rounded-lg overflow-x-auto text-sm text-gray-900 dark:text-gray-100 whitespace-pre-wrap">
                        {extractedContent || 'No content available'}
                      </pre>
                    </div>
                  )}
                  {/* Show extraction metadata when available */}
                  {extraction.extraction_time_seconds !== null && (
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
                  )}
                </div>
              ) : asset.status === 'pending' || hasActiveRuns ? (
                <div className="flex flex-col items-center justify-center py-8 text-gray-500 dark:text-gray-400">
                  <Loader2 className="w-8 h-8 animate-spin text-indigo-500 mb-3" />
                  <p className="text-sm font-medium">Extraction in progress</p>
                  <p className="text-xs mt-1">Content will appear automatically when ready</p>
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

              {/* Asset Metadata */}
              {isLoadingMetadata ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
                  <span className="ml-2 text-sm text-gray-500 dark:text-gray-400">Loading metadata...</span>
                </div>
              ) : metadataList && metadataList.canonical.length > 0 ? (
                <div className="space-y-6">
                  {/* Metadata Section */}
                  <div className="bg-white dark:bg-gray-800/50 rounded-xl border border-emerald-200 dark:border-emerald-800 overflow-hidden">
                    <div className="px-5 py-4 bg-emerald-50 dark:bg-emerald-900/20 border-b border-emerald-200 dark:border-emerald-800">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Star className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                          <h4 className="text-sm font-semibold text-emerald-800 dark:text-emerald-200">
                            Metadata
                          </h4>
                          <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">
                            {metadataList.total_canonical}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="p-5">
                      <div className="space-y-4">
                        {metadataList.canonical.map((metadata) => (
                          <div key={metadata.id} className="p-4 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
                            <div className="flex items-start justify-between mb-3">
                              <div>
                                <div className="flex items-center gap-2">
                                  <span className="text-sm font-semibold text-gray-900 dark:text-white">
                                    {metadata.metadata_type}
                                  </span>
                                </div>
                                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                                  Schema v{metadata.schema_version} • Created {formatDateTime(metadata.created_at)}
                                </p>
                              </div>
                              <button
                                onClick={() => handleDeleteMetadata(metadata.id)}
                                className="p-1.5 rounded-lg text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                                title="Delete metadata"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                            <div className="bg-gray-50 dark:bg-gray-900/50 p-3 rounded-lg">
                              <pre className="text-xs text-gray-700 dark:text-gray-300 overflow-x-auto max-h-32 overflow-y-auto">
                                {JSON.stringify(metadata.metadata_content, null, 2)}
                              </pre>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                </div>
              ) : (
                <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                  <Tag className="w-12 h-12 mx-auto mb-3 opacity-50" />
                  <p>No metadata available yet.</p>
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
                  {asset.source_metadata && Object.keys(asset.source_metadata as Record<string, unknown>).length > 0 && (
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
                              {formatDateTime(version.created_at)}
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

                      {/* Extraction Info */}
                      {version.extraction_status && (
                        <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700">
                          <div className="flex items-center flex-wrap gap-2">
                            {/* Status Badge */}
                            <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ${
                              version.extraction_status === 'completed'
                                ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300'
                                : version.extraction_status === 'failed'
                                ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300'
                                : 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300'
                            }`}>
                              {version.extraction_status === 'completed' ? (
                                <CheckCircle className="w-3 h-3" />
                              ) : version.extraction_status === 'failed' ? (
                                <XCircle className="w-3 h-3" />
                              ) : (
                                <Loader2 className="w-3 h-3" />
                              )}
                              {version.extraction_status}
                            </span>

                            {/* Tier Badge */}
                            {version.extraction_tier && (
                              <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${
                                version.extraction_tier === 'enhanced'
                                  ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300'
                                  : 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                              }`}>
                                {version.extraction_tier}
                              </span>
                            )}

                            {/* Extractor Version */}
                            {version.extractor_version && (
                              <span className="px-2 py-0.5 text-xs font-mono rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400">
                                {version.extractor_version}
                              </span>
                            )}

                            {/* Extraction Time */}
                            {version.extraction_time_seconds != null && (
                              <span className="text-xs text-gray-500 dark:text-gray-400">
                                {version.extraction_time_seconds.toFixed(1)}s
                              </span>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                  <History className="w-12 h-12 mx-auto mb-3 opacity-50" />
                  <p>No version history available</p>
                </div>
              )}

              {/* Runs Timeline - shown regardless of versions */}
              {runs.length > 0 && (
                <div className={versions.length > 0 ? 'mt-8' : 'mt-4'}>
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
                            : run.status === 'pending'
                            ? 'bg-amber-100 dark:bg-amber-900/30'
                            : 'bg-blue-100 dark:bg-blue-900/30'
                        }`}>
                          {run.status === 'completed' ? (
                            <CheckCircle className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                          ) : run.status === 'failed' ? (
                            <XCircle className="w-4 h-4 text-red-600 dark:text-red-400" />
                          ) : run.status === 'pending' ? (
                            <Clock className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                          ) : (
                            <Loader2 className="w-4 h-4 text-blue-600 dark:text-blue-400 animate-spin" />
                          )}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <p className="text-sm font-medium text-gray-900 dark:text-white">
                              {run.run_type === 'extraction'
                                ? 'Extraction'
                                : run.run_type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                            </p>
                            <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 capitalize">
                              {run.origin}
                            </span>
                            {/* Queue position badge for pending runs */}
                            {run.status === 'pending' && run.queue_position != null && (
                              <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300">
                                Queue #{run.queue_position}
                                {run.queue_priority && run.queue_priority > 0 && ' (Priority)'}
                              </span>
                            )}
                            {(run.config as Record<string, unknown>)?.extractor_version && (
                              <span className="px-2 py-0.5 text-xs font-mono rounded-full bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300">
                                {String((run.config as Record<string, unknown>).extractor_version)}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-4 mt-1 text-xs text-gray-500 dark:text-gray-400">
                            {run.status === 'pending' && !run.started_at && (
                              <span>Queued: {formatDateTime(run.created_at)}</span>
                            )}
                            {run.started_at && (
                              <span>Started: {formatDateTime(run.started_at)}</span>
                            )}
                            {run.completed_at && (
                              <span>Completed: {formatDateTime(run.completed_at)}</span>
                            )}
                          </div>
                          {run.results_summary && (
                            <div className="mt-2 text-xs text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-900/50 rounded p-2">
                              {(run.results_summary as Record<string, unknown>).status && (
                                <span className="font-medium">{String((run.results_summary as Record<string, unknown>).status)}</span>
                              )}
                              {(run.results_summary as Record<string, unknown>).improvement_percent !== undefined && (
                                <span className="ml-2">
                                  {Number((run.results_summary as Record<string, unknown>).improvement_percent) > 0
                                    ? `+${Number((run.results_summary as Record<string, unknown>).improvement_percent).toFixed(1)}% improvement`
                                    : 'No improvement'}
                                </span>
                              )}
                            </div>
                          )}
                          {run.error_message && (
                            <div className="mt-2 text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded p-2">
                              {run.error_message}
                            </div>
                          )}
                        </div>
                        {/* Action buttons */}
                        <div className="flex-shrink-0 flex items-center gap-2">
                          {/* View Job Link */}
                          <Link
                            href={orgUrl(`/jobs/${run.id}`)}
                            className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-200 dark:hover:bg-indigo-900/50 transition-colors"
                          >
                            <ExternalLink className="w-3 h-3" />
                            View Job
                          </Link>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

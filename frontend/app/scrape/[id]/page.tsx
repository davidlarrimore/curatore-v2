'use client'

import { useState, useEffect, use, useCallback, useRef } from 'react'
import { useAuth } from '@/lib/auth-context'
import { scrapeApi, ScrapeCollection, ScrapedAsset, ScrapeSource, PathTreeNode, CrawlStatus } from '@/lib/api'
import Link from 'next/link'
import {
  Globe,
  ArrowLeft,
  RefreshCw,
  Loader2,
  AlertTriangle,
  Play,
  Pause,
  Archive,
  ExternalLink,
  FileText,
  FolderOpen,
  ChevronRight,
  ArrowUpCircle,
  Clock,
  Star,
  Plus,
  Settings,
  Trash2,
  CheckCircle,
  XCircle,
  Info,
} from 'lucide-react'

interface PageProps {
  params: Promise<{ id: string }>
}

// Toast notification type
interface Toast {
  id: string
  type: 'success' | 'error' | 'info' | 'warning'
  message: string
}

// Add Source Form Component
function AddSourceForm({
  token,
  collectionId,
  onSourceAdded,
  onError,
  compact = false,
}: {
  token: string | null | undefined
  collectionId: string
  onSourceAdded: () => void
  onError: (message: string) => void
  compact?: boolean
}) {
  const [newSourceUrl, setNewSourceUrl] = useState('')
  const [addingSource, setAddingSource] = useState(false)
  const [showForm, setShowForm] = useState(!compact)

  async function handleAddSource(e: React.FormEvent) {
    e.preventDefault()
    if (!token || !newSourceUrl.trim()) return
    const authToken = token // TypeScript now knows this is string

    setAddingSource(true)
    try {
      await scrapeApi.addSource(token, collectionId, newSourceUrl.trim())
      setNewSourceUrl('')
      if (compact) setShowForm(false)
      onSourceAdded()
    } catch (err: any) {
      onError(err.message || 'Failed to add source')
    } finally {
      setAddingSource(false)
    }
  }

  if (compact && !showForm) {
    return (
      <button
        onClick={() => setShowForm(true)}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-gradient-to-r from-indigo-500 to-purple-600 rounded-lg hover:from-indigo-600 hover:to-purple-700 shadow-lg shadow-indigo-500/25 transition-all"
      >
        <Plus className="w-4 h-4" />
        Add Source URL
      </button>
    )
  }

  return (
    <form onSubmit={handleAddSource} className={compact ? 'inline-flex items-center gap-2' : 'flex items-center gap-3 max-w-xl mx-auto'}>
      <div className="flex-1">
        <input
          type="url"
          value={newSourceUrl}
          onChange={(e) => setNewSourceUrl(e.target.value)}
          placeholder="https://example.com/docs"
          className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
          required
        />
      </div>
      <button
        type="submit"
        disabled={addingSource || !newSourceUrl.trim()}
        className="inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-white bg-gradient-to-r from-indigo-500 to-purple-600 rounded-lg hover:from-indigo-600 hover:to-purple-700 disabled:opacity-50 shadow-lg shadow-indigo-500/25 transition-all"
      >
        {addingSource ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Plus className="w-4 h-4" />
        )}
        Add
      </button>
      {compact && (
        <button
          type="button"
          onClick={() => setShowForm(false)}
          className="p-2.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
        >
          ×
        </button>
      )}
    </form>
  )
}

export default function ScrapeCollectionDetailPage({ params }: PageProps) {
  const resolvedParams = use(params)
  const collectionId = resolvedParams.id
  const { token, user } = useAuth()

  const [collection, setCollection] = useState<ScrapeCollection | null>(null)
  const [sources, setSources] = useState<ScrapeSource[]>([])
  const [assets, setAssets] = useState<ScrapedAsset[]>([])
  const [pathTree, setPathTree] = useState<PathTreeNode[]>([])
  const [currentPath, setCurrentPath] = useState('/')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'assets' | 'tree' | 'sources'>('assets')
  const [assetFilter, setAssetFilter] = useState<'all' | 'page' | 'record'>('all')
  const [crawling, setCrawling] = useState(false)
  const [crawlStatus, setCrawlStatus] = useState<CrawlStatus | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)

  const isAdmin = user?.role === 'org_admin' || user?.role === 'admin'

  // Toast helper functions
  const addToast = useCallback((type: Toast['type'], message: string) => {
    const id = Date.now().toString()
    setToasts(prev => [...prev, { id, type, message }])
    // Auto-remove after 5 seconds
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, 5000)
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

  useEffect(() => {
    if (token && collectionId) {
      loadCollection()
    }
  }, [token, collectionId])

  // Check for ongoing crawl when collection loads
  useEffect(() => {
    if (collection?.last_crawl_run_id && token) {
      checkCrawlStatus()
    }
  }, [collection?.last_crawl_run_id, token])

  async function loadCollection() {
    if (!token) return
    setLoading(true)
    setError(null)

    try {
      const [col, srcResult, assetResult] = await Promise.all([
        scrapeApi.getCollection(token, collectionId),
        scrapeApi.listSources(token, collectionId),
        scrapeApi.listScrapedAssets(token, collectionId, { limit: 50 }),
      ])
      setCollection(col)
      setSources(srcResult.sources)
      setAssets(assetResult.assets)

      // Load path tree
      try {
        const tree = await scrapeApi.getPathTree(token, collectionId, '/')
        setPathTree(tree.nodes)
      } catch {
        // Tree might be empty
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load collection')
    } finally {
      setLoading(false)
    }
  }

  async function checkCrawlStatus() {
    if (!token) return
    try {
      const status = await scrapeApi.getCrawlStatus(token, collectionId)
      setCrawlStatus(status)

      // If crawl is running, start polling
      if (status.status === 'pending' || status.status === 'running') {
        setCrawling(true)
        startPolling()
      } else {
        setCrawling(false)
        stopPolling()
      }
    } catch {
      // No crawl status available - ensure crawling is also reset
      setCrawlStatus(null)
      setCrawling(false)
      stopPolling()
    }
  }

  function startPolling() {
    // Clear any existing polling
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
    }

    // Poll every 3 seconds
    pollIntervalRef.current = setInterval(async () => {
      if (!token) return
      try {
        const status = await scrapeApi.getCrawlStatus(token, collectionId)
        setCrawlStatus(status)

        // Check if crawl completed
        if (status.status === 'completed' || status.status === 'failed') {
          setCrawling(false)
          stopPolling()

          // Refresh data
          loadCollection()

          // Show completion toast
          if (status.status === 'completed') {
            const summary = status.results_summary as any
            const pagesNew = summary?.pages_new || 0
            const pagesUpdated = summary?.pages_updated || 0
            addToast('success', `Crawl complete! ${pagesNew} new pages, ${pagesUpdated} updated.`)
          } else {
            addToast('error', `Crawl failed: ${status.error_message || 'Unknown error'}`)
          }
        }
      } catch (err) {
        console.error('Failed to poll crawl status:', err)
      }
    }, 3000)
  }

  function stopPolling() {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
  }

  async function handleStartCrawl() {
    if (!token || !collection) return

    // Check if there are sources
    if (sources.length === 0) {
      addToast('warning', 'No URL sources configured. Add a source URL first.')
      return
    }

    setCrawling(true)
    setError(null)

    try {
      const result = await scrapeApi.startCrawl(token, collectionId)
      addToast('info', 'Crawl started! Fetching pages from source URLs...')

      // Set initial crawl status
      setCrawlStatus({
        run_id: result.run_id,
        status: 'running',
        progress: { current: 0, total: 0, unit: 'pages' },
        results_summary: null,
        error_message: null,
      })

      // Start polling for status updates
      startPolling()

      // Refresh collection to update last_crawl metadata
      setTimeout(() => {
        scrapeApi.getCollection(token, collectionId).then(col => {
          setCollection(col)
        }).catch(() => {})
      }, 1000)
    } catch (err: any) {
      setCrawling(false)
      const errorMsg = err.message || 'Failed to start crawl'
      setError(errorMsg)
      addToast('error', errorMsg)
    }
  }

  async function handlePromoteToRecord(scrapedAssetId: string) {
    if (!token) return
    try {
      await scrapeApi.promoteToRecord(token, collectionId, scrapedAssetId)
      loadCollection()
    } catch (err: any) {
      setError(err.message || 'Failed to promote to record')
    }
  }

  async function handleNavigatePath(path: string) {
    if (!token) return
    setCurrentPath(path)
    try {
      const tree = await scrapeApi.getPathTree(token, collectionId, path)
      setPathTree(tree.nodes)
    } catch {
      setPathTree([])
    }
  }

  async function handleFilterAssets(filter: 'all' | 'page' | 'record') {
    if (!token) return
    setAssetFilter(filter)
    try {
      const params: any = { limit: 50 }
      if (filter !== 'all') params.asset_subtype = filter
      const result = await scrapeApi.listScrapedAssets(token, collectionId, params)
      setAssets(result.assets)
    } catch (err: any) {
      setError(err.message)
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active':
        return 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400'
      case 'paused':
        return 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400'
      case 'archived':
        return 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400'
      default:
        return 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'active':
        return <Play className="w-3 h-3" />
      case 'paused':
        return <Pause className="w-3 h-3" />
      case 'archived':
        return <Archive className="w-3 h-3" />
      default:
        return null
    }
  }

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'Never'
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950 flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin mx-auto"></div>
          <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading collection...</p>
        </div>
      </div>
    )
  }

  if (!collection) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950 flex items-center justify-center">
        <div className="text-center">
          <AlertTriangle className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Collection Not Found</h2>
          <p className="text-gray-500 dark:text-gray-400 mb-4">The collection you're looking for doesn't exist.</p>
          <Link
            href="/scrape"
            className="inline-flex items-center gap-2 text-indigo-600 dark:text-indigo-400 hover:underline"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Collections
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Back Link */}
        <Link
          href="/scrape"
          className="inline-flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Collections
        </Link>

        {/* Page Header */}
        <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-4 mb-8">
          <div className="flex items-start gap-4">
            <div className="flex items-center justify-center w-14 h-14 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25">
              <Globe className="w-7 h-7" />
            </div>
            <div>
              <div className="flex items-center gap-3 mb-1">
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  {collection.name}
                </h1>
                <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${getStatusColor(collection.status)}`}>
                  {getStatusIcon(collection.status)}
                  <span className="capitalize">{collection.status}</span>
                </div>
              </div>
              <a
                href={collection.root_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400"
              >
                {collection.root_url}
                <ExternalLink className="w-3 h-3" />
              </a>
              {collection.description && (
                <p className="text-sm text-gray-600 dark:text-gray-300 mt-2 max-w-2xl">
                  {collection.description}
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={loadCollection}
              disabled={loading}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>

            {collection.status === 'active' && (
              <button
                onClick={handleStartCrawl}
                disabled={crawling || sources.length === 0}
                title={sources.length === 0 ? 'Add a URL source first' : crawling ? 'Crawl in progress...' : 'Start crawling source URLs'}
                className={`inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white rounded-lg shadow-lg transition-all ${
                  crawling
                    ? 'bg-gradient-to-r from-indigo-400 to-purple-500 cursor-not-allowed'
                    : sources.length === 0
                    ? 'bg-gray-400 cursor-not-allowed opacity-60'
                    : 'bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 shadow-indigo-500/25'
                }`}
              >
                {crawling ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Crawling...
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4" />
                    Start Crawl
                  </>
                )}
              </button>
            )}
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
                <FileText className="w-5 h-5 text-blue-600 dark:text-blue-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {collection.stats?.page_count || 0}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Pages</p>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-indigo-50 dark:bg-indigo-900/20 flex items-center justify-center">
                <Star className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {collection.stats?.record_count || 0}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Records</p>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center">
                <Globe className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {sources.length}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Sources</p>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gray-100 dark:bg-gray-700 flex items-center justify-center">
                <Clock className="w-5 h-5 text-gray-600 dark:text-gray-400" />
              </div>
              <div>
                <p className="text-sm font-medium text-gray-900 dark:text-white">
                  {formatDate(collection.last_crawl_at)}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Last Crawl</p>
              </div>
            </div>
          </div>
        </div>

        {/* Toast Notifications */}
        <div className="fixed top-4 right-4 z-50 space-y-2">
          {toasts.map((toast) => (
            <div
              key={toast.id}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg border transition-all animate-slide-in ${
                toast.type === 'success'
                  ? 'bg-emerald-50 dark:bg-emerald-900/90 border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-200'
                  : toast.type === 'error'
                  ? 'bg-red-50 dark:bg-red-900/90 border-red-200 dark:border-red-800 text-red-800 dark:text-red-200'
                  : toast.type === 'warning'
                  ? 'bg-amber-50 dark:bg-amber-900/90 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200'
                  : 'bg-blue-50 dark:bg-blue-900/90 border-blue-200 dark:border-blue-800 text-blue-800 dark:text-blue-200'
              }`}
            >
              {toast.type === 'success' && <CheckCircle className="w-5 h-5 flex-shrink-0" />}
              {toast.type === 'error' && <XCircle className="w-5 h-5 flex-shrink-0" />}
              {toast.type === 'warning' && <AlertTriangle className="w-5 h-5 flex-shrink-0" />}
              {toast.type === 'info' && <Info className="w-5 h-5 flex-shrink-0" />}
              <p className="text-sm font-medium">{toast.message}</p>
              <button
                onClick={() => removeToast(toast.id)}
                className="ml-2 text-current opacity-60 hover:opacity-100"
              >
                ×
              </button>
            </div>
          ))}
        </div>

        {/* Error */}
        {error && (
          <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
            <div className="flex items-center gap-3">
              <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
              <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
            </div>
          </div>
        )}

        {/* No Sources Warning */}
        {!loading && sources.length === 0 && collection?.status === 'active' && (
          <div className="mb-6 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-amber-100 dark:bg-amber-900/50 flex items-center justify-center">
                <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400" />
              </div>
              <div className="flex-1">
                <p className="font-medium text-amber-900 dark:text-amber-100">
                  No URL Sources Configured
                </p>
                <p className="text-sm text-amber-700 dark:text-amber-300">
                  Add a seed URL in the Sources tab to start crawling pages.
                </p>
              </div>
              <button
                onClick={() => setActiveTab('sources')}
                className="px-4 py-2 text-sm font-medium text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-900/50 hover:bg-amber-200 dark:hover:bg-amber-900/70 rounded-lg transition-colors"
              >
                Add Source
              </button>
            </div>
          </div>
        )}

        {/* Crawl Status Banner */}
        {crawling && (
          <div className="mb-6 rounded-xl bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 border border-indigo-200 dark:border-indigo-800 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="relative">
                  <div className="w-10 h-10 rounded-full bg-indigo-100 dark:bg-indigo-900/50 flex items-center justify-center">
                    <Loader2 className="w-5 h-5 text-indigo-600 dark:text-indigo-400 animate-spin" />
                  </div>
                  <span className="absolute -top-1 -right-1 flex h-3 w-3">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-3 w-3 bg-indigo-500"></span>
                  </span>
                </div>
                <div>
                  <p className="font-medium text-indigo-900 dark:text-indigo-100">
                    Crawl in Progress
                  </p>
                  <p className="text-sm text-indigo-700 dark:text-indigo-300">
                    {crawlStatus?.progress?.current || 0} of {crawlStatus?.progress?.total || '?'} {crawlStatus?.progress?.unit || 'pages'} processed
                  </p>
                </div>
              </div>
              <div className="text-right">
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300">
                  <span className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse"></span>
                  {crawlStatus?.status === 'pending' ? 'Starting...' : 'Running'}
                </span>
              </div>
            </div>
            {crawlStatus?.progress?.total && crawlStatus.progress.total > 0 && (
              <div className="mt-3">
                <div className="w-full bg-indigo-100 dark:bg-indigo-900/50 rounded-full h-2">
                  <div
                    className="bg-gradient-to-r from-indigo-500 to-purple-500 h-2 rounded-full transition-all duration-500"
                    style={{ width: `${Math.min(100, (crawlStatus.progress.current / crawlStatus.progress.total) * 100)}%` }}
                  ></div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tabs */}
        <div className="border-b border-gray-200 dark:border-gray-700 mb-6">
          <nav className="flex gap-6">
            {(['assets', 'tree', 'sources'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === tab
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
                }`}
              >
                {tab === 'assets' && 'Scraped Assets'}
                {tab === 'tree' && 'Path Browser'}
                {tab === 'sources' && 'URL Sources'}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab Content */}
        {activeTab === 'assets' && (
          <div className="space-y-4">
            {/* Filter */}
            <div className="flex items-center gap-2 mb-4">
              <span className="text-sm text-gray-500 dark:text-gray-400">Filter:</span>
              {(['all', 'page', 'record'] as const).map((filter) => (
                <button
                  key={filter}
                  onClick={() => handleFilterAssets(filter)}
                  className={`px-3 py-1 text-sm rounded-full transition-colors ${
                    assetFilter === filter
                      ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400'
                      : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
                  }`}
                >
                  {filter === 'all' ? 'All' : filter === 'page' ? 'Pages' : 'Records'}
                </button>
              ))}
            </div>

            {/* Assets List */}
            {assets.length === 0 ? (
              <div className="text-center py-12 text-gray-500 dark:text-gray-400">
                <FileText className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>No scraped assets yet. Start a crawl to begin capturing content.</p>
              </div>
            ) : (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-200 dark:border-gray-700">
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        URL
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Type
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Depth
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Created
                      </th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                    {assets.map((asset) => (
                      <tr key={asset.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                        <td className="px-4 py-3">
                          <a
                            href={asset.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1"
                          >
                            <span className="truncate max-w-md">{asset.url_path || asset.url}</span>
                            <ExternalLink className="w-3 h-3 flex-shrink-0" />
                          </a>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${
                            asset.asset_subtype === 'record'
                              ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400'
                              : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400'
                          }`}>
                            {asset.asset_subtype === 'record' ? (
                              <Star className="w-3 h-3" />
                            ) : (
                              <FileText className="w-3 h-3" />
                            )}
                            {asset.asset_subtype}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                          {asset.crawl_depth}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                          {formatDate(asset.created_at)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {asset.asset_subtype === 'page' && (
                            <button
                              onClick={() => handlePromoteToRecord(asset.id)}
                              className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded transition-colors"
                              title="Promote to Record"
                            >
                              <ArrowUpCircle className="w-4 h-4" />
                              Promote
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {activeTab === 'tree' && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
            {/* Breadcrumb */}
            <div className="flex items-center gap-2 mb-4 text-sm">
              <button
                onClick={() => handleNavigatePath('/')}
                className="text-indigo-600 dark:text-indigo-400 hover:underline"
              >
                Root
              </button>
              {currentPath !== '/' && currentPath.split('/').filter(Boolean).map((part, idx, arr) => (
                <span key={idx} className="flex items-center gap-2">
                  <ChevronRight className="w-4 h-4 text-gray-400" />
                  <button
                    onClick={() => handleNavigatePath('/' + arr.slice(0, idx + 1).join('/') + '/')}
                    className="text-indigo-600 dark:text-indigo-400 hover:underline"
                  >
                    {part}
                  </button>
                </span>
              ))}
            </div>

            {/* Tree Nodes */}
            {pathTree.length === 0 ? (
              <div className="text-center py-12 text-gray-500 dark:text-gray-400">
                <FolderOpen className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>No paths at this level. Try navigating to a different path or start a crawl.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {pathTree.map((node) => (
                  <button
                    key={node.path}
                    onClick={() => node.has_children && handleNavigatePath(node.path)}
                    className={`w-full flex items-center justify-between p-3 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors ${
                      node.has_children ? 'cursor-pointer' : 'cursor-default'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <FolderOpen className="w-5 h-5 text-indigo-500" />
                      <span className="font-medium text-gray-900 dark:text-white">{node.name}</span>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="text-sm text-gray-500 dark:text-gray-400">
                        {node.page_count} pages, {node.record_count} records
                      </span>
                      {node.has_children && (
                        <ChevronRight className="w-4 h-4 text-gray-400" />
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'sources' && (
          <div className="space-y-4">
            {sources.length === 0 ? (
              <div className="relative overflow-hidden rounded-2xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/50 px-6 py-12 text-center">
                {/* Background decoration */}
                <div className="absolute inset-0 pointer-events-none">
                  <div className="absolute -top-24 -right-24 w-64 h-64 rounded-full bg-gradient-to-br from-indigo-500/5 to-purple-500/5 blur-3xl"></div>
                  <div className="absolute -bottom-24 -left-24 w-64 h-64 rounded-full bg-gradient-to-br from-blue-500/5 to-cyan-500/5 blur-3xl"></div>
                </div>
                <div className="relative">
                  <div className="mx-auto w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-xl shadow-indigo-500/25 mb-4">
                    <Globe className="w-8 h-8 text-white" />
                  </div>
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                    No URL Sources Configured
                  </h3>
                  <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto mb-6">
                    Add a seed URL to start crawling. The crawler will discover and capture pages starting from this URL.
                  </p>
                  {isAdmin && (
                    <AddSourceForm
                      token={token}
                      collectionId={collectionId}
                      onSourceAdded={() => {
                        loadCollection()
                        addToast('success', 'Source URL added successfully!')
                      }}
                      onError={(err) => addToast('error', err)}
                    />
                  )}
                </div>
              </div>
            ) : (
              <>
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-gray-200 dark:border-gray-700">
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                          URL
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                          Type
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                          Status
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                          Pages Discovered
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                      {sources.map((source) => (
                        <tr key={source.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                          <td className="px-4 py-3">
                            <a
                              href={source.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1"
                            >
                              <span className="truncate max-w-md">{source.url}</span>
                              <ExternalLink className="w-3 h-3 flex-shrink-0" />
                            </a>
                          </td>
                          <td className="px-4 py-3">
                            <span className="text-sm text-gray-600 dark:text-gray-400 capitalize">
                              {source.source_type}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${
                              source.is_active
                                ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
                                : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400'
                            }`}>
                              {source.is_active ? 'Active' : 'Inactive'}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                            {source.discovered_pages}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Add Source Form (compact mode) */}
                {isAdmin && (
                  <div className="mt-4">
                    <AddSourceForm
                      token={token}
                      collectionId={collectionId}
                      onSourceAdded={() => {
                        loadCollection()
                        addToast('success', 'Source URL added successfully!')
                      }}
                      onError={(err) => addToast('error', err)}
                      compact
                    />
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

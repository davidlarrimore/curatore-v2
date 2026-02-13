'use client'

/**
 * Organization-scoped web scrape collection detail page.
 */

import { useState, useEffect, use, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { useOrgUrl } from '@/lib/org-url-context'
import { useDeletionJobs, useActiveJobs } from '@/lib/context-shims'
import { useJobProgress } from '@/lib/useJobProgress'
import { JobProgressPanel } from '@/components/ui/JobProgressPanel'
import { scrapeApi, ScrapeCollection, ScrapedAsset, PathTreeNode } from '@/lib/api'
import { formatCompact } from '@/lib/date-utils'
import Link from 'next/link'
import toast from 'react-hot-toast'
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
  Clock,
  CheckCircle,
  XCircle,
  Info,
  Eye,
  X,
  Copy,
  Check,
  Download,
  FileDown,
  Trash2,
} from 'lucide-react'

interface PageProps {
  params: Promise<{ id: string }>
}

// Toast notification type
interface ToastNotification {
  id: string
  type: 'success' | 'error' | 'info' | 'warning'
  message: string
}

export default function ScrapeCollectionDetailPage({ params }: PageProps) {
  const resolvedParams = use(params)
  const collectionId = resolvedParams.id
  const router = useRouter()
  const { token, user } = useAuth()
  const { orgSlug } = useOrgUrl()
  const { addJob: addDeletionJob, isDeleting } = useDeletionJobs()
  const { addJob } = useActiveJobs()
  const { isActive: isCrawlActive } = useJobProgress('scrape_collection', collectionId, {
    onComplete: () => loadCollection(),
  })

  const [collection, setCollection] = useState<ScrapeCollection | null>(null)
  const [assets, setAssets] = useState<ScrapedAsset[]>([])
  const [pathTree, setPathTree] = useState<PathTreeNode[]>([])
  const [currentPath, setCurrentPath] = useState('/')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'assets' | 'tree'>('assets')
  const [assetFilter, setAssetFilter] = useState<'all' | 'page' | 'record'>('all')
  const [toasts, setToasts] = useState<ToastNotification[]>([])
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [deleting, setDeleting] = useState(false)

  // Content viewer state
  const [contentViewerOpen, setContentViewerOpen] = useState(false)
  const [contentViewerAsset, setContentViewerAsset] = useState<ScrapedAsset | null>(null)
  const [contentViewerContent, setContentViewerContent] = useState<string | null>(null)
  const [contentViewerLoading, setContentViewerLoading] = useState(false)
  const [contentCopied, setContentCopied] = useState(false)

  const isAdmin = user?.role === 'org_admin' || user?.role === 'admin'

  // Helper to build org-scoped URLs
  const orgUrl = (path: string) => `/orgs/${orgSlug}${path}`

  // Toast helper functions
  const addToast = useCallback((type: ToastNotification['type'], message: string) => {
    const id = Date.now().toString()
    setToasts(prev => [...prev, { id, type, message }])
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, 5000)
  }, [])

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  useEffect(() => {
    if (token && collectionId) {
      loadCollection()
    }
  }, [token, collectionId])

  async function loadCollection() {
    if (!token) return
    setLoading(true)
    setError(null)

    try {
      const [col, assetResult] = await Promise.all([
        scrapeApi.getCollection(token, collectionId),
        scrapeApi.listScrapedAssets(token, collectionId, { limit: 50 }),
      ])
      setCollection(col)
      setAssets(assetResult.assets)

      // Load path tree
      try {
        const tree = await scrapeApi.getPathTree(token, collectionId, '/')
        setPathTree(tree.nodes)
      } catch {
        // Tree might be empty
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load collection'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  async function handleStartCrawl() {
    if (!token || !collection) return
    setError(null)

    try {
      const result = await scrapeApi.startCrawl(token, collectionId)
      addToast('info', 'Crawl started! Fetching pages...')

      if (result.run_id) {
        addJob({
          runId: result.run_id,
          jobType: 'scrape',
          displayName: collection.name || 'Web Scrape',
          resourceId: collectionId,
          resourceType: 'scrape_collection',
        })
      }
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to start crawl'
      setError(errorMsg)
      addToast('error', errorMsg)
    }
  }

  async function handleDelete() {
    if (!token || !collection) return

    setDeleting(true)
    try {
      const result = await scrapeApi.deleteCollection(token, collectionId)

      // Add to global deletion tracking
      addDeletionJob({
        runId: result.run_id,
        configId: collectionId,
        configName: collection.name,
        configType: 'scrape',
      })

      toast.success('Deletion started...')
      router.push(orgUrl('/syncs/scrape'))
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to delete collection'
      toast.error(errorMsg)
      setDeleting(false)
    }
  }

  // Redirect if collection is being deleted
  useEffect(() => {
    if (collection?.status === 'deleting' || isDeleting(collectionId)) {
      router.push(orgUrl('/syncs/scrape'))
    }
  }, [collection?.status, collectionId, isDeleting, router, orgSlug])

  async function handleViewContent(asset: ScrapedAsset) {
    if (!token) return
    setContentViewerAsset(asset)
    setContentViewerOpen(true)
    setContentViewerLoading(true)
    setContentViewerContent(null)
    setContentCopied(false)

    try {
      const content = await scrapeApi.getScrapedAssetContent(token, collectionId, asset.id)
      setContentViewerContent(content)
    } catch (err: unknown) {
      const errMessage = err instanceof Error ? err.message : 'Failed to load content'
      addToast('error', errMessage)
      setContentViewerContent(null)
    } finally {
      setContentViewerLoading(false)
    }
  }

  async function handleCopyContent() {
    if (!contentViewerContent) return
    try {
      await navigator.clipboard.writeText(contentViewerContent)
      setContentCopied(true)
      setTimeout(() => setContentCopied(false), 2000)
    } catch {
      addToast('error', 'Failed to copy to clipboard')
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
      const params: { limit: number; asset_subtype?: 'page' | 'record' } = { limit: 50 }
      if (filter !== 'all') params.asset_subtype = filter
      const result = await scrapeApi.listScrapedAssets(token, collectionId, params)
      setAssets(result.assets)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to filter assets'
      setError(message)
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

  // Use formatCompact from date-utils for consistent EST display
  const formatDate = (dateStr: string | null) => dateStr ? formatCompact(dateStr) : 'Never'

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950 flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-8 h-8 text-emerald-500 animate-spin mx-auto" />
          <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading...</p>
        </div>
      </div>
    )
  }

  if (!collection) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950 flex items-center justify-center">
        <div className="text-center">
          <AlertTriangle className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Not Found</h2>
          <p className="text-gray-500 dark:text-gray-400 mb-4">This website configuration doesn't exist.</p>
          <Link
            href={orgUrl('/syncs/scrape')}
            className="inline-flex items-center gap-2 text-emerald-600 dark:text-emerald-400 hover:underline"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Websites
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      {/* Toast Notifications */}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((toastItem) => (
          <div
            key={toastItem.id}
            className={`flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg border ${
              toastItem.type === 'success' ? 'bg-emerald-50 dark:bg-emerald-900/50 border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-200' :
              toastItem.type === 'error' ? 'bg-red-50 dark:bg-red-900/50 border-red-200 dark:border-red-800 text-red-800 dark:text-red-200' :
              toastItem.type === 'warning' ? 'bg-amber-50 dark:bg-amber-900/50 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200' :
              'bg-blue-50 dark:bg-blue-900/50 border-blue-200 dark:border-blue-800 text-blue-800 dark:text-blue-200'
            }`}
          >
            {toastItem.type === 'success' && <CheckCircle className="w-5 h-5" />}
            {toastItem.type === 'error' && <XCircle className="w-5 h-5" />}
            {toastItem.type === 'warning' && <AlertTriangle className="w-5 h-5" />}
            {toastItem.type === 'info' && <Info className="w-5 h-5" />}
            <span className="text-sm font-medium">{toastItem.message}</span>
            <button onClick={() => removeToast(toastItem.id)} className="ml-2 opacity-70 hover:opacity-100">
              <X className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Back Link */}
        <Link
          href={orgUrl('/syncs/scrape')}
          className="inline-flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Websites
        </Link>

        {/* Page Header */}
        <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-4 mb-8">
          <div className="flex items-start gap-4">
            <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-lg shadow-emerald-500/25">
              <Globe className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                {collection.name}
              </h1>
              <a
                href={collection.root_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 hover:text-emerald-600 dark:hover:text-emerald-400 mt-1"
              >
                {collection.root_url}
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={loadCollection}
              disabled={loading}
              className="p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>

            {isAdmin && collection.status === 'active' && (
              <button
                onClick={handleStartCrawl}
                disabled={isCrawlActive}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-gradient-to-r from-emerald-500 to-teal-600 rounded-lg hover:from-emerald-600 hover:to-teal-700 disabled:opacity-50 shadow-lg shadow-emerald-500/25 transition-all"
              >
                {isCrawlActive ? (
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

            {isAdmin && (
              <button
                onClick={() => setShowDeleteDialog(true)}
                disabled={isCrawlActive || deleting}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg disabled:opacity-50 transition-all"
                title="Delete collection"
              >
                <Trash2 className="w-4 h-4" />
                Delete
              </button>
            )}
          </div>
        </div>

        {/* Crawl Progress */}
        <JobProgressPanel
          resourceType="scrape_collection"
          resourceId={collectionId}
          onComplete={() => loadCollection()}
          className="mb-6"
        />

        {/* Stats Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
                <FileText className="w-5 h-5 text-blue-600 dark:text-blue-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {collection.stats?.page_count || 0}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Pages
                </p>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-purple-50 dark:bg-purple-900/20 flex items-center justify-center">
                <FileDown className="w-5 h-5 text-purple-600 dark:text-purple-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {collection.stats?.document_count || 0}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Documents
                </p>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${getStatusColor(collection.status)}`}>
                {getStatusIcon(collection.status)}
              </div>
              <div>
                <p className="text-lg font-semibold text-gray-900 dark:text-white capitalize">
                  {collection.status}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Status</p>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gray-50 dark:bg-gray-700 flex items-center justify-center">
                <Clock className="w-5 h-5 text-gray-500 dark:text-gray-400" />
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

        {/* Error State */}
        {error && (
          <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
            <div className="flex items-center gap-3">
              <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
              <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="border-b border-gray-200 dark:border-gray-700 mb-6">
          <nav className="flex gap-6">
            {(['assets', 'tree'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === tab
                    ? 'border-emerald-500 text-emerald-600 dark:text-emerald-400'
                    : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
                }`}
              >
                {tab === 'assets' && 'All Content'}
                {tab === 'tree' && 'Browse by Path'}
              </button>
            ))}
          </nav>
        </div>

        {/* Assets Tab */}
        {activeTab === 'assets' && (
          <div>
            {/* Filter Buttons */}
            <div className="flex items-center gap-2 mb-4">
              {(['all', 'page', 'record'] as const).map((filter) => (
                <button
                  key={filter}
                  onClick={() => handleFilterAssets(filter)}
                  className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
                    assetFilter === filter
                      ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
                      : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
                  }`}
                >
                  {filter === 'all' ? 'All' : filter === 'page' ? 'Pages' : 'Documents'}
                </button>
              ))}
            </div>

            {/* Assets List */}
            {assets.length === 0 ? (
              <div className="text-center py-12">
                <FileText className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
                  No content yet
                </h3>
                <p className="text-gray-500 dark:text-gray-400">
                  Start a crawl to capture pages from this website.
                </p>
              </div>
            ) : (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
                      <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                        Content
                      </th>
                      <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase hidden sm:table-cell">
                        Type
                      </th>
                      <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase hidden md:table-cell">
                        Captured
                      </th>
                      <th className="w-20"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                    {assets.map((asset) => (
                      <tr key={asset.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-3">
                            <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                              asset.asset_subtype === 'document'
                                ? 'bg-purple-50 dark:bg-purple-900/20'
                                : 'bg-blue-50 dark:bg-blue-900/20'
                            }`}>
                              {asset.asset_subtype === 'document' ? (
                                <FileDown className="w-4 h-4 text-purple-600 dark:text-purple-400" />
                              ) : (
                                <FileText className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                              )}
                            </div>
                            <div className="min-w-0">
                              <p className="font-medium text-gray-900 dark:text-white truncate">
                                {asset.title || asset.url_path}
                              </p>
                              <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                                {asset.url_path}
                              </p>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3 hidden sm:table-cell">
                          <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${
                            asset.asset_subtype === 'document'
                              ? 'bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-400'
                              : 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400'
                          }`}>
                            {asset.asset_subtype === 'document' ? 'Document' : 'Page'}
                          </span>
                        </td>
                        <td className="px-4 py-3 hidden md:table-cell">
                          <span className="text-sm text-gray-500 dark:text-gray-400">
                            {formatDate(asset.created_at)}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => handleViewContent(asset)}
                              className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
                              title="View content"
                            >
                              <Eye className="w-4 h-4" />
                            </button>
                            <a
                              href={asset.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
                              title="Open original"
                            >
                              <ExternalLink className="w-4 h-4" />
                            </a>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Tree Tab */}
        {activeTab === 'tree' && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            {/* Breadcrumb */}
            <div className="flex items-center gap-1 text-sm mb-4 overflow-x-auto">
              <button
                onClick={() => handleNavigatePath('/')}
                className="text-emerald-600 dark:text-emerald-400 hover:underline"
              >
                Root
              </button>
              {currentPath !== '/' && currentPath.split('/').filter(Boolean).map((segment, i, arr) => (
                <span key={i} className="flex items-center gap-1">
                  <ChevronRight className="w-4 h-4 text-gray-400" />
                  <button
                    onClick={() => handleNavigatePath('/' + arr.slice(0, i + 1).join('/'))}
                    className="text-emerald-600 dark:text-emerald-400 hover:underline"
                  >
                    {segment}
                  </button>
                </span>
              ))}
            </div>

            {/* Tree Nodes */}
            {pathTree.length === 0 ? (
              <p className="text-center py-8 text-gray-500 dark:text-gray-400">
                No content at this path
              </p>
            ) : (
              <div className="space-y-1">
                {pathTree.map((node) => (
                  <div
                    key={node.path}
                    className="flex items-center gap-3 p-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50"
                  >
                    {node.is_directory ? (
                      <button
                        onClick={() => handleNavigatePath(node.path)}
                        className="flex items-center gap-3 flex-1"
                      >
                        <FolderOpen className="w-5 h-5 text-amber-500" />
                        <span className="text-gray-900 dark:text-white">{node.name}</span>
                        <span className="text-xs text-gray-500 dark:text-gray-400 ml-auto">
                          {node.child_count} items
                        </span>
                        <ChevronRight className="w-4 h-4 text-gray-400" />
                      </button>
                    ) : (
                      <div className="flex items-center gap-3 flex-1">
                        <FileText className="w-5 h-5 text-blue-500" />
                        <span className="text-gray-900 dark:text-white">{node.name}</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Content Viewer Modal */}
      {contentViewerOpen && contentViewerAsset && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl shadow-xl max-w-4xl w-full max-h-[80vh] overflow-hidden flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-gray-900 dark:text-white truncate">
                  {contentViewerAsset.title || contentViewerAsset.url_path}
                </h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 truncate">
                  {contentViewerAsset.url_path}
                </p>
              </div>
              <div className="flex items-center gap-2 ml-4">
                <button
                  onClick={handleCopyContent}
                  disabled={!contentViewerContent}
                  className="p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors disabled:opacity-50"
                  title="Copy content"
                >
                  {contentCopied ? <Check className="w-4 h-4 text-emerald-500" /> : <Copy className="w-4 h-4" />}
                </button>
                <button
                  onClick={() => setContentViewerOpen(false)}
                  className="p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-auto p-6">
              {contentViewerLoading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="w-6 h-6 text-emerald-500 animate-spin" />
                </div>
              ) : contentViewerContent ? (
                <pre className="text-sm text-gray-800 dark:text-gray-200 whitespace-pre-wrap font-mono">
                  {contentViewerContent}
                </pre>
              ) : (
                <p className="text-center py-12 text-gray-500 dark:text-gray-400">
                  No content available
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      {showDeleteDialog && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-full items-center justify-center p-4 text-center">
            {/* Backdrop */}
            <div
              className="fixed inset-0 bg-black/50 transition-opacity"
              onClick={() => !deleting && setShowDeleteDialog(false)}
            />

            {/* Dialog */}
            <div className="relative bg-white dark:bg-gray-900 rounded-2xl shadow-xl p-6 w-full max-w-md text-left">
              <div className="flex items-center gap-3 mb-4">
                <div className="flex-shrink-0 w-10 h-10 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                  <Trash2 className="w-5 h-5 text-red-600 dark:text-red-400" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                    Delete Collection
                  </h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    This action cannot be undone
                  </p>
                </div>
              </div>

              <p className="text-gray-600 dark:text-gray-300 mb-4">
                Are you sure you want to delete <strong>{collection?.name}</strong>? This will permanently remove:
              </p>

              <ul className="list-disc list-inside text-sm text-gray-600 dark:text-gray-400 mb-6 space-y-1">
                <li>All scraped pages and documents</li>
                <li>All associated files from storage</li>
                <li>All crawl history and logs</li>
                <li>The collection configuration</li>
              </ul>

              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setShowDeleteDialog(false)}
                  disabled={deleting}
                  className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg disabled:opacity-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    setShowDeleteDialog(false)
                    handleDelete()
                  }}
                  disabled={deleting}
                  className="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg disabled:opacity-50 transition-colors inline-flex items-center gap-2"
                >
                  {deleting ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Deleting...
                    </>
                  ) : (
                    <>
                      <Trash2 className="w-4 h-4" />
                      Delete Collection
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

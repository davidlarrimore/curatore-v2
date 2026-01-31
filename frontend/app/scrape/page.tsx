'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { useDeletionJobs } from '@/lib/deletion-jobs-context'
import { scrapeApi, ScrapeCollection, CrawlStatus } from '@/lib/api'
import { formatCompact } from '@/lib/date-utils'
import Link from 'next/link'
import toast from 'react-hot-toast'
import {
  Globe,
  Plus,
  RefreshCw,
  Loader2,
  AlertTriangle,
  Search,
  ExternalLink,
  FileText,
  Clock,
  Play,
  Pause,
  Archive,
  CheckCircle,
  XCircle,
  Trash2,
  MoreVertical,
  Settings,
} from 'lucide-react'

export default function ScrapeCollectionsPage() {
  const router = useRouter()
  const { token, user } = useAuth()
  const { isDeleting, addJob } = useDeletionJobs()
  const [collections, setCollections] = useState<ScrapeCollection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [crawlStatuses, setCrawlStatuses] = useState<Record<string, CrawlStatus>>({})
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)

  const isAdmin = user?.role === 'org_admin' || user?.role === 'admin'

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
      }
    }
  }, [])

  useEffect(() => {
    if (token) {
      loadCollections()
    }
  }, [token])

  // Check crawl status for collections that might be running
  useEffect(() => {
    if (token && collections.length > 0) {
      checkActiveCrawls()
    }
  }, [token, collections])

  async function loadCollections() {
    if (!token) return
    setLoading(true)
    setError(null)
    try {
      const result = await scrapeApi.listCollections(token)
      setCollections(result.collections)
    } catch (err: any) {
      setError(err.message || 'Failed to load collections')
    } finally {
      setLoading(false)
    }
  }

  async function checkActiveCrawls() {
    if (!token) return

    // Check status for collections with recent crawl run IDs
    const collectionsToCheck = collections.filter(c => c.last_crawl_run_id)

    for (const collection of collectionsToCheck) {
      try {
        const status = await scrapeApi.getCrawlStatus(token, collection.id)
        if (status.status === 'pending' || status.status === 'running') {
          setCrawlStatuses(prev => ({ ...prev, [collection.id]: status }))
          startPolling()
        }
      } catch {
        // Ignore - no active crawl
      }
    }
  }

  function startPolling() {
    if (pollIntervalRef.current) return // Already polling

    pollIntervalRef.current = setInterval(async () => {
      if (!token) return

      const activeIds = Object.keys(crawlStatuses)
      if (activeIds.length === 0) {
        stopPolling()
        return
      }

      for (const collectionId of activeIds) {
        try {
          const status = await scrapeApi.getCrawlStatus(token, collectionId)
          if (status.status === 'completed' || status.status === 'failed') {
            setCrawlStatuses(prev => {
              const updated = { ...prev }
              delete updated[collectionId]
              return updated
            })
            loadCollections() // Refresh to get updated stats
          } else {
            setCrawlStatuses(prev => ({ ...prev, [collectionId]: status }))
          }
        } catch {
          setCrawlStatuses(prev => {
            const updated = { ...prev }
            delete updated[collectionId]
            return updated
          })
        }
      }
    }, 3000)
  }

  function stopPolling() {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
  }

  async function handleDelete(collection: ScrapeCollection) {
    if (!token) return

    setDeleting(collection.id)
    try {
      const result = await scrapeApi.deleteCollection(token, collection.id)

      // Add to global deletion tracking
      addJob({
        runId: result.run_id,
        configId: collection.id,
        configName: collection.name,
        configType: 'scrape',
      })

      toast.success('Deletion started...')
      setDeleteConfirm(null)
      loadCollections()
    } catch (err: any) {
      toast.error(err.message || 'Failed to delete collection')
    } finally {
      setDeleting(null)
    }
  }

  const isCrawling = (collectionId: string) => {
    const status = crawlStatuses[collectionId]
    return status && (status.status === 'pending' || status.status === 'running')
  }

  const filteredCollections = collections.filter((c) => {
    if (!searchQuery) return true
    const query = searchQuery.toLowerCase()
    return (
      c.name.toLowerCase().includes(query) ||
      c.root_url.toLowerCase().includes(query) ||
      c.description?.toLowerCase().includes(query)
    )
  })

  const getStatusBadge = (collection: ScrapeCollection) => {
    // Check if deletion is in progress (either from DB status or from context)
    if (collection.status === 'deleting' || isDeleting(collection.id)) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400">
          <Loader2 className="w-3 h-3 animate-spin" />
          Deleting...
        </span>
      )
    }

    // Check if crawl is in progress
    if (isCrawling(collection.id)) {
      const status = crawlStatuses[collection.id]
      const progress = status?.progress?.percent
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400">
          <Loader2 className="w-3 h-3 animate-spin" />
          Crawling{progress !== undefined && progress !== null ? ` ${progress}%` : '...'}
        </span>
      )
    }

    switch (collection.status) {
      case 'active':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
            Active
          </span>
        )
      case 'paused':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400">
            <Pause className="w-3 h-3" />
            Paused
          </span>
        )
      case 'archived':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
            <Archive className="w-3 h-3" />
            Archived
          </span>
        )
      default:
        return null
    }
  }

  // Use formatCompact from date-utils for consistent EST display
  const formatDate = (dateStr: string | null) => dateStr ? formatCompact(dateStr) : 'Never'

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-4">
            <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-lg shadow-emerald-500/25">
              <Globe className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900 dark:text-white">
                Web Scraping
              </h1>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {collections.length} website{collections.length !== 1 ? 's' : ''} configured
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={loadCollections}
              disabled={loading}
              className="p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>

            {isAdmin && (
              <button
                onClick={() => setShowCreateModal(true)}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-gradient-to-r from-emerald-500 to-teal-600 rounded-lg hover:from-emerald-600 hover:to-teal-700 shadow-lg shadow-emerald-500/25 transition-all"
              >
                <Plus className="w-4 h-4" />
                Add Website
              </button>
            )}
          </div>
        </div>

        {/* Search Bar */}
        <div className="relative mb-6">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search websites..."
            className="w-full pl-10 pr-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
          />
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

        {/* Loading State */}
        {loading && collections.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16">
            <Loader2 className="w-8 h-8 text-emerald-500 animate-spin" />
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading websites...</p>
          </div>
        )}

        {/* Empty State */}
        {!loading && collections.length === 0 && (
          <div className="text-center py-16">
            <Globe className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
              No websites configured
            </h3>
            <p className="text-gray-500 dark:text-gray-400 mb-6">
              Add a website to start scraping its content.
            </p>
            {isAdmin && (
              <button
                onClick={() => setShowCreateModal(true)}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-gradient-to-r from-emerald-500 to-teal-600 rounded-lg hover:from-emerald-600 hover:to-teal-700 shadow-lg shadow-emerald-500/25 transition-all"
              >
                <Plus className="w-4 h-4" />
                Add First Website
              </button>
            )}
          </div>
        )}

        {/* Table */}
        {!loading && filteredCollections.length > 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Website
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider hidden sm:table-cell">
                    Status
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider hidden md:table-cell">
                    Pages
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider hidden lg:table-cell">
                    Last Crawl
                  </th>
                  <th className="w-10"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {filteredCollections.map((collection) => (
                  <tr
                    key={collection.id}
                    className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <Link href={`/scrape/${collection.id}`} className="block">
                        <div className="flex items-center gap-3">
                          <div className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${
                            isCrawling(collection.id)
                              ? 'bg-blue-100 dark:bg-blue-900/30'
                              : 'bg-gray-100 dark:bg-gray-700'
                          }`}>
                            {isCrawling(collection.id) ? (
                              <RefreshCw className="w-4 h-4 text-blue-500 dark:text-blue-400 animate-spin" />
                            ) : (
                              <Globe className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                            )}
                          </div>
                          <div className="min-w-0">
                            <p className="font-medium text-gray-900 dark:text-white truncate">
                              {collection.name}
                            </p>
                            <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                              {collection.root_url}
                            </p>
                          </div>
                        </div>
                      </Link>
                    </td>
                    <td className="px-4 py-3 hidden sm:table-cell">
                      {getStatusBadge(collection)}
                    </td>
                    <td className="px-4 py-3 hidden md:table-cell">
                      <span className="text-sm text-gray-600 dark:text-gray-300">
                        {collection.stats?.page_count || 0}
                      </span>
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell">
                      <span className="text-sm text-gray-500 dark:text-gray-400">
                        {formatDate(collection.last_crawl_at)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        {/* View Job link when crawling */}
                        {isCrawling(collection.id) && crawlStatuses[collection.id]?.run_id && (
                          <Link
                            href={`/admin/queue/${crawlStatuses[collection.id].run_id}`}
                            className="p-1.5 text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded transition-colors"
                            title="View running job"
                          >
                            <Settings className="w-4 h-4" />
                          </Link>
                        )}

                        {/* Delete button for admins on archived collections */}
                        {isAdmin && collection.status === 'archived' && !isDeleting(collection.id) && (
                          <button
                            onClick={(e) => {
                              e.preventDefault()
                              e.stopPropagation()
                              setDeleteConfirm(collection.id)
                            }}
                            disabled={deleting === collection.id}
                            className="p-1.5 text-gray-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 rounded transition-colors"
                            title="Delete collection"
                          >
                            {deleting === collection.id ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <Trash2 className="w-4 h-4" />
                            )}
                          </button>
                        )}

                        {/* View details link */}
                        <Link
                          href={`/scrape/${collection.id}`}
                          className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
                          title="View details"
                        >
                          <ExternalLink className="w-4 h-4" />
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* No Results */}
        {!loading && collections.length > 0 && filteredCollections.length === 0 && (
          <div className="text-center py-12">
            <Search className="w-8 h-8 text-gray-300 dark:text-gray-600 mx-auto mb-3" />
            <p className="text-gray-500 dark:text-gray-400">
              No websites match "{searchQuery}"
            </p>
          </div>
        )}

        {/* Delete Confirmation Dialog */}
        {deleteConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
            <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl shadow-xl max-w-md w-full overflow-hidden">
              <div className="p-6">
                <div className="flex items-center gap-4 mb-4">
                  <div className="flex-shrink-0 w-12 h-12 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                    <Trash2 className="w-6 h-6 text-red-600 dark:text-red-400" />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                      Delete Website
                    </h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      This action cannot be undone
                    </p>
                  </div>
                </div>
                <p className="text-sm text-gray-600 dark:text-gray-300 mb-6">
                  Are you sure you want to delete{' '}
                  <span className="font-medium text-gray-900 dark:text-white">
                    {collections.find(c => c.id === deleteConfirm)?.name}
                  </span>
                  ? This will permanently remove all scraped pages, documents, and associated data.
                </p>
                <div className="flex items-center justify-end gap-3">
                  <button
                    onClick={() => setDeleteConfirm(null)}
                    className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => {
                      const collection = collections.find(c => c.id === deleteConfirm)
                      if (collection) handleDelete(collection)
                    }}
                    disabled={deleting !== null}
                    className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg disabled:opacity-50 transition-colors"
                  >
                    {deleting === deleteConfirm ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Deleting...
                      </>
                    ) : (
                      <>
                        <Trash2 className="w-4 h-4" />
                        Delete
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Create Modal */}
        {showCreateModal && (
          <AddWebsiteModal
            onClose={() => setShowCreateModal(false)}
            onCreated={() => {
              setShowCreateModal(false)
              loadCollections()
            }}
          />
        )}
      </div>
    </div>
  )
}

// Add Website Modal with crawl options
function AddWebsiteModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: () => void
}) {
  const { token } = useAuth()
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [downloadDocuments, setDownloadDocuments] = useState(false) // Default OFF
  const [maxDepth, setMaxDepth] = useState(2) // Default 2 levels
  const [loading, setLoading] = useState(false)
  const [fetchingMeta, setFetchingMeta] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [metaFetched, setMetaFetched] = useState(false)
  const urlInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    urlInputRef.current?.focus()
  }, [])

  // Auto-fetch website metadata when URL is entered
  async function fetchWebsiteMeta(targetUrl: string) {
    if (!targetUrl || metaFetched) return

    // Validate URL format
    try {
      new URL(targetUrl)
    } catch {
      return
    }

    setFetchingMeta(true)
    try {
      // Use a CORS proxy or fetch via our backend (for now, extract from URL)
      const urlObj = new URL(targetUrl)
      const hostname = urlObj.hostname.replace('www.', '')

      // Set a default name from hostname if not already set
      if (!name) {
        // Convert hostname to title case
        const siteName = hostname
          .split('.')
          .slice(0, -1) // Remove TLD
          .join(' ')
          .replace(/-/g, ' ')
          .split(' ')
          .map(word => word.charAt(0).toUpperCase() + word.slice(1))
          .join(' ')
        setName(siteName || hostname)
      }

      setMetaFetched(true)
    } catch (err) {
      console.error('Failed to fetch metadata:', err)
    } finally {
      setFetchingMeta(false)
    }
  }

  // Debounced URL change handler
  useEffect(() => {
    const timer = setTimeout(() => {
      if (url && url.includes('.')) {
        fetchWebsiteMeta(url)
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [url])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!token || !url) return

    // Validate URL
    let finalUrl = url
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      finalUrl = 'https://' + url
    }

    try {
      new URL(finalUrl)
    } catch {
      setError('Please enter a valid URL')
      return
    }

    setLoading(true)
    setError(null)

    try {
      // Create collection with auto-start crawl
      const collection = await scrapeApi.createCollection(token, {
        name: name || new URL(finalUrl).hostname,
        root_url: finalUrl,
        description: description || undefined,
        collection_mode: 'snapshot', // Default to snapshot
        crawl_config: {
          download_documents: downloadDocuments,
          max_depth: maxDepth,
        },
      })

      // Auto-start crawl
      try {
        await scrapeApi.startCrawl(token, collection.id)
      } catch (crawlErr: any) {
        console.error('Failed to auto-start crawl:', crawlErr)
        // Show error but don't fail - collection was created
        setError(`Website added but crawl failed to start: ${crawlErr.message || 'Unknown error'}. You can start it manually.`)
        setLoading(false)
        // Still call onCreated to close modal and refresh list
        setTimeout(() => onCreated(), 2000)
        return
      }

      onCreated()
    } catch (err: any) {
      setError(err.message || 'Failed to create website')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl shadow-xl max-w-md w-full overflow-hidden">
        {/* Header */}
        <div className="relative bg-gradient-to-r from-emerald-600 to-teal-600 px-6 py-4">
          <h2 className="text-lg font-bold text-white">Add Website</h2>
          <p className="text-emerald-100 text-sm">Enter a URL to start scraping</p>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-3">
              <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          {/* URL Input */}
          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Website URL *
            </label>
            <div className="relative">
              <Globe className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                ref={urlInputRef}
                type="text"
                value={url}
                onChange={(e) => {
                  setUrl(e.target.value)
                  setMetaFetched(false)
                }}
                placeholder="example.com"
                required
                className="w-full pl-10 pr-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
              />
              {fetchingMeta && (
                <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-emerald-500 animate-spin" />
              )}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              We'll automatically detect the website name
            </p>
          </div>

          {/* Name (auto-filled but editable) */}
          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Website name (auto-detected)"
              className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
            />
          </div>

          {/* Description (optional) */}
          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Description <span className="text-gray-400">(optional)</span>
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this website about?"
              className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
            />
          </div>

          {/* Crawl Depth */}
          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Crawl Depth
            </label>
            <div className="grid grid-cols-4 gap-2">
              {[
                { value: 1, label: '1 level' },
                { value: 2, label: '2 levels' },
                { value: 3, label: '3 levels' },
                { value: 0, label: 'All' },
              ].map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setMaxDepth(option.value)}
                  className={`px-3 py-2 text-sm font-medium rounded-lg border transition-colors ${
                    maxDepth === option.value
                      ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400'
                      : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800'
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              How many levels of links to follow from the starting page
            </p>
          </div>

          {/* Download Documents Toggle */}
          <label className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-700 rounded-lg cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
            <div>
              <p className="text-sm font-medium text-gray-900 dark:text-white">Download Documents</p>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Also download PDFs, Word docs, and other files
              </p>
            </div>
            <div className="relative">
              <input
                type="checkbox"
                checked={downloadDocuments}
                onChange={(e) => setDownloadDocuments(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-10 h-5 bg-gray-200 peer-focus:ring-2 peer-focus:ring-emerald-300 dark:peer-focus:ring-emerald-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-emerald-500"></div>
            </div>
          </label>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading || !url}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-gradient-to-r from-emerald-500 to-teal-600 rounded-lg hover:from-emerald-600 hover:to-teal-700 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-emerald-500/25 transition-all"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <Play className="w-4 h-4" />
                  Add & Start Crawl
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

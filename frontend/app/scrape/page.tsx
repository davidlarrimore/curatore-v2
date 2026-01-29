'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@/lib/auth-context'
import { scrapeApi, ScrapeCollection } from '@/lib/api'
import Link from 'next/link'
import {
  Globe,
  Plus,
  RefreshCw,
  Loader2,
  AlertTriangle,
  Archive,
  Play,
  Pause,
  ExternalLink,
  FolderOpen,
  FileText,
  Clock,
  MoreHorizontal,
  Pencil,
  Trash2,
} from 'lucide-react'

export default function ScrapeCollectionsPage() {
  const { token, user } = useAuth()
  const [collections, setCollections] = useState<ScrapeCollection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreateModal, setShowCreateModal] = useState(false)

  const isAdmin = user?.role === 'org_admin' || user?.role === 'admin'

  useEffect(() => {
    if (token) {
      loadCollections()
    }
  }, [token])

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

  const getModeGradient = (mode: string) => {
    return mode === 'record_preserving'
      ? 'from-indigo-500 to-purple-600'
      : 'from-blue-500 to-cyan-500'
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

  const activeCount = collections.filter(c => c.status === 'active').length
  const pausedCount = collections.filter(c => c.status === 'paused').length

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
          <div className="flex items-center gap-4">
            <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25">
              <Globe className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                Web Scraping
              </h1>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                Manage web scraping collections and crawled content
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={loadCollections}
              disabled={loading}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>

            {isAdmin && (
              <button
                onClick={() => setShowCreateModal(true)}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-gradient-to-r from-indigo-500 to-purple-600 rounded-lg hover:from-indigo-600 hover:to-purple-700 shadow-lg shadow-indigo-500/25 transition-all"
              >
                <Plus className="w-4 h-4" />
                New Collection
              </button>
            )}
          </div>
        </div>

        {/* Stats Bar */}
        <div className="flex flex-wrap items-center gap-4 text-sm mb-6">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300">
            <span className="font-medium">{collections.length}</span>
            <span>total</span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400">
            <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
            <span className="font-medium">{activeCount}</span>
            <span>active</span>
          </div>
          {pausedCount > 0 && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400">
              <span className="w-2 h-2 rounded-full bg-amber-500"></span>
              <span className="font-medium">{pausedCount}</span>
              <span>paused</span>
            </div>
          )}
        </div>

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
        {loading && collections.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin"></div>
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading collections...</p>
          </div>
        )}

        {/* Empty State */}
        {!loading && collections.length === 0 && (
          <div className="relative overflow-hidden rounded-2xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/50 px-6 py-16 text-center">
            <div className="absolute inset-0 pointer-events-none">
              <div className="absolute -top-24 -right-24 w-64 h-64 rounded-full bg-gradient-to-br from-indigo-500/5 to-purple-500/5 blur-3xl"></div>
              <div className="absolute -bottom-24 -left-24 w-64 h-64 rounded-full bg-gradient-to-br from-blue-500/5 to-cyan-500/5 blur-3xl"></div>
            </div>

            <div className="relative">
              <div className="mx-auto w-20 h-20 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-xl shadow-indigo-500/25 mb-6">
                <Globe className="w-10 h-10 text-white" />
              </div>
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                No Scrape Collections
              </h3>
              <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto mb-8">
                Create a collection to start crawling web content. Collections preserve scraped pages as durable records.
              </p>
              {isAdmin && (
                <button
                  onClick={() => setShowCreateModal(true)}
                  className="inline-flex items-center gap-2 px-6 py-3 text-sm font-medium text-white bg-gradient-to-r from-indigo-500 to-purple-600 rounded-lg hover:from-indigo-600 hover:to-purple-700 shadow-lg shadow-indigo-500/25 transition-all"
                >
                  <Plus className="w-5 h-5" />
                  Create First Collection
                </button>
              )}
            </div>
          </div>
        )}

        {/* Collections Grid */}
        {!loading && collections.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
            {collections.map((collection) => (
              <Link
                key={collection.id}
                href={`/scrape/${collection.id}`}
                className="group relative bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 hover:shadow-lg hover:shadow-gray-200/50 dark:hover:shadow-gray-900/50 transition-all duration-200 overflow-hidden"
              >
                {/* Status bar at top */}
                <div className={`absolute top-0 left-0 right-0 h-1 bg-gradient-to-r ${getModeGradient(collection.collection_mode)}`} />

                <div className="p-5">
                  {/* Header */}
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="font-semibold text-gray-900 dark:text-white truncate">
                          {collection.name}
                        </h3>
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                        {collection.root_url}
                      </p>
                    </div>
                    <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${getStatusColor(collection.status)}`}>
                      {getStatusIcon(collection.status)}
                      <span className="capitalize">{collection.status}</span>
                    </div>
                  </div>

                  {/* Description */}
                  {collection.description && (
                    <p className="text-sm text-gray-600 dark:text-gray-300 line-clamp-2 mb-4">
                      {collection.description}
                    </p>
                  )}

                  {/* Stats */}
                  <div className="grid grid-cols-2 gap-3 mb-4">
                    <div className="flex items-center gap-2 text-sm">
                      <FileText className="w-4 h-4 text-gray-400" />
                      <span className="text-gray-600 dark:text-gray-300">
                        {collection.stats?.page_count || 0} pages
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-sm">
                      <FolderOpen className="w-4 h-4 text-indigo-500" />
                      <span className="text-gray-600 dark:text-gray-300">
                        {collection.stats?.record_count || 0} records
                      </span>
                    </div>
                  </div>

                  {/* Footer */}
                  <div className="flex items-center justify-between pt-4 border-t border-gray-100 dark:border-gray-700">
                    <div className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
                      <Clock className="w-3 h-3" />
                      <span>Last crawl: {formatDate(collection.last_crawl_at)}</span>
                    </div>
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      collection.collection_mode === 'record_preserving'
                        ? 'bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-400'
                        : 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400'
                    }`}>
                      {collection.collection_mode === 'record_preserving' ? 'Preserving' : 'Snapshot'}
                    </span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}

        {/* Create Modal - Placeholder */}
        {showCreateModal && (
          <CreateCollectionModal
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

// Simple create modal component
function CreateCollectionModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: () => void
}) {
  const { token } = useAuth()
  const [name, setName] = useState('')
  const [rootUrl, setRootUrl] = useState('')
  const [description, setDescription] = useState('')
  const [mode, setMode] = useState<'record_preserving' | 'snapshot'>('record_preserving')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!token || !name || !rootUrl) return

    setLoading(true)
    setError(null)

    try {
      await scrapeApi.createCollection(token, {
        name,
        root_url: rootUrl,
        description: description || undefined,
        collection_mode: mode,
      })
      onCreated()
    } catch (err: any) {
      setError(err.message || 'Failed to create collection')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl shadow-xl max-w-lg w-full overflow-hidden">
        {/* Header */}
        <div className="relative bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-600 px-6 py-5">
          <h2 className="text-xl font-bold text-white">Create Scrape Collection</h2>
          <p className="text-indigo-100 text-sm mt-0.5">Configure a new web scraping collection</p>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-3">
              <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Collection Name *
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., SAM.gov Opportunities"
              required
              className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 transition-all"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Root URL *
            </label>
            <input
              type="url"
              value={rootUrl}
              onChange={(e) => setRootUrl(e.target.value)}
              placeholder="https://example.com"
              required
              className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 transition-all"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Brief description of what this collection will capture..."
              rows={2}
              className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 transition-all resize-none"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Collection Mode
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label
                className={`flex items-center p-3 border rounded-lg cursor-pointer transition-all ${
                  mode === 'record_preserving'
                    ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                    : 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800'
                }`}
              >
                <input
                  type="radio"
                  name="mode"
                  value="record_preserving"
                  checked={mode === 'record_preserving'}
                  onChange={() => setMode('record_preserving')}
                  className="sr-only"
                />
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-white">Record Preserving</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Never auto-delete records</p>
                </div>
              </label>
              <label
                className={`flex items-center p-3 border rounded-lg cursor-pointer transition-all ${
                  mode === 'snapshot'
                    ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                    : 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800'
                }`}
              >
                <input
                  type="radio"
                  name="mode"
                  value="snapshot"
                  checked={mode === 'snapshot'}
                  onChange={() => setMode('snapshot')}
                  className="sr-only"
                />
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-white">Snapshot</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Replace old pages on re-crawl</p>
                </div>
              </label>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading || !name || !rootUrl}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-gradient-to-r from-indigo-500 to-purple-600 rounded-lg hover:from-indigo-600 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-indigo-500/25 transition-all"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              Create Collection
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { searchApi, SearchHit, SearchResponse } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import {
  Search,
  FileText,
  Globe,
  Upload,
  FolderSync,
  X,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  AlertTriangle,
  Loader2,
  ExternalLink,
} from 'lucide-react'
import ProtectedRoute from '@/components/auth/ProtectedRoute'

// Source type configuration
const sourceTypeConfig: Record<string, { name: string; icon: React.ReactNode; color: string }> = {
  upload: {
    name: 'Upload',
    icon: <Upload className="w-4 h-4" />,
    color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  },
  sharepoint: {
    name: 'SharePoint',
    icon: <FolderSync className="w-4 h-4" />,
    color: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400',
  },
  web_scrape: {
    name: 'Web Scrape',
    icon: <Globe className="w-4 h-4" />,
    color: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  },
}

export default function SearchPage() {
  return (
    <ProtectedRoute>
      <SearchContent />
    </ProtectedRoute>
  )
}

function SearchContent() {
  const router = useRouter()
  const { token } = useAuth()
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [results, setResults] = useState<SearchResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedSourceTypes, setSelectedSourceTypes] = useState<string[]>([])
  const [limit] = useState(20)
  const [offset, setOffset] = useState(0)
  const searchInputRef = useRef<HTMLInputElement>(null)

  // Debounce search query
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query)
      setOffset(0) // Reset pagination on new query
    }, 300)

    return () => clearTimeout(timer)
  }, [query])

  // Execute search when debounced query changes
  const executeSearch = useCallback(async () => {
    if (!token || !debouncedQuery.trim()) {
      setResults(null)
      return
    }

    setIsLoading(true)
    setError('')

    try {
      const response = await searchApi.search(token, {
        query: debouncedQuery.trim(),
        source_types: selectedSourceTypes.length > 0 ? selectedSourceTypes : undefined,
        limit,
        offset,
      })
      setResults(response)
    } catch (err: any) {
      if (err.status === 503) {
        setError('Search is not enabled. Enable OpenSearch to use this feature.')
      } else {
        setError(err.message || 'Search failed')
      }
      setResults(null)
    } finally {
      setIsLoading(false)
    }
  }, [token, debouncedQuery, selectedSourceTypes, limit, offset])

  useEffect(() => {
    executeSearch()
  }, [executeSearch])

  // Toggle source type filter
  const toggleSourceType = (type: string) => {
    setSelectedSourceTypes(prev =>
      prev.includes(type)
        ? prev.filter(t => t !== type)
        : [...prev, type]
    )
    setOffset(0) // Reset pagination
  }

  // Clear all filters
  const clearFilters = () => {
    setSelectedSourceTypes([])
    setOffset(0)
  }

  // Pagination
  const totalPages = results ? Math.ceil(results.total / limit) : 0
  const currentPage = Math.floor(offset / limit) + 1

  const goToPage = (page: number) => {
    setOffset((page - 1) * limit)
  }

  // Navigate to asset detail
  const handleResultClick = (hit: SearchHit) => {
    router.push(`/assets/${hit.asset_id}`)
  }

  // Render highlighted text
  const renderHighlight = (text: string) => {
    // Split by mark tags and render
    const parts = text.split(/(<mark>.*?<\/mark>)/g)
    return parts.map((part, i) => {
      if (part.startsWith('<mark>') && part.endsWith('</mark>')) {
        const content = part.slice(6, -7)
        return (
          <mark
            key={i}
            className="bg-yellow-200 dark:bg-yellow-900/50 text-yellow-900 dark:text-yellow-200 px-0.5 rounded"
          >
            {content}
          </mark>
        )
      }
      return <span key={i}>{part}</span>
    })
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-4">
            <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25">
              <Search className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                Search
              </h1>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                Find documents across all your sources
              </p>
            </div>
          </div>
        </div>

        {/* Search Input */}
        <div className="mb-6">
          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
              {isLoading ? (
                <Loader2 className="w-5 h-5 text-gray-400 animate-spin" />
              ) : (
                <Search className="w-5 h-5 text-gray-400" />
              )}
            </div>
            <input
              ref={searchInputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search for documents, content, or keywords..."
              className="w-full pl-12 pr-12 py-4 text-lg border border-gray-200 dark:border-gray-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 shadow-sm"
              autoFocus
            />
            {query && (
              <button
                onClick={() => setQuery('')}
                className="absolute inset-y-0 right-0 pr-4 flex items-center text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
              >
                <X className="w-5 h-5" />
              </button>
            )}
          </div>
        </div>

        {/* Filters */}
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <span className="text-sm text-gray-500 dark:text-gray-400">Filter by:</span>
          {Object.entries(sourceTypeConfig).map(([type, config]) => (
            <button
              key={type}
              onClick={() => toggleSourceType(type)}
              className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium transition-all ${
                selectedSourceTypes.includes(type)
                  ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400 ring-2 ring-indigo-500'
                  : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
              }`}
            >
              {config.icon}
              {config.name}
            </button>
          ))}
          {selectedSourceTypes.length > 0 && (
            <button
              onClick={clearFilters}
              className="text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300 underline"
            >
              Clear filters
            </button>
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

        {/* Results */}
        {!query.trim() ? (
          /* Empty State - No Query */
          <div className="relative overflow-hidden rounded-2xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/50 px-6 py-16 text-center">
            <div className="absolute inset-0 pointer-events-none">
              <div className="absolute -top-24 -right-24 w-64 h-64 rounded-full bg-gradient-to-br from-indigo-500/5 to-purple-500/5 blur-3xl"></div>
              <div className="absolute -bottom-24 -left-24 w-64 h-64 rounded-full bg-gradient-to-br from-blue-500/5 to-cyan-500/5 blur-3xl"></div>
            </div>

            <div className="relative">
              <div className="mx-auto w-20 h-20 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-xl shadow-indigo-500/25 mb-6">
                <Search className="w-10 h-10 text-white" />
              </div>
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                Search your documents
              </h3>
              <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto">
                Enter a search query to find documents across uploads, SharePoint, and web scrapes.
              </p>
            </div>
          </div>
        ) : isLoading && !results ? (
          /* Loading State */
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin"></div>
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Searching...</p>
          </div>
        ) : results && results.hits.length === 0 ? (
          /* No Results */
          <div className="relative overflow-hidden rounded-2xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/50 px-6 py-16 text-center">
            <div className="relative">
              <div className="mx-auto w-16 h-16 rounded-xl bg-gray-100 dark:bg-gray-800 flex items-center justify-center mb-4">
                <FileText className="w-8 h-8 text-gray-400" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                No results found
              </h3>
              <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto">
                No documents match your search for &quot;{query}&quot;.
                Try different keywords or remove filters.
              </p>
            </div>
          </div>
        ) : results ? (
          /* Results List */
          <div className="space-y-4">
            {/* Results Header */}
            <div className="flex items-center justify-between text-sm text-gray-500 dark:text-gray-400">
              <span>
                {results.total.toLocaleString()} result{results.total !== 1 ? 's' : ''} found
              </span>
              {isLoading && (
                <span className="flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Updating...
                </span>
              )}
            </div>

            {/* Result Cards */}
            {results.hits.map((hit) => {
              const sourceConfig = sourceTypeConfig[hit.source_type || ''] || {
                name: hit.source_type || 'Unknown',
                icon: <FileText className="w-4 h-4" />,
                color: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400',
              }

              // Get highlighted content
              const contentHighlights = hit.highlights?.content || []
              const titleHighlights = hit.highlights?.title || []

              return (
                <div
                  key={hit.asset_id}
                  onClick={() => handleResultClick(hit)}
                  className="group bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-lg hover:shadow-indigo-500/10 transition-all duration-200 cursor-pointer overflow-hidden"
                >
                  <div className="p-5">
                    {/* Title and Source Type */}
                    <div className="flex items-start justify-between gap-4 mb-2">
                      <div className="flex-1 min-w-0">
                        <h3 className="text-base font-semibold text-gray-900 dark:text-white group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors truncate">
                          {titleHighlights.length > 0
                            ? renderHighlight(titleHighlights[0])
                            : hit.title || hit.filename || 'Untitled'}
                        </h3>
                        {hit.filename && hit.title && hit.filename !== hit.title && (
                          <p className="text-sm text-gray-500 dark:text-gray-400 truncate mt-0.5">
                            {hit.filename}
                          </p>
                        )}
                      </div>
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${sourceConfig.color}`}>
                        {sourceConfig.icon}
                        {sourceConfig.name}
                      </span>
                    </div>

                    {/* URL for web scrapes */}
                    {hit.url && (
                      <p className="text-sm text-gray-500 dark:text-gray-400 truncate mb-2 flex items-center gap-1">
                        <ExternalLink className="w-3 h-3 flex-shrink-0" />
                        {hit.url}
                      </p>
                    )}

                    {/* Content Highlights */}
                    {contentHighlights.length > 0 && (
                      <div className="mt-3 space-y-2">
                        {contentHighlights.slice(0, 2).map((highlight, i) => (
                          <p
                            key={i}
                            className="text-sm text-gray-600 dark:text-gray-300 line-clamp-2"
                          >
                            ...{renderHighlight(highlight)}...
                          </p>
                        ))}
                      </div>
                    )}

                    {/* Footer */}
                    <div className="mt-3 flex items-center justify-between text-xs text-gray-400 dark:text-gray-500">
                      <span>
                        {hit.content_type && `${hit.content_type} • `}
                        {hit.created_at && new Date(hit.created_at).toLocaleDateString()}
                      </span>
                      <span className="text-indigo-500 dark:text-indigo-400 font-medium">
                        {(hit.score * 100).toFixed(0)}% match
                      </span>
                    </div>
                  </div>
                </div>
              )
            })}

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-2 pt-4">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => goToPage(currentPage - 1)}
                  disabled={currentPage === 1}
                >
                  <ChevronLeft className="w-4 h-4" />
                </Button>
                <span className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400">
                  Page {currentPage} of {totalPages}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => goToPage(currentPage + 1)}
                  disabled={currentPage === totalPages}
                >
                  <ChevronRight className="w-4 h-4" />
                </Button>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}

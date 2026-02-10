'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { searchApi, SearchHit, SearchResponse, SearchFacets, metadataApi } from '@/lib/api'
import FacetAutocomplete from '@/components/search/FacetAutocomplete'
import { formatDate } from '@/lib/date-utils'
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
  ChevronDown,
  ChevronUp,
  RefreshCw,
  AlertTriangle,
  Loader2,
  ExternalLink,
  Building2,
  Check,
  Database,
  User,
  DollarSign,
  TrendingUp,
} from 'lucide-react'
import ProtectedRoute from '@/components/auth/ProtectedRoute'

// Source type filter configuration
// Keys match the facet values returned from the backend API for filter buttons
const sourceTypeFilterConfig: Record<string, { name: string; icon: React.ReactNode; color: string }> = {
  // Asset-based sources (from source_type_filter)
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
  sam_gov: {
    name: 'SAM.gov',
    icon: <Building2 className="w-4 h-4" />,
    color: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  },
  forecast: {
    name: 'Acquisition Forecasts',
    icon: <TrendingUp className="w-4 h-4" />,
    color: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  },
  // Salesforce entity types (individual filters)
  // Filter keys match facet values: "Accounts", "Contacts", "Opportunities"
  Accounts: {
    name: 'Accounts',
    icon: <Building2 className="w-4 h-4" />,
    color: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400',
  },
  Contacts: {
    name: 'Contacts',
    icon: <User className="w-4 h-4" />,
    color: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400',
  },
  Opportunities: {
    name: 'Opportunities',
    icon: <DollarSign className="w-4 h-4" />,
    color: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400',
  },
}

// Source type display configuration for search result badges
// Keys match the source_type values returned in search hits
const sourceTypeDisplayConfig: Record<string, { name: string; icon: React.ReactNode; color: string }> = {
  ...sourceTypeFilterConfig,
  // Salesforce result display labels (singular, returned in search hits)
  Account: {
    name: 'Account',
    icon: <Building2 className="w-4 h-4" />,
    color: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400',
  },
  Contact: {
    name: 'Contact',
    icon: <User className="w-4 h-4" />,
    color: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400',
  },
  Opportunity: {
    name: 'Opportunity',
    icon: <DollarSign className="w-4 h-4" />,
    color: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400',
  },
  // Forecast result display labels (keys match backend display names from FORECAST_DISPLAY_TYPES)
  'AG Forecast': {
    name: 'AG Forecast',
    icon: <TrendingUp className="w-4 h-4" />,
    color: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  },
  'APFS Forecast': {
    name: 'DHS Forecast',
    icon: <TrendingUp className="w-4 h-4" />,
    color: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  },
  'State Forecast': {
    name: 'State Forecast',
    icon: <TrendingUp className="w-4 h-4" />,
    color: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  },
}

export default function SearchPage() {
  return (
    <ProtectedRoute>
      <SearchContent />
    </ProtectedRoute>
  )
}

type SearchMode = 'keyword' | 'semantic' | 'hybrid'

function SearchContent() {
  const router = useRouter()
  const { token } = useAuth()
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [results, setResults] = useState<SearchResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedSourceTypes, setSelectedSourceTypes] = useState<string[]>([])
  const [selectedContentTypes, setSelectedContentTypes] = useState<string[]>([])
  const [showAllContentTypes, setShowAllContentTypes] = useState(false)
  const [facets, setFacets] = useState<SearchFacets | null>(null)
  const [limit] = useState(20)
  const [offset, setOffset] = useState(0)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const [searchMode, setSearchMode] = useState<SearchMode>('hybrid')
  const [semanticWeight, setSemanticWeight] = useState(0.5)
  const [facetFilters, setFacetFilters] = useState<Record<string, string[]>>({})
  // AbortController to cancel in-flight requests when filters change
  const abortControllerRef = useRef<AbortController | null>(null)

  // Number of content types to show before "Show more"
  const CONTENT_TYPE_INITIAL_COUNT = 5

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
      setFacets(null)
      return
    }

    // Cancel any in-flight request before starting a new one
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }

    // Create new AbortController for this request
    const abortController = new AbortController()
    abortControllerRef.current = abortController

    setIsLoading(true)
    setError('')

    try {
      // Build facet_filters from selected facet values
      const activeFacetFilters: Record<string, any> = {}
      for (const [facetName, values] of Object.entries(facetFilters)) {
        if (values.length === 1) {
          activeFacetFilters[facetName] = values[0]
        } else if (values.length > 1) {
          activeFacetFilters[facetName] = values
        }
      }

      const response = await searchApi.search(token, {
        query: debouncedQuery.trim(),
        search_mode: searchMode,
        semantic_weight: searchMode === 'hybrid' ? semanticWeight : undefined,
        source_types: selectedSourceTypes.length > 0 ? selectedSourceTypes : undefined,
        content_types: selectedContentTypes.length > 0 ? selectedContentTypes : undefined,
        facet_filters: Object.keys(activeFacetFilters).length > 0 ? activeFacetFilters : undefined,
        include_facets: true,
        limit,
        offset,
      })

      // Only update state if this request wasn't aborted
      if (!abortController.signal.aborted) {
        setResults(response)
        setFacets(response.facets || null)
      }
    } catch (err: any) {
      // Ignore abort errors - they're expected when we cancel requests
      if (err.name === 'AbortError' || abortController.signal.aborted) {
        return
      }
      if (err.status === 503) {
        setError('Search is not enabled. Enable SEARCH_ENABLED to use this feature.')
      } else {
        setError(err.message || 'Search failed')
      }
      setResults(null)
      setFacets(null)
    } finally {
      // Only clear loading if this was the current request
      if (abortControllerRef.current === abortController) {
        setIsLoading(false)
      }
    }
  }, [token, debouncedQuery, searchMode, semanticWeight, selectedSourceTypes, selectedContentTypes, facetFilters, limit, offset])

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

  // Toggle content type filter
  const toggleContentType = (type: string) => {
    setSelectedContentTypes(prev =>
      prev.includes(type)
        ? prev.filter(t => t !== type)
        : [...prev, type]
    )
    setOffset(0) // Reset pagination
  }

  // Clear all filters
  const clearFilters = () => {
    setSelectedSourceTypes([])
    setSelectedContentTypes([])
    setFacetFilters({})
    setOffset(0)
  }

  // Update facet filter values
  const updateFacetFilter = (facetName: string, values: string[]) => {
    setFacetFilters(prev => {
      if (values.length === 0) {
        const { [facetName]: _, ...rest } = prev
        return rest
      }
      return { ...prev, [facetName]: values }
    })
    setOffset(0)
  }

  // Get count for a source type from facets
  const getSourceTypeCount = (type: string): number | null => {
    if (!facets?.source_type) return null
    const bucket = facets.source_type.buckets.find(b => b.value === type)
    return bucket?.count ?? 0
  }

  // Format content type for display
  const formatContentType = (contentType: string): string => {
    // Extract file extension or type from MIME type
    if (contentType.includes('/')) {
      const subtype = contentType.split('/')[1]
      // Handle common types
      if (subtype === 'pdf') return 'PDF'
      if (subtype === 'html') return 'HTML'
      if (subtype === 'plain') return 'TXT'
      if (subtype === 'markdown' || subtype === 'x-markdown') return 'Markdown'
      if (subtype.includes('word') || subtype === 'docx') return 'DOCX'
      if (subtype.includes('excel') || subtype === 'xlsx') return 'XLSX'
      if (subtype.includes('powerpoint') || subtype === 'pptx') return 'PPTX'
      if (subtype.includes('json')) return 'JSON'
      if (subtype.includes('xml')) return 'XML'
      return subtype.toUpperCase()
    }
    return contentType
  }

  // Pagination
  const totalPages = results ? Math.ceil(results.total / limit) : 0
  const currentPage = Math.floor(offset / limit) + 1

  const goToPage = (page: number) => {
    setOffset((page - 1) * limit)
  }

  // Navigate to detail page - routes to appropriate page based on source type
  // Note: source_type values are display names from the backend's display_type_mapper
  const handleResultClick = (hit: SearchHit) => {
    // Route Salesforce records to their specific pages
    if (hit.source_type === 'Account') {
      router.push(`/salesforce/accounts/${hit.asset_id}`)
    } else if (hit.source_type === 'Contact') {
      router.push(`/salesforce/contacts/${hit.asset_id}`)
    } else if (hit.source_type === 'Opportunity') {
      router.push(`/salesforce/opportunities/${hit.asset_id}`)
    } else if (hit.source_type === 'AG Forecast' || hit.source_type === 'APFS Forecast' || hit.source_type === 'State Forecast') {
      // Route forecast records to forecast detail page
      // Backend sends display names: "AG Forecast", "APFS Forecast", "State Forecast"
      router.push(`/forecasts/${hit.asset_id}`)
    } else {
      // Default to asset page for documents
      router.push(`/assets/${hit.asset_id}`)
    }
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

        {/* Search Mode Toggle */}
        <div className="mb-6">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-gray-500 dark:text-gray-400">Mode:</span>
            <div className="inline-flex rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-1">
              {(['keyword', 'hybrid', 'semantic'] as const).map((mode) => (
                <button
                  key={mode}
                  disabled={isLoading}
                  onClick={() => {
                    setSearchMode(mode)
                    setOffset(0)
                  }}
                  className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
                    searchMode === mode
                      ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-300'
                      : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200'
                  } ${isLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  {mode === 'keyword' && 'Keyword'}
                  {mode === 'semantic' && 'Semantic'}
                  {mode === 'hybrid' && 'Hybrid'}
                </button>
              ))}
            </div>
            <span className="text-xs text-gray-400 dark:text-gray-500">
              {searchMode === 'keyword' && '(exact text matching)'}
              {searchMode === 'semantic' && '(finds related content)'}
              {searchMode === 'hybrid' && '(keyword + semantic combined)'}
            </span>
          </div>
        </div>

        {/* Filters */}
        <div className="mb-6 space-y-4">
          {/* Source Type Filters */}
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-gray-500 dark:text-gray-400">Source:</span>
            {Object.entries(sourceTypeFilterConfig).map(([type, config]) => {
              const count = getSourceTypeCount(type)
              const isSelected = selectedSourceTypes.includes(type)
              return (
                <button
                  key={type}
                  onClick={() => toggleSourceType(type)}
                  disabled={isLoading}
                  className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium transition-all ${
                    isSelected
                      ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400 ring-2 ring-indigo-500'
                      : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
                  } ${isLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  {config.icon}
                  <span>{config.name}</span>
                  {count !== null && (
                    <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                      isSelected
                        ? 'bg-indigo-200 dark:bg-indigo-800 text-indigo-800 dark:text-indigo-200'
                        : 'bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400'
                    }`}>
                      {count}
                    </span>
                  )}
                </button>
              )
            })}
            {(selectedSourceTypes.length > 0 || selectedContentTypes.length > 0 || Object.keys(facetFilters).length > 0) && (
              <button
                onClick={clearFilters}
                disabled={isLoading}
                className={`text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300 underline ${isLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                Clear filters
              </button>
            )}
          </div>

          {/* Facet Filters (Agency, Set-Aside) */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <FacetAutocomplete
              facetName="agency"
              label="Agency"
              selectedValues={facetFilters.agency || []}
              onSelectionChange={(values) => updateFacetFilter('agency', values)}
              placeholder="Search agencies (e.g., DHS, GSA)..."
              disabled={isLoading}
            />
            <FacetAutocomplete
              facetName="set_aside"
              label="Set-Aside"
              selectedValues={facetFilters.set_aside || []}
              onSelectionChange={(values) => updateFacetFilter('set_aside', values)}
              placeholder="Search set-asides (e.g., SBA, 8(a))..."
              disabled={isLoading}
            />
          </div>

          {/* Content Type Filters */}
          {facets?.content_type && facets.content_type.buckets.length > 0 && (
            <div className="flex flex-wrap items-start gap-3">
              <span className="text-sm text-gray-500 dark:text-gray-400 pt-1.5">Content Type:</span>
              <div className="flex flex-wrap items-center gap-2">
                {(showAllContentTypes
                  ? facets.content_type.buckets
                  : facets.content_type.buckets.slice(0, CONTENT_TYPE_INITIAL_COUNT)
                ).map((bucket) => {
                  const isSelected = selectedContentTypes.includes(bucket.value)
                  return (
                    <button
                      key={bucket.value}
                      onClick={() => toggleContentType(bucket.value)}
                      disabled={isLoading}
                      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-all border ${
                        isSelected
                          ? 'bg-indigo-50 text-indigo-700 border-indigo-300 dark:bg-indigo-900/30 dark:text-indigo-400 dark:border-indigo-700'
                          : 'bg-white text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                      } ${isLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      {isSelected && <Check className="w-3 h-3" />}
                      <span>{formatContentType(bucket.value)}</span>
                      <span className={`text-xs ${
                        isSelected
                          ? 'text-indigo-500 dark:text-indigo-300'
                          : 'text-gray-400 dark:text-gray-500'
                      }`}>
                        ({bucket.count})
                      </span>
                    </button>
                  )
                })}
                {facets.content_type.buckets.length > CONTENT_TYPE_INITIAL_COUNT && (
                  <button
                    onClick={() => setShowAllContentTypes(!showAllContentTypes)}
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 transition-colors"
                  >
                    {showAllContentTypes ? (
                      <>
                        <ChevronUp className="w-3 h-3" />
                        Show less
                      </>
                    ) : (
                      <>
                        <ChevronDown className="w-3 h-3" />
                        Show {facets.content_type.buckets.length - CONTENT_TYPE_INITIAL_COUNT} more
                      </>
                    )}
                  </button>
                )}
              </div>
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
                Enter a search query to find documents across uploads, SharePoint, web scrapes, SAM.gov, and Salesforce CRM.
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
              const sourceConfig = sourceTypeDisplayConfig[hit.source_type || ''] || {
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
                        {hit.created_at && formatDate(hit.created_at)}
                      </span>
                      <span className="text-indigo-500 dark:text-indigo-400 font-medium">
                        {Math.min(100, hit.score).toFixed(0)}% match
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
                  disabled={currentPage === 1 || isLoading}
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
                  disabled={currentPage === totalPages || isLoading}
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

'use client'

import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { samApi, connectionsApi, SamNoticeWithSolicitation, SamNoticeListParams } from '@/lib/api'
import { formatDate as formatDateUtil } from '@/lib/date-utils'
import { Button } from '@/components/ui/Button'
import SamNavigation from '@/components/sam/SamNavigation'
import SamConnectionRequired from '@/components/sam/SamConnectionRequired'
import { NoticeTypeBadge } from '@/components/sam/SamStatusBadge'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  FileText,
  RefreshCw,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Filter,
  X,
  Calendar,
  Building2,
  ExternalLink,
  Search,
  ChevronUp,
  ChevronDown,
  ArrowUpDown,
  Clock,
  Tag,
  CheckSquare,
  Square,
  Sparkles,
  Type,
} from 'lucide-react'

// Sort types
type SortColumn = 'type' | 'title' | 'agency' | 'solicitation_number' | 'posted' | 'deadline'
type SortDirection = 'asc' | 'desc'

// Search mode
type SearchMode = 'keyword' | 'semantic'

// Timeframe options
type TimeframeFilter = 'all' | '24h' | '7d' | '30d'

// Notice type display names
const NOTICE_TYPE_LABELS: Record<string, string> = {
  'o': 'Solicitation',
  'p': 'Presolicitation',
  'k': 'Combined Synopsis/Solicitation',
  'r': 'Sources Sought',
  's': 'Special Notice',
  'g': 'Sale of Surplus Property',
  'a': 'Award Notice',
  'u': 'Justification (J&A)',
  'i': 'Intent to Bundle',
  'Combined Synopsis/Solicitation': 'Combined Synopsis/Solicitation',
  'Solicitation': 'Solicitation',
  'Presolicitation': 'Presolicitation',
  'Sources Sought': 'Sources Sought',
  'Special Notice': 'Special Notice',
  'Award Notice': 'Award Notice',
  'Sale of Surplus Property': 'Sale of Surplus Property',
  'Justification': 'Justification (J&A)',
  'Intent to Bundle': 'Intent to Bundle',
}

// Helper to normalize notice type for comparison
function normalizeNoticeType(type: string): string {
  return NOTICE_TYPE_LABELS[type] || type
}

// Helper to check if a date is within a timeframe
function isWithinTimeframe(dateStr: string | null, timeframe: TimeframeFilter): boolean {
  if (!dateStr || timeframe === 'all') return true
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const hours = diff / (1000 * 60 * 60)

  switch (timeframe) {
    case '24h': return hours <= 24
    case '7d': return hours <= 24 * 7
    case '30d': return hours <= 24 * 30
    default: return true
  }
}

export default function SamNoticesPage() {
  return (
    <ProtectedRoute>
      <SamNoticesContent />
    </ProtectedRoute>
  )
}

function SamNoticesContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { token } = useAuth()

  // Ref to track latest request and ignore stale responses
  const loadRequestId = useRef(0)
  // Debounce timer for search
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // State
  const [allNotices, setAllNotices] = useState<SamNoticeWithSolicitation[]>([]) // All notices for facet counts
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [hasConnection, setHasConnection] = useState<boolean | null>(null)

  // Filters and Search
  const [searchQuery, setSearchQuery] = useState(searchParams.get('q') || '')
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState(searchParams.get('q') || '')
  const [searchMode, setSearchMode] = useState<SearchMode>('keyword')
  const [selectedAgencies, setSelectedAgencies] = useState<Set<string>>(new Set())
  const [selectedNoticeTypes, setSelectedNoticeTypes] = useState<Set<string>>(new Set())
  const [timeframeFilter, setTimeframeFilter] = useState<TimeframeFilter>('all')
  const [page, setPage] = useState(1)
  const pageSize = 25

  // Semantic search results (separate from all notices for faceting)
  const [semanticResults, setSemanticResults] = useState<SamNoticeWithSolicitation[]>([])
  const [isSemanticSearch, setIsSemanticSearch] = useState(false)

  // Sorting
  const [sortColumn, setSortColumn] = useState<SortColumn>('posted')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')

  // Sort handler
  const handleSort = (column: SortColumn) => {
    if (sortColumn === column) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortColumn(column)
      setSortDirection('asc')
    }
  }

  // Check for SAM.gov connection
  const checkConnection = useCallback(async () => {
    if (!token) return

    try {
      const response = await connectionsApi.listConnections(token)
      const samConnection = response.connections.find(
        c => c.connection_type === 'sam_gov' && c.is_active
      )
      setHasConnection(!!samConnection)
    } catch (err) {
      setHasConnection(false)
    }
  }, [token])

  // Debounce search query updates
  useEffect(() => {
    if (searchDebounceRef.current) {
      clearTimeout(searchDebounceRef.current)
    }
    searchDebounceRef.current = setTimeout(() => {
      setDebouncedSearchQuery(searchQuery)
    }, 300) // 300ms debounce

    return () => {
      if (searchDebounceRef.current) {
        clearTimeout(searchDebounceRef.current)
      }
    }
  }, [searchQuery])

  // Load all notices (for facet counts and filtering)
  const loadNotices = useCallback(async () => {
    if (!token) return

    // Track this request to ignore stale responses
    const requestId = ++loadRequestId.current

    setIsLoading(true)
    setError('')
    setIsSemanticSearch(false)

    try {
      // Always load base notices for facet counts
      const params: SamNoticeListParams = {
        limit: 500,
        offset: 0,
      }
      // Only use keyword filter in keyword mode
      if (debouncedSearchQuery && searchMode === 'keyword') {
        params.keyword = debouncedSearchQuery
      }

      const data = await samApi.listAllNotices(token, params)

      // Ignore stale responses from previous requests
      if (requestId !== loadRequestId.current) {
        return
      }

      setAllNotices(data.items)
      setTotal(data.total)

      // If semantic mode with a query, also do semantic search
      if (searchMode === 'semantic' && debouncedSearchQuery.trim()) {
        const semanticData = await samApi.searchSam(token, {
          query: debouncedSearchQuery,
          source_types: ['sam_notice'],
          limit: 100,
        })

        // Ignore stale responses from previous requests
        if (requestId !== loadRequestId.current) {
          return
        }

        // For semantic search, fetch full notice details for each hit
        // Build a map of notice IDs from the full list for quick lookup
        const noticeMap = new Map(data.items.map(n => [n.id, n]))

        // Order results by semantic relevance (preserve order from semantic results)
        const orderedNotices: SamNoticeWithSolicitation[] = []
        for (const hit of semanticData.hits) {
          const notice = noticeMap.get(hit.asset_id)
          if (notice) {
            orderedNotices.push(notice)
          }
        }

        // Set both states together to ensure consistent rendering
        setIsSemanticSearch(true)
        setSemanticResults(orderedNotices)
      } else {
        setSemanticResults([])
      }
    } catch (err: any) {
      // Ignore errors from stale requests
      if (requestId !== loadRequestId.current) {
        return
      }
      setError(err.message || 'Failed to load notices')
    } finally {
      // Only update loading state for current request
      if (requestId === loadRequestId.current) {
        setIsLoading(false)
      }
    }
  }, [token, debouncedSearchQuery, searchMode])

  useEffect(() => {
    if (token) {
      checkConnection()
    }
  }, [token, checkConnection])

  useEffect(() => {
    if (token && hasConnection === true) {
      loadNotices()
    } else if (hasConnection === false) {
      setIsLoading(false)
    }
  }, [token, hasConnection, loadNotices])

  // Show connection required screen if no SAM.gov connection
  if (hasConnection === false) {
    return <SamConnectionRequired />
  }

  // Compute facet counts
  const facetCounts = useMemo(() => {
    const agencies: Record<string, number> = {}
    const noticeTypes: Record<string, number> = {}
    const timeframes = { '24h': 0, '7d': 0, '30d': 0 }

    for (const notice of allNotices) {
      // Agency counts
      const agency = notice.agency_name || 'Unknown'
      agencies[agency] = (agencies[agency] || 0) + 1

      // Notice type counts
      const type = normalizeNoticeType(notice.notice_type)
      noticeTypes[type] = (noticeTypes[type] || 0) + 1

      // Timeframe counts
      if (isWithinTimeframe(notice.posted_date, '24h')) timeframes['24h']++
      if (isWithinTimeframe(notice.posted_date, '7d')) timeframes['7d']++
      if (isWithinTimeframe(notice.posted_date, '30d')) timeframes['30d']++
    }

    // Sort agencies by count
    const sortedAgencies = Object.entries(agencies)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10) // Top 10 agencies

    // Sort notice types by count
    const sortedNoticeTypes = Object.entries(noticeTypes)
      .sort((a, b) => b[1] - a[1])

    return {
      agencies: sortedAgencies,
      noticeTypes: sortedNoticeTypes,
      timeframes,
      total: allNotices.length,
    }
  }, [allNotices])

  // Filter and sort notices
  const filteredAndSortedNotices = useMemo(() => {
    // Use semantic results if in semantic search mode (even if empty - means no matches)
    let result = isSemanticSearch
      ? [...semanticResults]
      : [...allNotices]

    // Filter by selected agencies
    if (selectedAgencies.size > 0) {
      result = result.filter(n => selectedAgencies.has(n.agency_name || 'Unknown'))
    }

    // Filter by selected notice types
    if (selectedNoticeTypes.size > 0) {
      result = result.filter(n => selectedNoticeTypes.has(normalizeNoticeType(n.notice_type)))
    }

    // Filter by timeframe
    if (timeframeFilter !== 'all') {
      result = result.filter(n => isWithinTimeframe(n.posted_date, timeframeFilter))
    }

    // Sort (skip sorting for semantic results to preserve relevance order)
    if (!isSemanticSearch || semanticResults.length === 0) {
      result.sort((a, b) => {
        let comparison = 0

        switch (sortColumn) {
          case 'type':
            comparison = (a.notice_type || '').localeCompare(b.notice_type || '')
            break
          case 'title':
            comparison = (a.title || '').localeCompare(b.title || '')
            break
          case 'agency':
            comparison = (a.agency_name || '').localeCompare(b.agency_name || '')
            break
          case 'solicitation_number':
            comparison = (a.solicitation_number || '').localeCompare(b.solicitation_number || '')
            break
          case 'posted': {
            const aDate = a.posted_date ? new Date(a.posted_date).getTime() : 0
            const bDate = b.posted_date ? new Date(b.posted_date).getTime() : 0
            comparison = aDate - bDate
            break
          }
          case 'deadline': {
            const aDate = a.response_deadline ? new Date(a.response_deadline).getTime() : 0
            const bDate = b.response_deadline ? new Date(b.response_deadline).getTime() : 0
            comparison = aDate - bDate
            break
          }
        }

        return sortDirection === 'asc' ? comparison : -comparison
      })
    }

    return result
  }, [allNotices, semanticResults, isSemanticSearch, selectedAgencies, selectedNoticeTypes, timeframeFilter, sortColumn, sortDirection])

  // Paginate
  const paginatedNotices = useMemo(() => {
    const start = (page - 1) * pageSize
    return filteredAndSortedNotices.slice(start, start + pageSize)
  }, [filteredAndSortedNotices, page, pageSize])

  const totalPages = Math.ceil(filteredAndSortedNotices.length / pageSize)

  // Toggle agency filter
  const toggleAgency = (agency: string) => {
    const newSelected = new Set(selectedAgencies)
    if (newSelected.has(agency)) {
      newSelected.delete(agency)
    } else {
      newSelected.add(agency)
    }
    setSelectedAgencies(newSelected)
    setPage(1)
  }

  // Toggle notice type filter
  const toggleNoticeType = (type: string) => {
    const newSelected = new Set(selectedNoticeTypes)
    if (newSelected.has(type)) {
      newSelected.delete(type)
    } else {
      newSelected.add(type)
    }
    setSelectedNoticeTypes(newSelected)
    setPage(1)
  }

  // Set timeframe filter
  const handleTimeframeChange = (timeframe: TimeframeFilter) => {
    setTimeframeFilter(timeframe === timeframeFilter ? 'all' : timeframe)
    setPage(1)
  }

  const clearFilters = () => {
    setSearchQuery('')
    setSelectedAgencies(new Set())
    setSelectedNoticeTypes(new Set())
    setTimeframeFilter('all')
    setPage(1)
  }

  const hasFilters = searchQuery || selectedAgencies.size > 0 || selectedNoticeTypes.size > 0 || timeframeFilter !== 'all'

  // Use formatDate from date-utils for consistent EST display
  const formatDate = (dateStr: string | null) => formatDateUtil(dateStr)

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 text-white shadow-lg shadow-cyan-500/25">
                <FileText className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  All Notices
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  {filteredAndSortedNotices.length.toLocaleString()} of {total.toLocaleString()} notices
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                onClick={loadNotices}
                disabled={isLoading}
                className="gap-2"
              >
                <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <SamNavigation />

        {/* Search Bar */}
        <div className="mb-6 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
          <div className="flex gap-4">
            {/* Search Mode Toggle */}
            <div className="flex items-center bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
              <button
                onClick={() => setSearchMode('keyword')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  searchMode === 'keyword'
                    ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow-sm'
                    : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                }`}
                title="Keyword search - exact text matching"
              >
                <Type className="w-4 h-4" />
                <span className="hidden sm:inline">Keyword</span>
              </button>
              <button
                onClick={() => setSearchMode('semantic')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  searchMode === 'semantic'
                    ? 'bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300 shadow-sm'
                    : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                }`}
                title="Semantic search - AI-powered meaning-based search"
              >
                <Sparkles className="w-4 h-4" />
                <span className="hidden sm:inline">Semantic</span>
              </button>
            </div>

            <div className="flex-1 relative">
              {searchMode === 'semantic' ? (
                <Sparkles className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-purple-500" />
              ) : (
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              )}
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value)
                  setPage(1)
                }}
                placeholder={searchMode === 'semantic'
                  ? "Search by meaning... e.g., 'cybersecurity contracts for defense'"
                  : "Search by title, solicitation number, or description..."
                }
                className={`w-full pl-10 pr-4 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 bg-white dark:bg-gray-900 text-gray-900 dark:text-white ${
                  searchMode === 'semantic'
                    ? 'border-purple-300 dark:border-purple-700 focus:ring-purple-500'
                    : 'border-gray-200 dark:border-gray-700 focus:ring-indigo-500'
                }`}
              />
            </div>
            {hasFilters && (
              <Button
                variant="secondary"
                onClick={clearFilters}
                className="gap-1"
              >
                <X className="w-4 h-4" />
                Clear All
              </Button>
            )}
          </div>
          {searchMode === 'semantic' && (
            <p className="mt-2 text-xs text-purple-600 dark:text-purple-400">
              <Sparkles className="w-3 h-3 inline mr-1" />
              Semantic search finds related content even without exact keyword matches
            </p>
          )}
        </div>

        {/* Quick Filter Panels */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
          {/* Timeframe Filter */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Clock className="w-4 h-4 text-gray-500 dark:text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Posted</h3>
            </div>
            <div className="flex flex-wrap gap-2">
              {[
                { value: '24h' as TimeframeFilter, label: 'Last 24 Hours', count: facetCounts.timeframes['24h'] },
                { value: '7d' as TimeframeFilter, label: 'Last 7 Days', count: facetCounts.timeframes['7d'] },
                { value: '30d' as TimeframeFilter, label: 'Last 30 Days', count: facetCounts.timeframes['30d'] },
              ].map(({ value, label, count }) => (
                <button
                  key={value}
                  onClick={() => handleTimeframeChange(value)}
                  className={`
                    flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors
                    ${timeframeFilter === value
                      ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400 ring-2 ring-indigo-500/20'
                      : 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                    }
                  `}
                >
                  {label}
                  <span className={`
                    px-1.5 py-0.5 rounded text-xs font-medium
                    ${timeframeFilter === value
                      ? 'bg-indigo-200 dark:bg-indigo-800'
                      : 'bg-gray-200 dark:bg-gray-600'
                    }
                  `}>
                    {count}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Notice Type Filter */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Tag className="w-4 h-4 text-gray-500 dark:text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Notice Type</h3>
              {selectedNoticeTypes.size > 0 && (
                <button
                  onClick={() => setSelectedNoticeTypes(new Set())}
                  className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300 ml-auto"
                >
                  Clear
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto">
              {facetCounts.noticeTypes.map(([type, count]) => (
                <button
                  key={type}
                  onClick={() => toggleNoticeType(type)}
                  className={`
                    flex items-center gap-1.5 px-2 py-1 rounded text-xs transition-colors
                    ${selectedNoticeTypes.has(type)
                      ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
                      : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'
                    }
                  `}
                >
                  {selectedNoticeTypes.has(type) ? (
                    <CheckSquare className="w-3 h-3" />
                  ) : (
                    <Square className="w-3 h-3" />
                  )}
                  <span className="truncate max-w-[120px]">{type}</span>
                  <span className={`
                    px-1 rounded text-[10px] font-medium
                    ${selectedNoticeTypes.has(type)
                      ? 'bg-emerald-200 dark:bg-emerald-800'
                      : 'bg-gray-200 dark:bg-gray-600'
                    }
                  `}>
                    {count}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Agency Filter */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Building2 className="w-4 h-4 text-gray-500 dark:text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Top Agencies</h3>
              {selectedAgencies.size > 0 && (
                <button
                  onClick={() => setSelectedAgencies(new Set())}
                  className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300 ml-auto"
                >
                  Clear
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto">
              {facetCounts.agencies.map(([agency, count]) => (
                <button
                  key={agency}
                  onClick={() => toggleAgency(agency)}
                  className={`
                    flex items-center gap-1.5 px-2 py-1 rounded text-xs transition-colors
                    ${selectedAgencies.has(agency)
                      ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400'
                      : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'
                    }
                  `}
                >
                  {selectedAgencies.has(agency) ? (
                    <CheckSquare className="w-3 h-3" />
                  ) : (
                    <Square className="w-3 h-3" />
                  )}
                  <span className="truncate max-w-[150px]">{agency}</span>
                  <span className={`
                    px-1 rounded text-[10px] font-medium
                    ${selectedAgencies.has(agency)
                      ? 'bg-purple-200 dark:bg-purple-800'
                      : 'bg-gray-200 dark:bg-gray-600'
                    }
                  `}>
                    {count}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Active Filters Display */}
        {hasFilters && (
          <div className="mb-4 flex items-center gap-2 flex-wrap">
            <span className="text-sm text-gray-500 dark:text-gray-400">Filters:</span>
            {timeframeFilter !== 'all' && (
              <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400">
                {timeframeFilter === '24h' ? 'Last 24 Hours' : timeframeFilter === '7d' ? 'Last 7 Days' : 'Last 30 Days'}
                <button onClick={() => setTimeframeFilter('all')} className="ml-1 hover:text-indigo-900 dark:hover:text-indigo-200">×</button>
              </span>
            )}
            {Array.from(selectedNoticeTypes).map(type => (
              <span key={type} className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
                {type}
                <button onClick={() => toggleNoticeType(type)} className="ml-1 hover:text-emerald-900 dark:hover:text-emerald-200">×</button>
              </span>
            ))}
            {Array.from(selectedAgencies).map(agency => (
              <span key={agency} className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400 max-w-[200px]">
                <span className="truncate">{agency}</span>
                <button onClick={() => toggleAgency(agency)} className="ml-1 hover:text-purple-900 dark:hover:text-purple-200 flex-shrink-0">×</button>
              </span>
            ))}
            <button
              onClick={clearFilters}
              className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
            >
              Clear all
            </button>
          </div>
        )}

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
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-blue-500 animate-spin" />
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading notices...</p>
          </div>
        ) : paginatedNotices.length === 0 ? (
          <div className="text-center py-16">
            <FileText className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <p className="text-gray-500 dark:text-gray-400">
              {hasFilters ? 'No notices match your filters.' : 'No notices found.'}
            </p>
          </div>
        ) : (
          <>
            {/* Table */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700">
                      <SortableHeader
                        label="Type"
                        column="type"
                        currentColumn={sortColumn}
                        direction={sortDirection}
                        onSort={handleSort}
                      />
                      <SortableHeader
                        label="Title"
                        column="title"
                        currentColumn={sortColumn}
                        direction={sortDirection}
                        onSort={handleSort}
                      />
                      <SortableHeader
                        label="Agency"
                        column="agency"
                        currentColumn={sortColumn}
                        direction={sortDirection}
                        onSort={handleSort}
                      />
                      <SortableHeader
                        label="Notice ID"
                        column="solicitation_number"
                        currentColumn={sortColumn}
                        direction={sortDirection}
                        onSort={handleSort}
                      />
                      <SortableHeader
                        label="Posted"
                        column="posted"
                        currentColumn={sortColumn}
                        direction={sortDirection}
                        onSort={handleSort}
                      />
                      <SortableHeader
                        label="Deadline"
                        column="deadline"
                        currentColumn={sortColumn}
                        direction={sortDirection}
                        onSort={handleSort}
                      />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                    {paginatedNotices.map((notice) => (
                      <tr
                        key={notice.id}
                        onClick={() => router.push(`/sam/notices/${notice.id}`)}
                        className="hover:bg-gray-50 dark:hover:bg-gray-750 cursor-pointer transition-colors"
                      >
                        <td className="px-4 py-3">
                          <NoticeTypeBadge type={notice.notice_type} />
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-sm font-medium text-gray-900 dark:text-white truncate max-w-[300px]">
                            {notice.title || 'Untitled'}
                          </p>
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-sm text-gray-600 dark:text-gray-400 truncate max-w-[200px]">
                            {notice.agency_name || '-'}
                          </p>
                        </td>
                        <td className="px-4 py-3">
                          {notice.solicitation_number ? (
                            notice.solicitation_id ? (
                              <Link
                                href={`/sam/solicitations/${notice.solicitation_id}`}
                                onClick={(e) => e.stopPropagation()}
                                className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline font-mono"
                              >
                                {notice.solicitation_number}
                              </Link>
                            ) : (
                              <span className="text-sm text-gray-600 dark:text-gray-400 font-mono">
                                {notice.solicitation_number}
                              </span>
                            )
                          ) : (
                            <span className="text-sm text-gray-400">-</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-sm text-gray-600 dark:text-gray-400">
                            {formatDate(notice.posted_date)}
                          </p>
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-sm text-gray-600 dark:text-gray-400">
                            {formatDate(notice.response_deadline)}
                          </p>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between mt-4">
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Showing {((page - 1) * pageSize) + 1} - {Math.min(page * pageSize, filteredAndSortedNotices.length)} of {filteredAndSortedNotices.length}
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="gap-1"
                  >
                    <ChevronLeft className="w-4 h-4" />
                    Previous
                  </Button>
                  <span className="text-sm text-gray-600 dark:text-gray-400 px-4">
                    Page {page} of {totalPages}
                  </span>
                  <Button
                    variant="secondary"
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    className="gap-1"
                  >
                    Next
                    <ChevronRight className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// Sortable Header Component
interface SortableHeaderProps {
  label: string
  column: SortColumn
  currentColumn: SortColumn
  direction: SortDirection
  onSort: (column: SortColumn) => void
}

function SortableHeader({ label, column, currentColumn, direction, onSort }: SortableHeaderProps) {
  const isActive = currentColumn === column

  return (
    <th
      className="text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider px-4 py-3 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors select-none"
      onClick={() => onSort(column)}
    >
      <div className="flex items-center gap-1.5">
        <span>{label}</span>
        <span className="flex flex-col">
          {isActive ? (
            direction === 'asc' ? (
              <ChevronUp className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400" />
            )
          ) : (
            <ArrowUpDown className="w-3.5 h-3.5 text-gray-400" />
          )}
        </span>
      </div>
    </th>
  )
}

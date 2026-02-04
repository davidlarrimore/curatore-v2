'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { functionsApi, connectionsApi, FunctionExecuteResult } from '@/lib/api'
import { formatDate as formatDateUtil, formatCompact } from '@/lib/date-utils'
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
  X,
  Calendar,
  Building2,
  Search,
  ChevronUp,
  ChevronDown,
  ArrowUpDown,
  RotateCcw,
  Clock,
  Activity,
  Briefcase,
  FileSearch,
  Bell,
  Award,
  Scale,
  Package,
  Layers,
} from 'lucide-react'

// Notice type from query_notifications function
interface Notice {
  id: string
  sam_notice_id: string
  notice_type: string
  notice_type_label: string
  version_number?: number
  title: string
  posted_date: string | null
  response_deadline: string | null
  description?: string
  is_standalone: boolean
  solicitation_id: string | null
  has_changes_summary: boolean
  changes_summary?: string
  ui_link?: string
  sam_url?: string
  // Standalone notice fields
  naics_code?: string
  psc_code?: string
  set_aside_code?: string
  agency_name?: string
  bureau_name?: string
  office_name?: string
}

// Sort types
type SortColumn = 'type' | 'title' | 'agency' | 'posted' | 'deadline'
type SortDirection = 'asc' | 'desc'

// Date filter options
type DateFilter = 'today' | '24h' | '1week' | '30days' | null

// Notice type tabs with icons (matching Job Manager pattern)
const NOTICE_TYPE_TABS = [
  { value: 'all', label: 'All', icon: Activity },
  { value: 'o', label: 'Solicitation', icon: Briefcase },
  { value: 'k', label: 'Combined', icon: Layers },
  { value: 'p', label: 'Presolicitation', icon: FileSearch },
  { value: 'r', label: 'Sources Sought', icon: Search },
  { value: 's', label: 'Special', icon: Bell },
  { value: 'a', label: 'Award', icon: Award },
  { value: 'u', label: 'J&A', icon: Scale },
  { value: 'g', label: 'Surplus', icon: Package },
]

// Get icon for notice type
function getNoticeTypeIcon(type: string): React.ComponentType<{ className?: string }> {
  const tab = NOTICE_TYPE_TABS.find(t => t.value === type)
  return tab?.icon || FileText
}

// Check if a date is within range
function isWithinDays(dateStr: string | null, days: number): boolean {
  if (!dateStr) return false
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  return diff >= 0 && diff < days * 24 * 60 * 60 * 1000
}

function isToday(dateStr: string | null): boolean {
  if (!dateStr) return false
  const date = new Date(dateStr)
  const now = new Date()
  return date.toDateString() === now.toDateString()
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

  // State
  const [notices, setNotices] = useState<Notice[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [hasConnection, setHasConnection] = useState<boolean | null>(null)

  // Search and server-side filters
  const [searchQuery, setSearchQuery] = useState(searchParams.get('q') || '')
  const [pendingSearch, setPendingSearch] = useState(searchQuery)

  // Client-side filters (quick filters)
  const [typeFilter, setTypeFilter] = useState('all')
  const [dateFilter, setDateFilter] = useState<DateFilter>(null)
  const [selectedAgencies, setSelectedAgencies] = useState<Set<string>>(new Set())

  // Sorting
  const [sortColumn, setSortColumn] = useState<SortColumn>('posted')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')

  // Pagination
  const [page, setPage] = useState(1)
  const pageSize = 50

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

  // Load notices using the query_notifications function
  const loadNotices = useCallback(async (silent = false) => {
    if (!token) return

    if (!silent) {
      setIsLoading(true)
    }
    setError('')

    try {
      // Build function params
      const params: Record<string, any> = {
        limit: 500, // Load enough for client-side filtering
        order_by: '-posted_date',
      }

      // Only add keyword if there's a search query
      if (searchQuery.trim()) {
        params.keyword = searchQuery.trim()
      }

      // Execute the query_notifications function
      const result: FunctionExecuteResult = await functionsApi.executeFunction(
        token,
        'query_notifications',
        params
      )

      if (result.status === 'success' && Array.isArray(result.data)) {
        setNotices(result.data)
      } else if (result.status === 'failed') {
        setError(result.error || result.message || 'Failed to load notices')
      }
    } catch (err: any) {
      if (!silent) {
        setError(err.message || 'Failed to load notices')
      }
    } finally {
      if (!silent) {
        setIsLoading(false)
      }
      setIsRefreshing(false)
    }
  }, [token, searchQuery])

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

  // Handle search submit
  const handleSearch = () => {
    setSearchQuery(pendingSearch)
    setPage(1)
  }

  // Handle refresh
  const handleRefresh = async () => {
    setIsRefreshing(true)
    await loadNotices()
  }

  // Compute stats for type tabs
  const typeStats = useMemo(() => {
    const stats: Record<string, number> = { all: notices.length }
    for (const notice of notices) {
      const type = notice.notice_type || 'unknown'
      stats[type] = (stats[type] || 0) + 1
    }
    return stats
  }, [notices])

  // Compute date stats
  const dateStats = useMemo(() => {
    const stats = {
      today: 0,
      '24h': 0,
      '1week': 0,
      '30days': 0,
    }

    // Filter by type first if selected
    const noticesInType = typeFilter === 'all'
      ? notices
      : notices.filter(n => n.notice_type === typeFilter)

    for (const notice of noticesInType) {
      if (isToday(notice.posted_date)) stats.today++
      if (isWithinDays(notice.posted_date, 1)) stats['24h']++
      if (isWithinDays(notice.posted_date, 7)) stats['1week']++
      if (isWithinDays(notice.posted_date, 30)) stats['30days']++
    }

    return stats
  }, [notices, typeFilter])

  // Extract unique agencies from loaded notices
  const uniqueAgencies = useMemo(() => {
    const agencies = new Map<string, number>()

    // Only count agencies in filtered notices
    const noticesInType = typeFilter === 'all'
      ? notices
      : notices.filter(n => n.notice_type === typeFilter)

    noticesInType.forEach(notice => {
      if (notice.agency_name) {
        agencies.set(notice.agency_name, (agencies.get(notice.agency_name) || 0) + 1)
      }
    })

    // Sort by count (most common first), take top 8
    return Array.from(agencies.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
  }, [notices, typeFilter])

  // Apply filters and sort
  const filteredAndSortedNotices = useMemo(() => {
    let filtered = [...notices]

    // Apply type filter
    if (typeFilter !== 'all') {
      filtered = filtered.filter(n => n.notice_type === typeFilter)
    }

    // Apply date filter
    if (dateFilter) {
      filtered = filtered.filter(n => {
        switch (dateFilter) {
          case 'today':
            return isToday(n.posted_date)
          case '24h':
            return isWithinDays(n.posted_date, 1)
          case '1week':
            return isWithinDays(n.posted_date, 7)
          case '30days':
            return isWithinDays(n.posted_date, 30)
          default:
            return true
        }
      })
    }

    // Apply agency filter (multi-select)
    if (selectedAgencies.size > 0) {
      filtered = filtered.filter(n => n.agency_name && selectedAgencies.has(n.agency_name))
    }

    // Sort
    return filtered.sort((a, b) => {
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
  }, [notices, typeFilter, dateFilter, selectedAgencies, sortColumn, sortDirection])

  // Paginated notices
  const paginatedNotices = useMemo(() => {
    const start = (page - 1) * pageSize
    return filteredAndSortedNotices.slice(start, start + pageSize)
  }, [filteredAndSortedNotices, page, pageSize])

  const totalPages = Math.ceil(filteredAndSortedNotices.length / pageSize)

  // Handle type filter change
  const handleTypeChange = (value: string) => {
    setTypeFilter(value)
    setPage(1)
  }

  // Handle date filter change
  const handleDateChange = (value: DateFilter) => {
    setDateFilter(prev => prev === value ? null : value)
    setPage(1)
  }

  // Toggle agency filter
  const toggleAgencyFilter = (agency: string) => {
    setSelectedAgencies(prev => {
      const next = new Set(prev)
      if (next.has(agency)) {
        next.delete(agency)
      } else {
        next.add(agency)
      }
      return next
    })
    setPage(1)
  }

  // Clear quick filters
  const clearQuickFilters = () => {
    setTypeFilter('all')
    setDateFilter(null)
    setSelectedAgencies(new Set())
    setPage(1)
  }

  const hasQuickFilters = typeFilter !== 'all' || dateFilter !== null || selectedAgencies.size > 0

  // Show connection required screen if no SAM.gov connection
  if (hasConnection === false) {
    return <SamConnectionRequired />
  }

  // Use formatDate from date-utils for consistent EST display
  const formatDate = (dateStr: string | null) => formatDateUtil(dateStr)
  // Format posted date with time (HH:MM AM/PM EST)
  const formatPostedDate = (dateStr: string | null) => {
    const compact = formatCompact(dateStr)
    return compact === '-' ? '-' : `${compact} EST`
  }

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
                  {notices.length.toLocaleString()} notices across all searches
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                onClick={handleRefresh}
                disabled={isLoading || isRefreshing}
                className="gap-2"
              >
                <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
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
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                value={pendingSearch}
                onChange={(e) => setPendingSearch(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                placeholder="Search by title or description..."
                className="w-full pl-10 pr-4 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
              />
            </div>
            <Button onClick={handleSearch} disabled={isLoading}>
              Search
            </Button>
            {searchQuery && (
              <Button
                variant="secondary"
                onClick={() => {
                  setPendingSearch('')
                  setSearchQuery('')
                  setPage(1)
                }}
                className="gap-1"
              >
                <X className="w-4 h-4" />
                Clear
              </Button>
            )}
          </div>
        </div>

        {/* Notice Type Tabs (Job Manager style) */}
        <div className="mb-6">
          <div className="flex flex-wrap gap-2">
            {NOTICE_TYPE_TABS.map((tab) => {
              const Icon = tab.icon
              const isActive = typeFilter === tab.value
              const count = typeStats[tab.value] || 0

              return (
                <button
                  key={tab.value}
                  onClick={() => handleTypeChange(tab.value)}
                  className={`
                    flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors
                    ${isActive
                      ? 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400'
                      : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 border border-gray-200 dark:border-gray-700'
                    }
                  `}
                >
                  <Icon className="w-4 h-4" />
                  {tab.label}
                  {count > 0 && (
                    <span className={`
                      px-1.5 py-0.5 rounded-full text-xs
                      ${isActive
                        ? 'bg-cyan-200 dark:bg-cyan-800'
                        : 'bg-gray-100 dark:bg-gray-700'
                      }
                    `}>
                      {count}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        </div>

        {/* Date Filter Cards (Job Manager style stat cards) */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
          {/* Today */}
          <button
            onClick={() => handleDateChange('today')}
            className={`bg-white dark:bg-gray-800 rounded-xl border-2 p-4 transition-all ${
              dateFilter === 'today'
                ? 'border-indigo-500 ring-2 ring-indigo-500/20'
                : 'border-gray-200 dark:border-gray-700 hover:border-indigo-300 dark:hover:border-indigo-700'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-indigo-50 dark:bg-indigo-900/20 flex items-center justify-center">
                <Calendar className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
              </div>
              <div className="text-left">
                <p className="text-xs text-gray-500 dark:text-gray-400">Today</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{dateStats.today}</p>
              </div>
            </div>
          </button>

          {/* 24 Hours */}
          <button
            onClick={() => handleDateChange('24h')}
            className={`bg-white dark:bg-gray-800 rounded-xl border-2 p-4 transition-all ${
              dateFilter === '24h'
                ? 'border-blue-500 ring-2 ring-blue-500/20'
                : 'border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-700'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
                <Clock className="w-5 h-5 text-blue-600 dark:text-blue-400" />
              </div>
              <div className="text-left">
                <p className="text-xs text-gray-500 dark:text-gray-400">24 Hours</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{dateStats['24h']}</p>
              </div>
            </div>
          </button>

          {/* 1 Week */}
          <button
            onClick={() => handleDateChange('1week')}
            className={`bg-white dark:bg-gray-800 rounded-xl border-2 p-4 transition-all ${
              dateFilter === '1week'
                ? 'border-emerald-500 ring-2 ring-emerald-500/20'
                : 'border-gray-200 dark:border-gray-700 hover:border-emerald-300 dark:hover:border-emerald-700'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center">
                <Calendar className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
              </div>
              <div className="text-left">
                <p className="text-xs text-gray-500 dark:text-gray-400">1 Week</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{dateStats['1week']}</p>
              </div>
            </div>
          </button>

          {/* 30 Days */}
          <button
            onClick={() => handleDateChange('30days')}
            className={`bg-white dark:bg-gray-800 rounded-xl border-2 p-4 transition-all ${
              dateFilter === '30days'
                ? 'border-amber-500 ring-2 ring-amber-500/20'
                : 'border-gray-200 dark:border-gray-700 hover:border-amber-300 dark:hover:border-amber-700'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center">
                <Calendar className="w-5 h-5 text-amber-600 dark:text-amber-400" />
              </div>
              <div className="text-left">
                <p className="text-xs text-gray-500 dark:text-gray-400">30 Days</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{dateStats['30days']}</p>
              </div>
            </div>
          </button>
        </div>

        {/* Agency Quick Filters */}
        {uniqueAgencies.length > 0 && (
          <div className="mb-6 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm font-medium text-gray-700 dark:text-gray-300 flex items-center gap-2">
                <Building2 className="w-4 h-4" />
                Filter by Agency
              </p>
              {hasQuickFilters && (
                <button
                  onClick={clearQuickFilters}
                  className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 transition-colors"
                >
                  <RotateCcw className="w-3 h-3" />
                  Reset All Filters
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {uniqueAgencies.map(([agency, count]) => {
                const shortName = agency.length > 35 ? agency.substring(0, 32) + '...' : agency
                return (
                  <button
                    key={agency}
                    onClick={() => toggleAgencyFilter(agency)}
                    title={agency}
                    className={`px-3 py-1.5 text-xs font-medium rounded-full transition-colors ${
                      selectedAgencies.has(agency)
                        ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300 ring-1 ring-emerald-500'
                        : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'
                    }`}
                  >
                    {shortName}
                    <span className="ml-1.5 text-[10px] opacity-75">({count})</span>
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {/* Active Filters Display */}
        {hasQuickFilters && (
          <div className="mb-4 flex items-center gap-2 flex-wrap">
            <span className="text-sm text-gray-500 dark:text-gray-400">Filters:</span>
            {typeFilter !== 'all' && (
              <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400">
                {NOTICE_TYPE_TABS.find(t => t.value === typeFilter)?.label}
                <button onClick={() => handleTypeChange('all')} className="ml-1 hover:text-cyan-900 dark:hover:text-cyan-200">×</button>
              </span>
            )}
            {dateFilter && (
              <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400">
                {dateFilter === 'today' ? 'Today' : dateFilter === '24h' ? '24 Hours' : dateFilter === '1week' ? '1 Week' : '30 Days'}
                <button onClick={() => setDateFilter(null)} className="ml-1 hover:text-indigo-900 dark:hover:text-indigo-200">×</button>
              </span>
            )}
            {selectedAgencies.size > 0 && (
              <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
                {selectedAgencies.size} {selectedAgencies.size === 1 ? 'agency' : 'agencies'}
                <button onClick={() => setSelectedAgencies(new Set())} className="ml-1 hover:text-emerald-900 dark:hover:text-emerald-200">×</button>
              </span>
            )}
            <button
              onClick={clearQuickFilters}
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
        ) : notices.length === 0 ? (
          <div className="text-center py-16">
            <FileText className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <p className="text-gray-500 dark:text-gray-400">
              {searchQuery ? 'No notices match your search.' : 'No notices found.'}
            </p>
          </div>
        ) : filteredAndSortedNotices.length === 0 ? (
          <div className="text-center py-16">
            <Activity className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <p className="text-gray-500 dark:text-gray-400 mb-4">
              No notices match your filters.
            </p>
            <Button variant="secondary" onClick={clearQuickFilters} className="gap-2">
              <RotateCcw className="w-4 h-4" />
              Reset Filters
            </Button>
          </div>
        ) : (
          <>
            {/* Table */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                      Notices
                    </h2>
                    <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                      {filteredAndSortedNotices.length} notice{filteredAndSortedNotices.length !== 1 ? 's' : ''}
                      {hasQuickFilters && ` (filtered from ${notices.length})`}
                    </p>
                  </div>
                </div>
              </div>

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
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-gray-900 dark:text-white truncate max-w-[300px]">
                              {notice.title || 'Untitled'}
                            </p>
                            {notice.solicitation_id && (
                              <Link
                                href={`/sam/solicitations/${notice.solicitation_id}`}
                                onClick={(e) => e.stopPropagation()}
                                className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline font-mono"
                              >
                                View Solicitation
                              </Link>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-sm text-gray-600 dark:text-gray-400 truncate max-w-[200px]">
                            {notice.agency_name || '-'}
                          </p>
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap">
                            {formatPostedDate(notice.posted_date)}
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

'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
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
} from 'lucide-react'

// Sort types
type SortColumn = 'type' | 'title' | 'agency' | 'solicitation_number' | 'posted' | 'deadline'
type SortDirection = 'asc' | 'desc'

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
  const [notices, setNotices] = useState<SamNoticeWithSolicitation[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [hasConnection, setHasConnection] = useState<boolean | null>(null)

  // Filters and Search
  const [showFilters, setShowFilters] = useState(false)
  const [searchQuery, setSearchQuery] = useState(searchParams.get('q') || '')
  const [agencyFilter, setAgencyFilter] = useState(searchParams.get('agency') || '')
  const [noticeTypeFilter, setNoticeTypeFilter] = useState(searchParams.get('notice_type') || '')
  const [page, setPage] = useState(1)
  const pageSize = 25

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

  // Sorted notices
  const sortedNotices = useMemo(() => {
    return [...notices].sort((a, b) => {
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
  }, [notices, sortColumn, sortDirection])

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

  // Load notices
  const loadNotices = useCallback(async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const params: SamNoticeListParams = {
        limit: pageSize,
        offset: (page - 1) * pageSize,
      }
      if (searchQuery) params.keyword = searchQuery
      if (agencyFilter) params.agency = agencyFilter
      if (noticeTypeFilter) params.notice_type = noticeTypeFilter

      const data = await samApi.listAllNotices(token, params)
      setNotices(data.items)
      setTotal(data.total)
    } catch (err: any) {
      setError(err.message || 'Failed to load notices')
    } finally {
      setIsLoading(false)
    }
  }, [token, page, searchQuery, agencyFilter, noticeTypeFilter])

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

  const clearFilters = () => {
    setSearchQuery('')
    setAgencyFilter('')
    setNoticeTypeFilter('')
    setPage(1)
  }

  const hasFilters = searchQuery || agencyFilter || noticeTypeFilter

  // Use formatDate from date-utils for consistent EST display
  const formatDate = (dateStr: string | null) => formatDateUtil(dateStr)

  const totalPages = Math.ceil(total / pageSize)

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
                  {total.toLocaleString()} notices across all searches
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                onClick={() => setShowFilters(!showFilters)}
                className="gap-2"
              >
                <Filter className="w-4 h-4" />
                Filters
                {hasFilters && (
                  <span className="w-2 h-2 rounded-full bg-indigo-500" />
                )}
              </Button>
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

        {/* Search and Filters Panel */}
        <div className="mb-6 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
          {/* Search Bar */}
          <div className="flex gap-4 mb-4">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value)
                  setPage(1)
                }}
                placeholder="Search by title, solicitation number, or agency..."
                className="w-full pl-10 pr-4 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
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

          {/* Filters Row */}
          {showFilters && (
            <div className="flex flex-wrap items-end gap-4 pt-4 border-t border-gray-200 dark:border-gray-700">
              <div className="w-[200px]">
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Agency
                </label>
                <input
                  type="text"
                  value={agencyFilter}
                  onChange={(e) => {
                    setAgencyFilter(e.target.value)
                    setPage(1)
                  }}
                  placeholder="Filter by agency..."
                  className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
                />
              </div>

              <div className="w-[220px]">
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Notice Type
                </label>
                <select
                  value={noticeTypeFilter}
                  onChange={(e) => {
                    setNoticeTypeFilter(e.target.value)
                    setPage(1)
                  }}
                  className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
                >
                  <option value="">All Types</option>
                  <option value="Combined Synopsis/Solicitation">Combined Synopsis/Solicitation</option>
                  <option value="Solicitation">Solicitation</option>
                  <option value="Presolicitation">Presolicitation</option>
                  <option value="Sources Sought">Sources Sought</option>
                  <option value="Special Notice">Special Notice</option>
                  <option value="Award Notice">Award Notice</option>
                  <option value="Justification">Justification (J&A)</option>
                  <option value="Intent to Bundle">Intent to Bundle (DoD)</option>
                  <option value="Sale of Surplus Property">Sale of Surplus Property</option>
                </select>
              </div>
            </div>
          )}
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
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-blue-500 animate-spin" />
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading notices...</p>
          </div>
        ) : notices.length === 0 ? (
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
                        label="Sol #"
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
                    {sortedNotices.map((notice) => (
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
                            <Link
                              href={`/sam/solicitations/${notice.solicitation_id}`}
                              onClick={(e) => e.stopPropagation()}
                              className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline font-mono"
                            >
                              {notice.solicitation_number}
                            </Link>
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
                  Showing {((page - 1) * pageSize) + 1} - {Math.min(page * pageSize, total)} of {total}
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

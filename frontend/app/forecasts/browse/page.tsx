'use client'

import { useState, useEffect, useMemo } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { forecastsApi, Forecast } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  TrendingUp,
  Search,
  Filter,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Building2,
  Calendar,
  X,
  Loader2,
  AlertTriangle,
  SlidersHorizontal,
  ArrowUpDown,
} from 'lucide-react'

// Source type display config
const sourceTypeConfig: Record<string, { label: string; color: string; bgColor: string }> = {
  ag: {
    label: 'AG',
    color: 'text-blue-700 dark:text-blue-400',
    bgColor: 'bg-blue-100 dark:bg-blue-900/30',
  },
  apfs: {
    label: 'DHS',
    color: 'text-amber-700 dark:text-amber-400',
    bgColor: 'bg-amber-100 dark:bg-amber-900/30',
  },
  state: {
    label: 'State',
    color: 'text-purple-700 dark:text-purple-400',
    bgColor: 'bg-purple-100 dark:bg-purple-900/30',
  },
}

type SortField = 'title' | 'agency_name' | 'fiscal_year' | 'estimated_award_quarter' | 'first_seen_at' | 'last_updated_at'
type SortDirection = 'asc' | 'desc'

function ForecastBrowserContent() {
  const { token } = useAuth()
  const router = useRouter()
  const searchParams = useSearchParams()

  // State
  const [forecasts, setForecasts] = useState<Forecast[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [total, setTotal] = useState(0)

  // Pagination
  const [page, setPage] = useState(1)
  const [pageSize] = useState(25)

  // Filters
  const [searchQuery, setSearchQuery] = useState('')
  const [sourceTypeFilter, setSourceTypeFilter] = useState<string>('')
  const [agencyFilter, setAgencyFilter] = useState('')
  const [fiscalYearFilter, setFiscalYearFilter] = useState<string>('')
  const [showFilters, setShowFilters] = useState(false)

  // Sorting
  const [sortField, setSortField] = useState<SortField>('last_updated_at')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')

  // Debounced search
  const [debouncedSearch, setDebouncedSearch] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery)
      setPage(1) // Reset to first page on search
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  // Load forecasts
  useEffect(() => {
    loadForecasts()
  }, [token, page, debouncedSearch, sourceTypeFilter, fiscalYearFilter, agencyFilter])

  const loadForecasts = async () => {
    if (!token) return
    setLoading(true)
    setError(null)

    try {
      const response = await forecastsApi.listForecasts(token, {
        source_type: sourceTypeFilter || undefined,
        fiscal_year: fiscalYearFilter ? parseInt(fiscalYearFilter) : undefined,
        agency_name: agencyFilter || undefined,
        search: debouncedSearch || undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      })
      setForecasts(response.items)
      setTotal(response.total)
    } catch (err: any) {
      setError(err.message || 'Failed to load forecasts')
    } finally {
      setLoading(false)
    }
  }

  // Sort forecasts client-side
  const sortedForecasts = useMemo(() => {
    const sorted = [...forecasts].sort((a, b) => {
      let aVal: any = a[sortField]
      let bVal: any = b[sortField]

      // Handle nulls
      if (aVal === null || aVal === undefined) aVal = ''
      if (bVal === null || bVal === undefined) bVal = ''

      // String comparison
      if (typeof aVal === 'string') {
        aVal = aVal.toLowerCase()
        bVal = (bVal as string).toLowerCase()
      }

      if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1
      if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1
      return 0
    })
    return sorted
  }, [forecasts, sortField, sortDirection])

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDirection('asc')
    }
  }

  const clearFilters = () => {
    setSearchQuery('')
    setSourceTypeFilter('')
    setAgencyFilter('')
    setFiscalYearFilter('')
    setPage(1)
  }

  const hasActiveFilters = searchQuery || sourceTypeFilter || agencyFilter || fiscalYearFilter

  const totalPages = Math.ceil(total / pageSize)

  // Generate fiscal year options (current year - 1 to current year + 5)
  const currentYear = new Date().getFullYear()
  const fiscalYears = Array.from({ length: 7 }, (_, i) => currentYear - 1 + i)

  const SortButton = ({ field, label }: { field: SortField; label: string }) => (
    <button
      onClick={() => handleSort(field)}
      className="flex items-center gap-1 hover:text-gray-900 dark:hover:text-white transition-colors"
    >
      {label}
      {sortField === field ? (
        sortDirection === 'asc' ? (
          <ChevronUp className="w-4 h-4" />
        ) : (
          <ChevronDown className="w-4 h-4" />
        )
      ) : (
        <ArrowUpDown className="w-3 h-3 opacity-50" />
      )}
    </button>
  )

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">
            Browse Forecasts
          </h1>
          <p className="text-gray-500 dark:text-gray-400">
            {total.toLocaleString()} forecasts from all sources
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/forecasts/syncs">
            <Button variant="outline" size="sm">
              <SlidersHorizontal className="w-4 h-4 mr-2" />
              Manage Syncs
            </Button>
          </Link>
        </div>
      </div>

      {/* Search and Filter Bar */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex flex-col lg:flex-row gap-4">
          {/* Search Input */}
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search forecasts by title, description..."
              className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
            />
          </div>

          {/* Quick Filters */}
          <div className="flex items-center gap-3">
            {/* Source Type */}
            <select
              value={sourceTypeFilter}
              onChange={(e) => {
                setSourceTypeFilter(e.target.value)
                setPage(1)
              }}
              className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-emerald-500"
            >
              <option value="">All Sources</option>
              <option value="ag">Acquisition Gateway</option>
              <option value="apfs">DHS APFS</option>
              <option value="state">State Dept</option>
            </select>

            {/* Fiscal Year */}
            <select
              value={fiscalYearFilter}
              onChange={(e) => {
                setFiscalYearFilter(e.target.value)
                setPage(1)
              }}
              className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-emerald-500"
            >
              <option value="">All Years</option>
              {fiscalYears.map((year) => (
                <option key={year} value={year}>
                  FY{year}
                </option>
              ))}
            </select>

            {/* Toggle More Filters */}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowFilters(!showFilters)}
              className={showFilters ? 'bg-gray-100 dark:bg-gray-700' : ''}
            >
              <Filter className="w-4 h-4 mr-2" />
              More Filters
            </Button>

            {/* Clear Filters */}
            {hasActiveFilters && (
              <Button variant="ghost" size="sm" onClick={clearFilters}>
                <X className="w-4 h-4 mr-1" />
                Clear
              </Button>
            )}
          </div>
        </div>

        {/* Expanded Filters */}
        {showFilters && (
          <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700 grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Agency Filter */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Agency Name
              </label>
              <input
                type="text"
                value={agencyFilter}
                onChange={(e) => {
                  setAgencyFilter(e.target.value)
                  setPage(1)
                }}
                placeholder="Filter by agency..."
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-emerald-500"
              />
            </div>
          </div>
        )}
      </div>

      {/* Error State */}
      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 rounded-lg flex items-center gap-2 text-red-600 dark:text-red-400">
          <AlertTriangle className="w-5 h-5" />
          <span>{error}</span>
        </div>
      )}

      {/* Results Table */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="w-8 h-8 animate-spin text-emerald-500" />
          </div>
        ) : sortedForecasts.length === 0 ? (
          <div className="p-12 text-center">
            <TrendingUp className="w-12 h-12 mx-auto text-gray-300 dark:text-gray-600 mb-4" />
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
              No forecasts found
            </h3>
            <p className="text-gray-500 dark:text-gray-400">
              {hasActiveFilters
                ? 'Try adjusting your filters'
                : 'Create a sync to start pulling forecasts'}
            </p>
          </div>
        ) : (
          <>
            {/* Table */}
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50 dark:bg-gray-700/50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider min-w-[300px]">
                      <SortButton field="title" label="Title" />
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      <SortButton field="agency_name" label="Agency" />
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      NAICS
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      <SortButton field="fiscal_year" label="FY" />
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      <SortButton field="estimated_award_quarter" label="Award Qtr" />
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      <SortButton field="first_seen_at" label="Date Added" />
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      <SortButton field="last_updated_at" label="Updated" />
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {sortedForecasts.map((forecast) => {
                    const sourceConfig = sourceTypeConfig[forecast.source_type]
                    const naicsCode = forecast.naics_codes?.[0]?.code

                    return (
                      <tr
                        key={forecast.id}
                        className="hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors"
                      >
                        <td className="px-4 py-3">
                          <Link
                            href={`/forecasts/${forecast.id}`}
                            className="block max-w-md hover:text-emerald-600 dark:hover:text-emerald-400"
                          >
                            <div className="flex items-center gap-2">
                              <span
                                className={`inline-flex px-2 py-0.5 text-xs font-medium rounded ${sourceConfig?.bgColor} ${sourceConfig?.color}`}
                              >
                                {sourceConfig?.label || forecast.source_type.toUpperCase()}
                              </span>
                              <p className="font-medium text-gray-900 dark:text-white truncate">
                                {forecast.title}
                              </p>
                            </div>
                            {forecast.description && (
                              <p className="text-sm text-gray-500 dark:text-gray-400 truncate mt-1">
                                {forecast.description.slice(0, 100)}
                                {forecast.description.length > 100 ? '...' : ''}
                              </p>
                            )}
                          </Link>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-sm text-gray-600 dark:text-gray-400">
                            {forecast.agency_name || '-'}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-sm text-gray-600 dark:text-gray-400 font-mono">
                            {naicsCode || '-'}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-sm text-gray-600 dark:text-gray-400">
                            {forecast.fiscal_year ? `FY${forecast.fiscal_year}` : '-'}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-sm text-gray-600 dark:text-gray-400">
                            {forecast.estimated_award_quarter || '-'}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-sm text-gray-500 dark:text-gray-400">
                            {new Date(forecast.first_seen_at).toLocaleDateString()}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-sm text-gray-500 dark:text-gray-400">
                            {new Date(forecast.last_updated_at).toLocaleDateString()}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-2">
                            {forecast.source_url && (
                              <a
                                href={forecast.source_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="p-1.5 text-gray-400 hover:text-emerald-500 transition-colors"
                                title="View source"
                              >
                                <ExternalLink className="w-4 h-4" />
                              </a>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-700 flex items-center justify-between">
              <div className="text-sm text-gray-500 dark:text-gray-400">
                Showing {(page - 1) * pageSize + 1} to{' '}
                {Math.min(page * pageSize, total)} of {total.toLocaleString()} forecasts
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage(page - 1)}
                  disabled={page <= 1}
                >
                  <ChevronLeft className="w-4 h-4" />
                </Button>
                <span className="text-sm text-gray-600 dark:text-gray-400">
                  Page {page} of {totalPages || 1}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage(page + 1)}
                  disabled={page >= totalPages}
                >
                  <ChevronRight className="w-4 h-4" />
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default function ForecastBrowserPage() {
  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <ForecastBrowserContent />
        </div>
      </div>
    </ProtectedRoute>
  )
}

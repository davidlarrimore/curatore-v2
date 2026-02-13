'use client'

import { useState, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { useOrgUrl } from '@/lib/org-url-context'
import { forecastsApi, ForecastSync, ForecastStatsResponse, Forecast } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import {
  TrendingUp,
  Plus,
  RefreshCw,
  Calendar,
  Clock,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  ChevronRight,
  ChevronLeft,
  Settings,
  List,
  Search,
  X,
  ExternalLink,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from 'lucide-react'

// Sort field type
type SortField = 'title' | 'agency_name' | 'naics' | 'fiscal_year' | 'award_quarter' | 'first_seen_at' | 'last_updated_at' | null
type SortDirection = 'asc' | 'desc'

// Source type display config
const sourceTypeConfig: Record<string, { label: string; color: string; bgColor: string; description: string }> = {
  ag: {
    label: 'AG',
    color: 'text-blue-700 dark:text-blue-400',
    bgColor: 'bg-blue-100 dark:bg-blue-900/30',
    description: 'GSA Acquisition Gateway',
  },
  apfs: {
    label: 'DHS',
    color: 'text-amber-700 dark:text-amber-400',
    bgColor: 'bg-amber-100 dark:bg-amber-900/30',
    description: 'Department of Homeland Security',
  },
  state: {
    label: 'State',
    color: 'text-purple-700 dark:text-purple-400',
    bgColor: 'bg-purple-100 dark:bg-purple-900/30',
    description: 'Department of State',
  },
}

type TabType = 'forecasts' | 'setup'

function ForecastsPageContent() {
  const { token } = useAuth()
  const { orgSlug } = useOrgUrl()
  const router = useRouter()
  const searchParams = useSearchParams()

  // Helper for org-scoped URLs
  const orgUrl = (path: string) => `/orgs/${orgSlug}${path}`

  // Get tab from URL or default to 'forecasts'
  const tabParam = searchParams.get('tab')
  const [activeTab, setActiveTab] = useState<TabType>(
    tabParam === 'setup' ? 'setup' : 'forecasts'
  )

  const [stats, setStats] = useState<ForecastStatsResponse | null>(null)
  const [syncs, setSyncs] = useState<ForecastSync[]>([])
  const [forecasts, setForecasts] = useState<Forecast[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Forecasts tab state
  const [searchQuery, setSearchQuery] = useState('')
  const [sourceTypeFilter, setSourceTypeFilter] = useState('')
  const [fiscalYearFilter, setFiscalYearFilter] = useState('')
  const [sortBy, setSortBy] = useState<SortField>(null)
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const [page, setPage] = useState(1)
  const [totalForecasts, setTotalForecasts] = useState(0)
  const pageSize = 25

  // Debounced search
  const [debouncedSearch, setDebouncedSearch] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery)
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  // Update URL when tab changes
  useEffect(() => {
    const url = new URL(window.location.href)
    url.searchParams.set('tab', activeTab)
    router.replace(url.pathname + url.search, { scroll: false })
  }, [activeTab, router])

  useEffect(() => {
    loadData()
  }, [token, activeTab, page, debouncedSearch, sourceTypeFilter, fiscalYearFilter, sortBy, sortDirection])

  const loadData = async () => {
    if (!token) return
    setLoading(true)
    setError(null)

    try {
      // Always load stats
      const statsData = await forecastsApi.getStats(token)
      setStats(statsData)

      if (activeTab === 'setup') {
        // Load syncs for setup tab
        const syncsData = await forecastsApi.listSyncs(token, { limit: 50 })
        setSyncs(syncsData.items)
      } else {
        // Load forecasts for forecasts tab
        const forecastsData = await forecastsApi.listForecasts(token, {
          source_type: sourceTypeFilter || undefined,
          fiscal_year: fiscalYearFilter ? parseInt(fiscalYearFilter) : undefined,
          search: debouncedSearch || undefined,
          sort_by: sortBy || undefined,
          sort_direction: sortBy ? sortDirection : undefined,
          limit: pageSize,
          offset: (page - 1) * pageSize,
        })
        setForecasts(forecastsData.items)
        setTotalForecasts(forecastsData.total)
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load data'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  const totalPages = Math.ceil(totalForecasts / pageSize)
  const currentYear = new Date().getFullYear()
  const fiscalYears = Array.from({ length: 7 }, (_, i) => currentYear - 1 + i)
  const hasActiveFilters = searchQuery || sourceTypeFilter || fiscalYearFilter

  const clearFilters = () => {
    setSearchQuery('')
    setSourceTypeFilter('')
    setFiscalYearFilter('')
    setSortBy(null)
    setSortDirection('desc')
    setPage(1)
  }

  // Handle sort column click
  const handleSort = (field: SortField) => {
    if (sortBy === field) {
      // Toggle direction if clicking same column
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      // Set new field with default desc direction
      setSortBy(field)
      setSortDirection('desc')
    }
    setPage(1) // Reset to first page when sorting
  }

  // Render sortable header
  const SortableHeader = ({ field, label, className = '' }: { field: SortField; label: string; className?: string }) => {
    const isActive = sortBy === field
    return (
      <th
        className={`px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase cursor-pointer hover:text-gray-700 dark:hover:text-gray-200 select-none group ${className}`}
        onClick={() => handleSort(field)}
      >
        <div className="flex items-center gap-1">
          {label}
          <span className={`transition-colors ${isActive ? 'text-emerald-500' : 'text-gray-300 dark:text-gray-600 group-hover:text-gray-400'}`}>
            {isActive ? (
              sortDirection === 'asc' ? <ArrowUp className="w-3.5 h-3.5" /> : <ArrowDown className="w-3.5 h-3.5" />
            ) : (
              <ArrowUpDown className="w-3.5 h-3.5" />
            )}
          </span>
        </div>
      </th>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center shadow-lg">
            <TrendingUp className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">
              Acquisition Forecasts
            </h1>
            <p className="text-gray-500 dark:text-gray-400">
              Federal procurement forecasts from multiple sources
            </p>
          </div>
        </div>
        <Button onClick={loadData} variant="outline" size="sm">
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Total Forecasts</p>
                <p className="text-2xl font-semibold text-gray-900 dark:text-white">
                  {stats.total_forecasts.toLocaleString()}
                </p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
                <TrendingUp className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
              </div>
            </div>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Active Syncs</p>
                <p className="text-2xl font-semibold text-gray-900 dark:text-white">
                  {stats.active_syncs}
                </p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                <RefreshCw className="w-5 h-5 text-blue-600 dark:text-blue-400" />
              </div>
            </div>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Recent Changes</p>
                <p className="text-2xl font-semibold text-gray-900 dark:text-white">
                  {stats.recent_changes}
                </p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
                <Clock className="w-5 h-5 text-amber-600 dark:text-amber-400" />
              </div>
            </div>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Last Sync</p>
                <p className="text-lg font-semibold text-gray-900 dark:text-white">
                  {stats.last_sync_at
                    ? new Date(stats.last_sync_at).toLocaleDateString()
                    : 'Never'}
                </p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center">
                <Calendar className="w-5 h-5 text-purple-600 dark:text-purple-400" />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-gray-700">
        <nav className="flex gap-8">
          <button
            onClick={() => setActiveTab('forecasts')}
            className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'forecasts'
                ? 'border-emerald-500 text-emerald-600 dark:text-emerald-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <div className="flex items-center gap-2">
              <List className="w-4 h-4" />
              Forecasts
              {stats && (
                <span className="ml-1 px-2 py-0.5 text-xs rounded-full bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                  {stats.total_forecasts.toLocaleString()}
                </span>
              )}
            </div>
          </button>
          <button
            onClick={() => setActiveTab('setup')}
            className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'setup'
                ? 'border-emerald-500 text-emerald-600 dark:text-emerald-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <div className="flex items-center gap-2">
              <Settings className="w-4 h-4" />
              Setup
              {stats && (
                <span className="ml-1 px-2 py-0.5 text-xs rounded-full bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                  {stats.total_syncs}
                </span>
              )}
            </div>
          </button>
        </nav>
      </div>

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 rounded-lg flex items-center gap-2 text-red-600 dark:text-red-400">
          <AlertTriangle className="w-5 h-5" />
          <span>{error}</span>
        </div>
      )}

      {/* Tab Content */}
      {activeTab === 'forecasts' ? (
        /* Forecasts Tab */
        <div className="space-y-4">
          {/* Search and Filters */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex flex-col lg:flex-row gap-4">
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
              <div className="flex items-center gap-3">
                <select
                  value={sourceTypeFilter}
                  onChange={(e) => {
                    setSourceTypeFilter(e.target.value)
                    setPage(1)
                  }}
                  className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm"
                >
                  <option value="">All Sources</option>
                  <option value="ag">Acquisition Gateway</option>
                  <option value="apfs">DHS APFS</option>
                  <option value="state">State Dept</option>
                </select>
                <select
                  value={fiscalYearFilter}
                  onChange={(e) => {
                    setFiscalYearFilter(e.target.value)
                    setPage(1)
                  }}
                  className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm"
                >
                  <option value="">All Years</option>
                  {fiscalYears.map((year) => (
                    <option key={year} value={year}>FY{year}</option>
                  ))}
                </select>
                {sortBy && (
                  <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">
                    {sortDirection === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
                    {sortBy === 'title' && 'Title'}
                    {sortBy === 'agency_name' && 'Agency'}
                    {sortBy === 'naics' && 'NAICS'}
                    {sortBy === 'fiscal_year' && 'FY'}
                    {sortBy === 'award_quarter' && 'Award Qtr'}
                    {sortBy === 'first_seen_at' && 'Created'}
                    {sortBy === 'last_updated_at' && 'Updated'}
                  </span>
                )}
                {(hasActiveFilters || sortBy) && (
                  <Button variant="ghost" size="sm" onClick={clearFilters}>
                    <X className="w-4 h-4 mr-1" />
                    Clear
                  </Button>
                )}
              </div>
            </div>
          </div>

          {/* Forecasts Table */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            {loading ? (
              <div className="flex items-center justify-center h-64">
                <Loader2 className="w-8 h-8 animate-spin text-emerald-500" />
              </div>
            ) : forecasts.length === 0 ? (
              <div className="p-12 text-center">
                <TrendingUp className="w-12 h-12 mx-auto text-gray-300 dark:text-gray-600 mb-4" />
                <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
                  No forecasts found
                </h3>
                <p className="text-gray-500 dark:text-gray-400 mb-4">
                  {hasActiveFilters ? 'Try adjusting your filters' : 'Set up a sync to start pulling forecasts'}
                </p>
                {!hasActiveFilters && (
                  <Button variant="primary" onClick={() => setActiveTab('setup')}>
                    <Plus className="w-4 h-4 mr-2" />
                    Set Up Sync
                  </Button>
                )}
              </div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-gray-50 dark:bg-gray-700/50">
                      <tr>
                        <SortableHeader field="title" label="Title" className="min-w-[300px]" />
                        <SortableHeader field="agency_name" label="Agency" />
                        <SortableHeader field="naics" label="NAICS" />
                        <SortableHeader field="fiscal_year" label="FY" />
                        <SortableHeader field="award_quarter" label="Award Qtr" />
                        <SortableHeader field="first_seen_at" label="Created" />
                        <SortableHeader field="last_updated_at" label="Updated" />
                        <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                      {forecasts.map((forecast) => {
                        const sourceConfig = sourceTypeConfig[forecast.source_type]
                        const naicsCode = forecast.naics_codes?.[0]?.code
                        const detailUrl = orgUrl(`/syncs/forecasts/${forecast.id}`)
                        return (
                          <tr
                            key={forecast.id}
                            onClick={() => router.push(detailUrl)}
                            className="hover:bg-gray-50 dark:hover:bg-gray-700/30 cursor-pointer transition-colors"
                          >
                            <td className="px-4 py-3">
                              <Link
                                href={detailUrl}
                                onClick={(e) => e.stopPropagation()}
                                className="block max-w-md hover:text-emerald-600 dark:hover:text-emerald-400"
                              >
                                <div className="flex items-center gap-2">
                                  <span className={`inline-flex px-2 py-0.5 text-xs font-medium rounded ${sourceConfig?.bgColor} ${sourceConfig?.color}`}>
                                    {sourceConfig?.label || forecast.source_type.toUpperCase()}
                                  </span>
                                  <span className="font-medium text-gray-900 dark:text-white truncate">
                                    {forecast.title}
                                  </span>
                                </div>
                              </Link>
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                              {forecast.agency_name || '-'}
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400 font-mono">
                              {naicsCode || '-'}
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                              {forecast.fiscal_year ? `FY${forecast.fiscal_year}` : '-'}
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                              {forecast.estimated_award_quarter || '-'}
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                              {forecast.first_seen_at ? new Date(forecast.first_seen_at).toLocaleDateString() : '-'}
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                              {forecast.last_updated_at ? new Date(forecast.last_updated_at).toLocaleDateString() : '-'}
                            </td>
                            <td className="px-4 py-3 text-right">
                              <div className="flex items-center justify-end gap-1">
                                <Link
                                  href={detailUrl}
                                  onClick={(e) => e.stopPropagation()}
                                  className="p-1.5 text-gray-400 hover:text-emerald-500 transition-colors inline-flex"
                                  title="View details"
                                >
                                  <ChevronRight className="w-4 h-4" />
                                </Link>
                                {forecast.source_url && (
                                  <a
                                    href={forecast.source_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    onClick={(e) => e.stopPropagation()}
                                    className="p-1.5 text-gray-400 hover:text-emerald-500 transition-colors inline-flex"
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
                    Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, totalForecasts)} of {totalForecasts.toLocaleString()}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" onClick={() => setPage(page - 1)} disabled={page <= 1}>
                      <ChevronLeft className="w-4 h-4" />
                    </Button>
                    <span className="text-sm text-gray-600 dark:text-gray-400">
                      Page {page} of {totalPages || 1}
                    </span>
                    <Button variant="outline" size="sm" onClick={() => setPage(page + 1)} disabled={page >= totalPages}>
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      ) : (
        /* Setup Tab */
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-gray-600 dark:text-gray-400">
              Configure data sources to pull acquisition forecasts
            </p>
            <Link href={orgUrl('/syncs/forecasts/syncs/new')}>
              <Button variant="primary" size="sm">
                <Plus className="w-4 h-4 mr-2" />
                New Sync
              </Button>
            </Link>
          </div>

          {loading ? (
            <div className="flex items-center justify-center h-64">
              <Loader2 className="w-8 h-8 animate-spin text-emerald-500" />
            </div>
          ) : syncs.length === 0 ? (
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-12 text-center">
              <Settings className="w-12 h-12 mx-auto text-gray-300 dark:text-gray-600 mb-4" />
              <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
                No syncs configured
              </h3>
              <p className="text-gray-500 dark:text-gray-400 mb-6">
                Create a sync to start pulling forecasts from federal sources
              </p>
              <Link href={orgUrl('/syncs/forecasts/syncs/new')}>
                <Button variant="primary">
                  <Plus className="w-4 h-4 mr-2" />
                  Create Your First Sync
                </Button>
              </Link>
            </div>
          ) : (
            <div className="grid gap-4">
              {syncs.map((sync) => {
                const sourceConfig = sourceTypeConfig[sync.source_type]
                return (
                  <Link
                    key={sync.id}
                    href={orgUrl(`/syncs/forecasts/syncs/${sync.id}`)}
                    className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 hover:border-emerald-300 dark:hover:border-emerald-700 transition-colors"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-4">
                        <div className={`w-10 h-10 rounded-lg ${sourceConfig?.bgColor} flex items-center justify-center`}>
                          <TrendingUp className={`w-5 h-5 ${sourceConfig?.color}`} />
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <h3 className="font-medium text-gray-900 dark:text-white">
                              {sync.name}
                            </h3>
                            <span className={`px-2 py-0.5 text-xs font-medium rounded ${sourceConfig?.bgColor} ${sourceConfig?.color}`}>
                              {sourceConfig?.description || sync.source_type.toUpperCase()}
                            </span>
                            {!sync.is_active && (
                              <span className="px-2 py-0.5 text-xs font-medium rounded bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400">
                                Paused
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-4 text-sm text-gray-500 dark:text-gray-400 mt-1">
                            <span>{sync.forecast_count.toLocaleString()} forecasts</span>
                            <span>-</span>
                            <span className="capitalize">{sync.sync_frequency}</span>
                            {sync.last_sync_at && (
                              <>
                                <span>-</span>
                                <span>Last sync: {new Date(sync.last_sync_at).toLocaleDateString()}</span>
                              </>
                            )}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        {sync.is_syncing ? (
                          <span className="flex items-center gap-1 text-sm text-amber-600 dark:text-amber-400">
                            <Loader2 className="w-4 h-4 animate-spin" />
                            Syncing
                          </span>
                        ) : sync.last_sync_status === 'success' ? (
                          <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                        ) : sync.last_sync_status === 'failed' ? (
                          <AlertTriangle className="w-5 h-5 text-red-500" />
                        ) : null}
                        <ChevronRight className="w-5 h-5 text-gray-400" />
                      </div>
                    </div>
                  </Link>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function ForecastsPage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <ForecastsPageContent />
      </div>
    </div>
  )
}

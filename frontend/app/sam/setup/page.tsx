'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { samApi, connectionsApi, SamSearch, SamApiUsage, SamQueueStats } from '@/lib/api'
import { formatCompact } from '@/lib/date-utils'
import { Button } from '@/components/ui/Button'
import SamNavigation from '@/components/sam/SamNavigation'
import SamSearchForm from '@/components/sam/SamSearchForm'
import SamConnectionRequired from '@/components/sam/SamConnectionRequired'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import toast from 'react-hot-toast'
import {
  Plus,
  RefreshCw,
  AlertTriangle,
  Building2,
  Search,
  FileText,
  Clock,
  Zap,
  MoreHorizontal,
  Pencil,
  Trash2,
  Play,
  BarChart3,
  AlertCircle,
  Settings,
  Copy,
  ChevronUp,
  ChevronDown,
  ArrowUpDown,
} from 'lucide-react'

// Sort column type
type SortColumn = 'name' | 'status' | 'criteria' | 'frequency' | 'lastPull'
type SortDirection = 'asc' | 'desc'

export default function SamSetupPage() {
  return (
    <ProtectedRoute>
      <SamSetupContent />
    </ProtectedRoute>
  )
}

function SamSetupContent() {
  const router = useRouter()
  const { token } = useAuth()

  // State
  const [searches, setSearches] = useState<SamSearch[]>([])
  const [usage, setUsage] = useState<SamApiUsage | null>(null)
  const [queueStats, setQueueStats] = useState<SamQueueStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editingSearch, setEditingSearch] = useState<SamSearch | null>(null)
  const [hasConnection, setHasConnection] = useState<boolean | null>(null)
  const [sortColumn, setSortColumn] = useState<SortColumn>('name')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')

  // Sort handler
  const handleSort = (column: SortColumn) => {
    if (sortColumn === column) {
      // Toggle direction if same column
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      // New column, default to ascending
      setSortColumn(column)
      setSortDirection('asc')
    }
  }

  // Sorted searches
  const sortedSearches = useMemo(() => {
    return [...searches].sort((a, b) => {
      let comparison = 0

      switch (sortColumn) {
        case 'name':
          comparison = a.name.localeCompare(b.name)
          break
        case 'status':
          comparison = a.status.localeCompare(b.status)
          break
        case 'criteria': {
          const aCriteria = a.search_config?.naics_codes?.join(',') || a.search_config?.keyword || ''
          const bCriteria = b.search_config?.naics_codes?.join(',') || b.search_config?.keyword || ''
          comparison = aCriteria.localeCompare(bCriteria)
          break
        }
        case 'frequency':
          comparison = a.pull_frequency.localeCompare(b.pull_frequency)
          break
        case 'lastPull': {
          const aDate = a.last_pull_at ? new Date(a.last_pull_at).getTime() : 0
          const bDate = b.last_pull_at ? new Date(b.last_pull_at).getTime() : 0
          comparison = aDate - bDate
          break
        }
      }

      return sortDirection === 'asc' ? comparison : -comparison
    })
  }, [searches, sortColumn, sortDirection])

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
      // If we can't check connections, assume no connection
      setHasConnection(false)
    }
  }, [token])

  // Load data - silent parameter skips the loading spinner (for polling refreshes)
  const loadData = useCallback(async (silent = false) => {
    if (!token) return

    if (!silent) {
      setIsLoading(true)
    }
    setError('')

    try {
      const [searchesRes, usageRes, queueRes] = await Promise.all([
        samApi.listSearches(token),
        samApi.getUsage(token),
        samApi.getQueueStats(token),
      ])
      setSearches(searchesRes.items)
      setUsage(usageRes)
      setQueueStats(queueRes)
    } catch (err: any) {
      setError(err.message || 'Failed to load SAM data')
    } finally {
      if (!silent) {
        setIsLoading(false)
      }
    }
  }, [token])

  useEffect(() => {
    if (token) {
      checkConnection()
    }
  }, [token, checkConnection])

  useEffect(() => {
    if (token && hasConnection === true) {
      loadData()
    } else if (hasConnection === false) {
      setIsLoading(false)
    }
  }, [token, hasConnection, loadData])

  // Show connection required screen if no SAM.gov connection
  if (hasConnection === false) {
    return <SamConnectionRequired />
  }

  // Poll when any search is pulling
  useEffect(() => {
    const hasPulling = searches.some(s => s.is_pulling)
    if (hasPulling) {
      const interval = setInterval(() => {
        loadData(true) // Silent refresh - don't show spinner
      }, 3000) // Poll every 3 seconds while pulling
      return () => clearInterval(interval)
    }
  }, [searches, loadData])

  // Handlers
  const handleCreate = () => {
    setEditingSearch(null)
    setShowForm(true)
  }

  const handleEdit = (search: SamSearch) => {
    setEditingSearch(search)
    setShowForm(true)
  }

  const handleClone = (search: SamSearch) => {
    // Create a clone with ONLY the fields needed for creating a new search
    // Explicitly do NOT include id, organization_id, slug, or any runtime fields
    const clonedSearch: Partial<SamSearch> = {
      // Only copy user-editable configuration
      name: `${search.name} (Copy)`,
      description: search.description,
      search_config: { ...search.search_config },
      pull_frequency: search.pull_frequency,
      // Note: id is intentionally omitted so form creates a new record
    }
    setEditingSearch(clonedSearch as SamSearch)
    setShowForm(true)
  }

  const handleFormSuccess = () => {
    setShowForm(false)
    setEditingSearch(null)
    loadData()
  }

  const handleFormCancel = () => {
    setShowForm(false)
    setEditingSearch(null)
  }

  const handleDelete = async (search: SamSearch) => {
    console.log('[SAM Delete] Starting delete for:', search.id, search.name)
    if (!token) {
      console.log('[SAM Delete] No token, aborting')
      return
    }
    if (!confirm(`Delete search "${search.name}"? This cannot be undone.`)) {
      console.log('[SAM Delete] User cancelled')
      return
    }

    console.log('[SAM Delete] User confirmed, calling API')
    try {
      await samApi.deleteSearch(token, search.id)
      console.log('[SAM Delete] Delete successful')
      toast.success(`Deleted "${search.name}"`)
      loadData()
    } catch (err: any) {
      console.error('[SAM Delete] Error:', err)
      setError(err.message || 'Failed to delete search')
      toast.error(err.message || 'Failed to delete search')
    }
  }

  const handleTriggerPull = async (search: SamSearch) => {
    if (!token) return

    try {
      const result = await samApi.triggerPull(token, search.id)
      if (result.status === 'queued') {
        toast.success(`Pull queued for "${search.name}". Results will appear shortly.`)
      } else {
        toast.success(`Pull completed: ${result.new_solicitations || 0} new solicitations`)
      }
      // Refresh data silently to show the pulling indicator
      // The polling effect will take over once is_pulling is detected
      loadData(true)
    } catch (err: any) {
      // Check if this is a rate limit error (429)
      const isRateLimit = err.status === 429
      if (isRateLimit) {
        // Show a warning toast for rate limiting (not an error)
        toast(err.message || 'Please wait before triggering another pull.', {
          icon: '⏳',
          duration: 4000,
        })
      } else {
        // Show error for actual failures
        setError(err.message || 'Failed to trigger pull')
        toast.error(err.message || 'Failed to trigger pull')
      }
    }
  }

  // Use formatCompact from date-utils for consistent EST display
  const formatDate = (dateStr: string | null) => dateStr ? formatCompact(dateStr) : 'Never'

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active':
        return 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400'
      case 'paused':
        return 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400'
      case 'archived':
        return 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
      default:
        return 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
    }
  }

  const getPullStatusColor = (status: string | null) => {
    switch (status) {
      case 'success':
        return 'text-emerald-600 dark:text-emerald-400'
      case 'partial':
        return 'text-amber-600 dark:text-amber-400'
      case 'failed':
        return 'text-red-600 dark:text-red-400'
      default:
        return 'text-gray-400'
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-gray-500 to-slate-600 text-white shadow-lg shadow-gray-500/25">
                <Settings className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  SAM.gov Setup
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  Manage searches and monitor API usage
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                onClick={loadData}
                disabled={isLoading}
                className="gap-2"
              >
                <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
              <Button onClick={handleCreate} className="gap-2 shadow-lg shadow-blue-500/25">
                <Plus className="w-4 h-4" />
                New Search
              </Button>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <SamNavigation />

        {/* API Usage Dashboard */}
        {usage && (
          <div className="mb-8 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center text-white">
                <BarChart3 className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                  API Usage Today
                </h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Resets at {new Date(usage.reset_at).toLocaleTimeString()}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {/* Usage Progress */}
              <div className="col-span-2 p-4 bg-gray-50 dark:bg-gray-900/50 rounded-lg">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-gray-600 dark:text-gray-400">
                    {usage.total_calls} / {usage.daily_limit} calls
                  </span>
                  <span className={`text-sm font-bold ${
                    usage.usage_percent > 80
                      ? 'text-red-600 dark:text-red-400'
                      : usage.usage_percent > 50
                      ? 'text-amber-600 dark:text-amber-400'
                      : 'text-emerald-600 dark:text-emerald-400'
                  }`}>
                    {usage.usage_percent.toFixed(1)}%
                  </span>
                </div>
                <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      usage.usage_percent > 80
                        ? 'bg-red-500'
                        : usage.usage_percent > 50
                        ? 'bg-amber-500'
                        : 'bg-emerald-500'
                    }`}
                    style={{ width: `${Math.min(usage.usage_percent, 100)}%` }}
                  />
                </div>
                {usage.is_over_limit && (
                  <div className="mt-2 flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
                    <AlertCircle className="w-4 h-4" />
                    Daily limit exceeded
                  </div>
                )}
              </div>

              {/* Call Breakdown */}
              <div className="p-4 bg-gray-50 dark:bg-gray-900/50 rounded-lg">
                <div className="flex items-center gap-2 mb-1">
                  <Search className="w-4 h-4 text-blue-500" />
                  <span className="text-xs text-gray-500 dark:text-gray-400">Search Calls</span>
                </div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {usage.search_calls}
                </p>
              </div>

              <div className="p-4 bg-gray-50 dark:bg-gray-900/50 rounded-lg">
                <div className="flex items-center gap-2 mb-1">
                  <FileText className="w-4 h-4 text-purple-500" />
                  <span className="text-xs text-gray-500 dark:text-gray-400">Attachments</span>
                </div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {usage.attachment_calls}
                </p>
              </div>
            </div>

            {/* Queue Stats */}
            {queueStats && queueStats.total > 0 && (
              <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                <div className="flex items-center gap-4 text-sm">
                  <span className="text-gray-500 dark:text-gray-400">Queued Requests:</span>
                  <span className="px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 font-medium">
                    {queueStats.pending} pending
                  </span>
                  {queueStats.ready_to_process > 0 && (
                    <span className="px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400 font-medium">
                      {queueStats.ready_to_process} ready
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Stats Bar */}
        {searches.length > 0 && !isLoading && (
          <div className="mb-6 flex flex-wrap items-center gap-4 text-sm">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300">
              <span className="font-medium">{searches.length}</span>
              <span>searches</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="font-medium">{searches.filter(s => s.status === 'active').length}</span>
              <span>active</span>
            </div>
            {searches.filter(s => s.is_pulling).length > 0 && (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-400">
                <RefreshCw className="w-4 h-4 animate-spin" />
                <span className="font-medium">{searches.filter(s => s.is_pulling).length}</span>
                <span>pulling</span>
              </div>
            )}
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400">
              <Clock className="w-4 h-4" />
              <span className="font-medium">{searches.filter(s => s.pull_frequency !== 'manual').length}</span>
              <span>scheduled</span>
            </div>
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

        {/* Form Modal */}
        {showForm && (
          <SamSearchForm
            search={editingSearch}
            onSuccess={handleFormSuccess}
            onCancel={handleFormCancel}
          />
        )}

        {/* Content */}
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-blue-500 animate-spin" />
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading searches...</p>
          </div>
        ) : searches.length === 0 ? (
          /* Empty State */
          <div className="relative overflow-hidden rounded-2xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/50 px-6 py-16 text-center">
            <div className="absolute inset-0 pointer-events-none">
              <div className="absolute -top-24 -right-24 w-64 h-64 rounded-full bg-gradient-to-br from-blue-500/5 to-indigo-500/5 blur-3xl" />
              <div className="absolute -bottom-24 -left-24 w-64 h-64 rounded-full bg-gradient-to-br from-purple-500/5 to-pink-500/5 blur-3xl" />
            </div>

            <div className="relative">
              <div className="mx-auto w-20 h-20 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-xl shadow-blue-500/25 mb-6">
                <Building2 className="w-10 h-10 text-white" />
              </div>
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                No SAM.gov Searches
              </h3>
              <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto mb-8">
                Create a search to start monitoring federal contract opportunities from SAM.gov.
              </p>
              <Button
                onClick={handleCreate}
                size="lg"
                className="gap-2 shadow-lg shadow-blue-500/25"
              >
                <Plus className="w-5 h-5" />
                Create First Search
              </Button>
            </div>
          </div>
        ) : (
          /* Table View */
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700">
                    <SortableHeader
                      label="Name"
                      column="name"
                      currentColumn={sortColumn}
                      direction={sortDirection}
                      onSort={handleSort}
                    />
                    <SortableHeader
                      label="Status"
                      column="status"
                      currentColumn={sortColumn}
                      direction={sortDirection}
                      onSort={handleSort}
                    />
                    <SortableHeader
                      label="Search Criteria"
                      column="criteria"
                      currentColumn={sortColumn}
                      direction={sortDirection}
                      onSort={handleSort}
                    />
                    <SortableHeader
                      label="Frequency"
                      column="frequency"
                      currentColumn={sortColumn}
                      direction={sortDirection}
                      onSort={handleSort}
                    />
                    <SortableHeader
                      label="Last Pull"
                      column="lastPull"
                      currentColumn={sortColumn}
                      direction={sortDirection}
                      onSort={handleSort}
                    />
                    <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {sortedSearches.map((search) => (
                    <SearchTableRow
                      key={search.id}
                      search={search}
                      onEdit={() => handleEdit(search)}
                      onClone={() => handleClone(search)}
                      onDelete={() => handleDelete(search)}
                      onTriggerPull={() => handleTriggerPull(search)}
                      onClick={() => router.push(`/sam/${search.id}`)}
                      formatDate={formatDate}
                      getStatusColor={getStatusColor}
                      getPullStatusColor={getPullStatusColor}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Search Table Row Component
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
      className="px-4 py-3 text-left text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors select-none"
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

// Search Table Row Component
interface SearchTableRowProps {
  search: SamSearch
  onEdit: () => void
  onClone: () => void
  onDelete: () => void
  onTriggerPull: () => void
  onClick: () => void
  formatDate: (date: string | null) => string
  getStatusColor: (status: string) => string
  getPullStatusColor: (status: string | null) => string
}

function SearchTableRow({
  search,
  onEdit,
  onClone,
  onDelete,
  onTriggerPull,
  onClick,
  formatDate,
  getStatusColor,
  getPullStatusColor,
}: SearchTableRowProps) {
  const [showMenu, setShowMenu] = useState(false)

  // Build search criteria summary
  const getCriteriaSummary = () => {
    const parts: string[] = []
    if (search.search_config?.naics_codes?.length > 0) {
      const naics = search.search_config.naics_codes.slice(0, 2).join(', ')
      const more = search.search_config.naics_codes.length > 2
        ? ` +${search.search_config.naics_codes.length - 2}`
        : ''
      parts.push(`NAICS: ${naics}${more}`)
    }
    if (search.search_config?.keyword) {
      parts.push(`"${search.search_config.keyword}"`)
    }
    return parts.length > 0 ? parts.join(' · ') : '-'
  }

  return (
    <tr
      onClick={onClick}
      className="hover:bg-gray-50 dark:hover:bg-gray-900/50 cursor-pointer transition-colors"
    >
      {/* Name */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          {/* Pulling indicator */}
          {search.is_pulling && (
            <div className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
          )}
          <div className="min-w-0">
            <div className="font-medium text-gray-900 dark:text-white truncate max-w-[200px]">
              {search.name}
            </div>
            {search.description && (
              <div className="text-xs text-gray-500 dark:text-gray-400 truncate max-w-[200px]">
                {search.description}
              </div>
            )}
          </div>
        </div>
      </td>

      {/* Status */}
      <td className="px-4 py-3">
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${getStatusColor(search.status)}`}>
          {search.status}
        </span>
      </td>

      {/* Search Criteria */}
      <td className="px-4 py-3">
        <div className="text-sm text-gray-600 dark:text-gray-300 truncate max-w-[250px]" title={getCriteriaSummary()}>
          {getCriteriaSummary()}
        </div>
      </td>

      {/* Frequency */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-1.5 text-sm text-gray-600 dark:text-gray-300">
          <Clock className="w-3.5 h-3.5 text-gray-400" />
          <span className="capitalize">
            {search.pull_frequency === 'manual' ? 'Manual' : search.pull_frequency}
          </span>
        </div>
      </td>

      {/* Last Pull */}
      <td className="px-4 py-3">
        {search.is_pulling ? (
          <div className="flex items-center gap-1.5 text-sm text-indigo-600 dark:text-indigo-400">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            <span className="font-medium">Pulling...</span>
          </div>
        ) : (
          <div className={`text-sm ${getPullStatusColor(search.last_pull_status)}`}>
            {formatDate(search.last_pull_at)}
          </div>
        )}
      </td>

      {/* Actions */}
      <td className="px-4 py-3">
        <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
          {/* Sync button */}
          <button
            onClick={() => {
              if (!search.is_pulling) {
                onTriggerPull()
              }
            }}
            disabled={search.is_pulling}
            title={search.is_pulling ? 'Sync in progress...' : 'Sync now'}
            className={`p-1.5 rounded-lg transition-all ${
              search.is_pulling
                ? 'text-indigo-500 cursor-not-allowed'
                : 'text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20'
            }`}
          >
            <RefreshCw className={`w-4 h-4 ${search.is_pulling ? 'animate-spin' : ''}`} />
          </button>

          {/* Edit button */}
          <button
            onClick={onEdit}
            title="Edit"
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-all"
          >
            <Pencil className="w-4 h-4" />
          </button>

          {/* More menu */}
          <div className="relative">
            <button
              onClick={() => setShowMenu(!showMenu)}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-all"
            >
              <MoreHorizontal className="w-4 h-4" />
            </button>

            {showMenu && (
              <div className="absolute right-0 top-full mt-1 w-36 bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 py-1 z-50">
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onClone()
                    setShowMenu(false)
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                  <Copy className="w-4 h-4" />
                  Clone
                </button>
                <hr className="my-1 border-gray-200 dark:border-gray-700" />
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onDelete()
                    setShowMenu(false)
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                  Delete
                </button>
              </div>
            )}
          </div>
        </div>
      </td>
    </tr>
  )
}

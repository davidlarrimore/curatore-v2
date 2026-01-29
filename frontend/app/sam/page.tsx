'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { samApi, SamSearch, SamApiUsage, SamQueueStats } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import toast from 'react-hot-toast'
import {
  Plus,
  RefreshCw,
  Loader2,
  AlertTriangle,
  Building2,
  Search,
  FileText,
  Clock,
  TrendingUp,
  Zap,
  Calendar,
  MoreHorizontal,
  Pencil,
  Trash2,
  Play,
  Pause,
  ExternalLink,
  BarChart3,
  AlertCircle,
} from 'lucide-react'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import SamSearchForm from '@/components/sam/SamSearchForm'

export default function SamPage() {
  return (
    <ProtectedRoute>
      <SamContent />
    </ProtectedRoute>
  )
}

function SamContent() {
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

  // Load data
  const loadData = useCallback(async () => {
    if (!token) return

    setIsLoading(true)
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
      setIsLoading(false)
    }
  }, [token])

  useEffect(() => {
    if (token) {
      loadData()
    }
  }, [token, loadData])

  // Handlers
  const handleCreate = () => {
    setEditingSearch(null)
    setShowForm(true)
  }

  const handleEdit = (search: SamSearch) => {
    setEditingSearch(search)
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
    if (!token) return
    if (!confirm(`Delete search "${search.name}"? This cannot be undone.`)) return

    try {
      await samApi.deleteSearch(token, search.id)
      loadData()
    } catch (err: any) {
      setError(err.message || 'Failed to delete search')
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
      // Refresh data periodically to show results as they come in
      loadData()
      setTimeout(() => loadData(), 5000)
      setTimeout(() => loadData(), 15000)
    } catch (err: any) {
      setError(err.message || 'Failed to trigger pull')
      toast.error(err.message || 'Failed to trigger pull')
    }
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
        <div className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 text-white shadow-lg shadow-blue-500/25">
                <Building2 className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  SAM.gov Opportunities
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  Track and analyze federal contract opportunities
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
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400">
              <FileText className="w-4 h-4" />
              <span className="font-medium">{searches.reduce((acc, s) => acc + s.solicitation_count, 0)}</span>
              <span>solicitations</span>
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

        {/* Form */}
        {showForm && (
          <div className="mb-8">
            <SamSearchForm
              search={editingSearch}
              onSuccess={handleFormSuccess}
              onCancel={handleFormCancel}
            />
          </div>
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
          /* Grid of Cards */
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
            {searches.map((search) => (
              <SearchCard
                key={search.id}
                search={search}
                onEdit={() => handleEdit(search)}
                onDelete={() => handleDelete(search)}
                onTriggerPull={() => handleTriggerPull(search)}
                onClick={() => router.push(`/sam/${search.id}`)}
                formatDate={formatDate}
                getStatusColor={getStatusColor}
                getPullStatusColor={getPullStatusColor}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// Search Card Component
interface SearchCardProps {
  search: SamSearch
  onEdit: () => void
  onDelete: () => void
  onTriggerPull: () => void
  onClick: () => void
  formatDate: (date: string | null) => string
  getStatusColor: (status: string) => string
  getPullStatusColor: (status: string | null) => string
}

function SearchCard({
  search,
  onEdit,
  onDelete,
  onTriggerPull,
  onClick,
  formatDate,
  getStatusColor,
  getPullStatusColor,
}: SearchCardProps) {
  const [showMenu, setShowMenu] = useState(false)

  return (
    <div
      onClick={onClick}
      className="group relative bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 hover:shadow-lg hover:shadow-gray-200/50 dark:hover:shadow-gray-900/50 transition-all duration-200 overflow-hidden cursor-pointer"
    >
      {/* Status bar at top */}
      <div className={`absolute top-0 left-0 right-0 h-1 bg-gradient-to-r ${
        search.status === 'active'
          ? 'from-emerald-500 to-teal-500'
          : search.status === 'paused'
          ? 'from-amber-500 to-orange-500'
          : 'from-gray-400 to-gray-500'
      }`} />

      <div className="p-5">
        {/* Header */}
        <div className="flex items-start justify-between mb-3">
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-gray-900 dark:text-white truncate">
              {search.name}
            </h3>
            {search.description && (
              <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
                {search.description}
              </p>
            )}
          </div>
          <span className={`ml-2 inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${getStatusColor(search.status)}`}>
            {search.status}
          </span>
        </div>

        {/* Config Summary */}
        <div className="mb-4 space-y-1">
          {search.search_config?.naics_codes?.length > 0 && (
            <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
              <span className="font-medium">NAICS:</span>
              <span className="truncate">{search.search_config.naics_codes.slice(0, 3).join(', ')}</span>
              {search.search_config.naics_codes.length > 3 && (
                <span className="text-gray-400">+{search.search_config.naics_codes.length - 3}</span>
              )}
            </div>
          )}
          {search.search_config?.keyword && (
            <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
              <span className="font-medium">Keywords:</span>
              <span className="truncate">{search.search_config.keyword}</span>
            </div>
          )}
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div className="flex items-center gap-2 text-sm">
            <FileText className="w-4 h-4 text-blue-500" />
            <span className="text-gray-600 dark:text-gray-300">
              {search.solicitation_count} solicitations
            </span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Zap className="w-4 h-4 text-purple-500" />
            <span className="text-gray-600 dark:text-gray-300">
              {search.notice_count} notices
            </span>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between pt-4 border-t border-gray-100 dark:border-gray-700">
          <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
            <Clock className="w-3 h-3" />
            <span>Last pull: </span>
            <span className={getPullStatusColor(search.last_pull_status)}>
              {formatDate(search.last_pull_at)}
            </span>
          </div>

          {/* Dropdown menu */}
          <div className="relative" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => setShowMenu(!showMenu)}
              className="p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-all"
            >
              <MoreHorizontal className="w-4 h-4" />
            </button>

            {showMenu && (
              <div className="absolute right-0 top-full mt-1 w-48 bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 py-1 z-10">
                <button
                  onClick={() => {
                    onTriggerPull()
                    setShowMenu(false)
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                  <Play className="w-4 h-4" />
                  Pull Now
                </button>
                <button
                  onClick={() => {
                    onEdit()
                    setShowMenu(false)
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                  <Pencil className="w-4 h-4" />
                  Edit
                </button>
                <hr className="my-1 border-gray-200 dark:border-gray-700" />
                <button
                  onClick={() => {
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
      </div>
    </div>
  )
}

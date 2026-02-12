'use client'

import { useState, useEffect, use, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { useActiveJobs } from '@/lib/context-shims'
import { useJobProgress } from '@/lib/useJobProgress'
import { JobProgressPanel } from '@/components/ui/JobProgressPanel'
import { samApi, SamSearch, SamPullHistoryItem } from '@/lib/api'
import { formatDate as formatDateUtil, formatCompact, formatDuration as formatDurationUtil } from '@/lib/date-utils'
import { Button } from '@/components/ui/Button'
import toast from 'react-hot-toast'
import Link from 'next/link'
import {
  ArrowLeft,
  RefreshCw,
  Loader2,
  AlertTriangle,
  Building2,
  FileText,
  Clock,
  Zap,
  Calendar,
  Play,
  ChevronLeft,
  ChevronRight,
  CheckCircle,
  XCircle,
  AlertCircle,
  Pencil,
  History,
  ExternalLink,
} from 'lucide-react'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import SamSearchForm from '@/components/sam/SamSearchForm'

interface PageProps {
  params: Promise<{ searchId: string }>
}

export default function SamSearchDetailPage({ params }: PageProps) {
  return (
    <ProtectedRoute>
      <SamSearchDetailContent params={params} />
    </ProtectedRoute>
  )
}

function SamSearchDetailContent({ params }: PageProps) {
  const resolvedParams = use(params)
  const searchId = resolvedParams.searchId
  const router = useRouter()
  const { token } = useAuth()
  const { addJob } = useActiveJobs()

  // State
  const [search, setSearch] = useState<SamSearch | null>(null)
  const [pullHistory, setPullHistory] = useState<SamPullHistoryItem[]>([])
  const [totalPulls, setTotalPulls] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [error, setError] = useState('')
  const [isPulling, setIsPulling] = useState(false)
  const [showEditForm, setShowEditForm] = useState(false)

  // Track pull jobs and auto-refresh on completion
  const { isActive: isPullJobActive } = useJobProgress('sam_search', searchId, {
    onComplete: () => {
      loadSearch()
      loadPullHistory()
      setIsPulling(false)
    },
  })

  // Pagination
  const [page, setPage] = useState(1)
  const pageSize = 10

  // Load search details
  const loadSearch = useCallback(async () => {
    if (!token) return

    try {
      const data = await samApi.getSearch(token, searchId)
      setSearch(data)
    } catch (err: any) {
      setError(err.message || 'Failed to load search')
    }
  }, [token, searchId])

  // Load pull history
  const loadPullHistory = useCallback(async () => {
    if (!token) return

    setIsLoadingHistory(true)
    try {
      const data = await samApi.getPullHistory(token, searchId, {
        limit: pageSize,
        offset: (page - 1) * pageSize,
      })
      setPullHistory(data.items)
      setTotalPulls(data.total)
    } catch (err: any) {
      setError(err.message || 'Failed to load pull history')
    } finally {
      setIsLoadingHistory(false)
    }
  }, [token, searchId, page])

  // Initial load
  useEffect(() => {
    const loadData = async () => {
      setIsLoading(true)
      await loadSearch()
      setIsLoading(false)
    }
    if (token) loadData()
  }, [token, loadSearch])

  // Load pull history when page changes or after initial load
  useEffect(() => {
    if (token && !isLoading) {
      loadPullHistory()
    }
  }, [token, isLoading, loadPullHistory])

  // Handlers
  const handleTriggerPull = async () => {
    if (!token) return

    setIsPulling(true)
    setError('')
    try {
      const result = await samApi.triggerPull(token, searchId)

      // Track the job in the activity monitor
      if (result.run_id) {
        addJob({
          runId: result.run_id,
          jobType: 'sam_pull',
          displayName: `Pull: ${search?.name || 'SAM.gov Search'}`,
          resourceId: searchId,
          resourceType: 'sam_search',
        })
      }

      if (result.status === 'queued') {
        toast.success('Pull task queued. Results will appear as they are processed.')
      } else {
        toast.success(`Pull completed: ${result.new_solicitations || 0} new solicitations`)
      }
      // WebSocket hook handles refresh on job completion
    } catch (err: any) {
      setError(err.message || 'Failed to trigger pull')
      toast.error(err.message || 'Failed to trigger pull')
      setIsPulling(false)
    }
  }

  const handleEditSuccess = () => {
    setShowEditForm(false)
    loadSearch()
  }

  // Use date utilities for consistent EST display
  const formatDate = (dateStr: string | null) => dateStr ? formatDateUtil(dateStr) : 'N/A'
  const formatDateTime = (dateStr: string | null) => dateStr ? formatCompact(dateStr) : 'Never'
  const formatDuration = (start: string | null, end: string | null) => formatDurationUtil(start, end)

  const getStatusBadge = (status: string) => {
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

  const getPullStatusBadge = (status: string) => {
    switch (status) {
      case 'completed':
        return {
          bg: 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400',
          icon: <CheckCircle className="w-3 h-3" />,
        }
      case 'running':
        return {
          bg: 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400',
          icon: <RefreshCw className="w-3 h-3 animate-spin" />,
        }
      case 'failed':
        return {
          bg: 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400',
          icon: <XCircle className="w-3 h-3" />,
        }
      case 'pending':
        return {
          bg: 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400',
          icon: <Clock className="w-3 h-3" />,
        }
      default:
        return {
          bg: 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400',
          icon: <AlertCircle className="w-3 h-3" />,
        }
    }
  }

  // SAM.gov ptype values - see: https://open.gsa.gov/api/opportunities-api/
  const getNoticeTypeLabel = (noticeType: string) => {
    const labels: Record<string, string> = {
      k: 'Combined Synopsis',  // Combined Synopsis/Solicitation
      o: 'Solicitation',
      p: 'Presolicitation',
      r: 'Sources Sought',
      s: 'Special Notice',
      a: 'Award',
      u: 'J&A',                // Justification (J&A)
      i: 'Intent to Bundle',
      g: 'Sale of Surplus',
    }
    return labels[noticeType] || noticeType.toUpperCase()
  }

  const totalPages = Math.ceil(totalPulls / pageSize)

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-blue-500 animate-spin" />
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading search details...</p>
          </div>
        </div>
      </div>
    )
  }

  if (!search) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="text-center py-16">
            <AlertTriangle className="w-12 h-12 mx-auto text-red-500 mb-4" />
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Search Not Found</h2>
            <p className="text-gray-500 dark:text-gray-400 mb-6">{error || 'The requested search could not be found.'}</p>
            <Link href="/sam/setup">
              <Button variant="secondary" className="gap-2">
                <ArrowLeft className="w-4 h-4" />
                Back to SAM Setup
              </Button>
            </Link>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Back Link */}
        <Link
          href="/sam/setup"
          className="inline-flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to SAM Setup
        </Link>

        {/* Header */}
        <div className="mb-8">
          <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-14 h-14 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 text-white shadow-lg shadow-blue-500/25">
                <Building2 className="w-7 h-7" />
              </div>
              <div>
                <div className="flex items-center gap-3">
                  <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                    {search.name}
                  </h1>
                  <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${getStatusBadge(search.status)}`}>
                    {search.status}
                  </span>
                </div>
                {search.description && (
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                    {search.description}
                  </p>
                )}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                onClick={() => setShowEditForm(true)}
                className="gap-2"
              >
                <Pencil className="w-4 h-4" />
                Edit
              </Button>
              <Button
                onClick={handleTriggerPull}
                disabled={isPulling || isPullJobActive}
                className="gap-2 shadow-lg shadow-blue-500/25"
              >
                {(isPulling || isPullJobActive) ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Pulling...
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4" />
                    Pull Now
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>

        {/* Edit Form Modal */}
        {showEditForm && (
          <SamSearchForm
            search={search}
            onSuccess={handleEditSuccess}
            onCancel={() => setShowEditForm(false)}
          />
        )}

        {/* Error */}
        {error && (
          <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
            <div className="flex items-center gap-3">
              <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
              <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
            </div>
          </div>
        )}

        {/* Job Progress */}
        <JobProgressPanel
          resourceType="sam_search"
          resourceId={searchId}
          className="mb-8"
        />

        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Calendar className="w-4 h-4 text-blue-500" />
              <span className="text-xs text-gray-500 dark:text-gray-400">Date Range</span>
            </div>
            <p className="text-sm font-medium text-gray-900 dark:text-white">
              {search.search_config?.posted_from
                ? `From ${search.search_config.posted_from}`
                : search.search_config?.active_only
                ? 'Active only'
                : 'All dates'}
            </p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-2 mb-2">
              <History className="w-4 h-4 text-purple-500" />
              <span className="text-xs text-gray-500 dark:text-gray-400">Total Pulls</span>
            </div>
            <p className="text-2xl font-bold text-gray-900 dark:text-white">{totalPulls}</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Clock className="w-4 h-4 text-amber-500" />
              <span className="text-xs text-gray-500 dark:text-gray-400">Last Pull</span>
            </div>
            <p className="text-sm font-medium text-gray-900 dark:text-white">{formatDateTime(search.last_pull_at)}</p>
            {search.last_pull_status && (
              <span className={`text-xs ${
                search.last_pull_status === 'success' ? 'text-emerald-600' :
                search.last_pull_status === 'partial' ? 'text-amber-600' :
                'text-red-600'
              }`}>
                {search.last_pull_status}
              </span>
            )}
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-2 mb-2">
              <RefreshCw className="w-4 h-4 text-emerald-500" />
              <span className="text-xs text-gray-500 dark:text-gray-400">Frequency</span>
            </div>
            <p className="text-sm font-medium text-gray-900 dark:text-white capitalize">{search.pull_frequency}</p>
          </div>
        </div>

        {/* Search Config Summary */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 mb-8">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Search Configuration</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {search.search_config?.naics_codes?.length > 0 && (
              <div>
                <span className="text-xs text-gray-500 dark:text-gray-400 block mb-1">NAICS Codes</span>
                <div className="flex flex-wrap gap-1">
                  {search.search_config.naics_codes.map((code: string) => (
                    <span key={code} className="px-2 py-0.5 text-xs font-mono bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400 rounded">
                      {code}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {search.search_config?.psc_codes?.length > 0 && (
              <div>
                <span className="text-xs text-gray-500 dark:text-gray-400 block mb-1">PSC Codes</span>
                <div className="flex flex-wrap gap-1">
                  {search.search_config.psc_codes.map((code: string) => (
                    <span key={code} className="px-2 py-0.5 text-xs font-mono bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-400 rounded">
                      {code}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {search.search_config?.set_aside_codes?.length > 0 && (
              <div>
                <span className="text-xs text-gray-500 dark:text-gray-400 block mb-1">Set-Asides</span>
                <div className="flex flex-wrap gap-1">
                  {search.search_config.set_aside_codes.map((code: string) => (
                    <span key={code} className="px-2 py-0.5 text-xs font-mono bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 rounded">
                      {code}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {search.search_config?.notice_types?.length > 0 && (
              <div>
                <span className="text-xs text-gray-500 dark:text-gray-400 block mb-1">Notice Types</span>
                <div className="flex flex-wrap gap-1">
                  {search.search_config.notice_types.map((type: string) => (
                    <span key={type} className="px-2 py-0.5 text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded">
                      {getNoticeTypeLabel(type)}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {search.search_config?.keyword && (
              <div>
                <span className="text-xs text-gray-500 dark:text-gray-400 block mb-1">Keywords</span>
                <span className="text-sm text-gray-900 dark:text-white">{search.search_config.keyword}</span>
              </div>
            )}
            {search.search_config?.department && (
              <div>
                <span className="text-xs text-gray-500 dark:text-gray-400 block mb-1">Department</span>
                <span className="text-sm text-gray-900 dark:text-white">{search.search_config.department}</span>
              </div>
            )}
            {search.search_config?.posted_from && (
              <div>
                <span className="text-xs text-gray-500 dark:text-gray-400 block mb-1">Posted From</span>
                <span className="text-sm text-gray-900 dark:text-white">{formatDate(search.search_config.posted_from)}</span>
              </div>
            )}
          </div>
        </div>

        {/* Pull History Section */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <History className="w-5 h-5 text-gray-400" />
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Pull History</h3>
                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                  {totalPulls}
                </span>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={loadPullHistory}
                disabled={isLoadingHistory}
                className="gap-1.5"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isLoadingHistory ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
            </div>
          </div>

          {isLoadingHistory ? (
            <div className="flex flex-col items-center justify-center py-12">
              <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
              <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">Loading pull history...</p>
            </div>
          ) : pullHistory.length === 0 ? (
            <div className="text-center py-12">
              <History className="w-12 h-12 mx-auto text-gray-300 dark:text-gray-600 mb-4" />
              <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">No Pull History</h3>
              <p className="text-gray-500 dark:text-gray-400 mb-6">
                Trigger a pull to fetch solicitations from SAM.gov.
              </p>
              <Button onClick={handleTriggerPull} disabled={isPulling} className="gap-2">
                <Play className="w-4 h-4" />
                Pull Now
              </Button>
            </div>
          ) : (
            <>
              {/* Table */}
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700">
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Started
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Duration
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Status
                      </th>
                      <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Fetched
                      </th>
                      <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        New
                      </th>
                      <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Updated
                      </th>
                      <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Notices
                      </th>
                      <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Attachments
                      </th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                    {pullHistory.map((pull) => {
                      const statusBadge = getPullStatusBadge(pull.status)
                      return (
                        <tr key={pull.id} className="hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors">
                          <td className="px-4 py-4">
                            <div>
                              <p className="text-sm font-medium text-gray-900 dark:text-white">
                                {formatDateTime(pull.started_at)}
                              </p>
                              {pull.completed_at && (
                                <p className="text-xs text-gray-500 dark:text-gray-400">
                                  Completed {formatDateTime(pull.completed_at)}
                                </p>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-4 text-sm text-gray-600 dark:text-gray-400">
                            {formatDuration(pull.started_at, pull.completed_at)}
                          </td>
                          <td className="px-4 py-4">
                            <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium rounded ${statusBadge.bg}`}>
                              {statusBadge.icon}
                              {pull.status}
                            </span>
                            {pull.error_message && (
                              <p className="text-xs text-red-600 dark:text-red-400 mt-1 truncate max-w-[200px]" title={pull.error_message}>
                                {pull.error_message}
                              </p>
                            )}
                          </td>
                          <td className="px-4 py-4 text-center">
                            <span className="text-sm font-medium text-gray-900 dark:text-white">
                              {pull.results_summary?.total_fetched ?? '-'}
                            </span>
                          </td>
                          <td className="px-4 py-4 text-center">
                            <span className={`text-sm font-medium ${
                              (pull.results_summary?.new_solicitations ?? 0) > 0
                                ? 'text-emerald-600 dark:text-emerald-400'
                                : 'text-gray-500 dark:text-gray-400'
                            }`}>
                              {pull.results_summary?.new_solicitations ?? '-'}
                            </span>
                          </td>
                          <td className="px-4 py-4 text-center">
                            <span className={`text-sm font-medium ${
                              (pull.results_summary?.updated_solicitations ?? 0) > 0
                                ? 'text-blue-600 dark:text-blue-400'
                                : 'text-gray-500 dark:text-gray-400'
                            }`}>
                              {pull.results_summary?.updated_solicitations ?? '-'}
                            </span>
                          </td>
                          <td className="px-4 py-4 text-center">
                            <span className="text-sm text-gray-600 dark:text-gray-400">
                              {pull.results_summary?.new_notices ?? '-'}
                            </span>
                          </td>
                          <td className="px-4 py-4 text-center">
                            <span className="text-sm text-gray-600 dark:text-gray-400">
                              {pull.results_summary?.new_attachments ?? '-'}
                            </span>
                          </td>
                          <td className="px-4 py-4 text-right">
                            <Link
                              href={`/admin/queue/${pull.id}`}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-lg transition-colors"
                            >
                              View Job
                              <ExternalLink className="w-3 h-3" />
                            </Link>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 dark:border-gray-700">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ChevronLeft className="w-4 h-4" />
                    Previous
                  </button>
                  <span className="text-sm text-gray-500 dark:text-gray-400">
                    Page {page} of {totalPages}
                  </span>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Next
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              )}
            </>
          )}
        </div>

        {/* Link to all solicitations */}
        <div className="mt-6 text-center">
          <Link
            href="/sam/solicitations"
            className="inline-flex items-center gap-2 text-sm text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300"
          >
            <FileText className="w-4 h-4" />
            View all solicitations
          </Link>
        </div>
      </div>
    </div>
  )
}

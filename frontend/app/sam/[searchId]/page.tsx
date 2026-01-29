'use client'

import { useState, useEffect, use, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { samApi, SamSearch, SamSolicitation } from '@/lib/api'
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
  ExternalLink,
  Play,
  Pause,
  ChevronLeft,
  ChevronRight,
  Filter,
  Search,
  Tag,
  AlertCircle,
  CheckCircle,
  XCircle,
  Pencil,
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

  // State
  const [search, setSearch] = useState<SamSearch | null>(null)
  const [solicitations, setSolicitations] = useState<SamSolicitation[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [isLoadingSolicitations, setIsLoadingSolicitations] = useState(false)
  const [error, setError] = useState('')
  const [isPulling, setIsPulling] = useState(false)
  const [showEditForm, setShowEditForm] = useState(false)

  // Filters & Pagination
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [noticeTypeFilter, setNoticeTypeFilter] = useState<string>('')
  const [naicsFilter, setNaicsFilter] = useState<string>('')
  const [page, setPage] = useState(1)
  const pageSize = 20

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

  // Load solicitations with filters
  const loadSolicitations = useCallback(async () => {
    if (!token) return

    setIsLoadingSolicitations(true)
    try {
      const params: any = {
        search_id: searchId,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      }
      if (statusFilter) params.status = statusFilter
      if (noticeTypeFilter) params.notice_type = noticeTypeFilter
      if (naicsFilter) params.naics_code = naicsFilter

      const data = await samApi.listSolicitations(token, params)
      setSolicitations(data.items)
      setTotal(data.total)
    } catch (err: any) {
      setError(err.message || 'Failed to load solicitations')
    } finally {
      setIsLoadingSolicitations(false)
    }
  }, [token, searchId, statusFilter, noticeTypeFilter, naicsFilter, page])

  // Initial load
  useEffect(() => {
    const loadData = async () => {
      setIsLoading(true)
      await loadSearch()
      setIsLoading(false)
    }
    if (token) loadData()
  }, [token, loadSearch])

  // Load solicitations when filters change
  useEffect(() => {
    if (token && !isLoading) {
      loadSolicitations()
    }
  }, [token, isLoading, loadSolicitations])

  // Handlers
  const handleTriggerPull = async () => {
    if (!token) return

    setIsPulling(true)
    setError('')
    try {
      const result = await samApi.triggerPull(token, searchId)
      if (result.status === 'queued') {
        toast.success('Pull task queued. Results will appear as they are processed.')
      } else {
        toast.success(`Pull completed: ${result.new_solicitations || 0} new solicitations`)
      }
      // Refresh periodically to show results as they come in
      setTimeout(() => {
        loadSearch()
        loadSolicitations()
      }, 3000)
      setTimeout(() => {
        loadSearch()
        loadSolicitations()
        setIsPulling(false)
      }, 10000)
      setTimeout(() => {
        loadSearch()
        loadSolicitations()
      }, 30000)
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

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'N/A'
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  const formatDateTime = (dateStr: string | null) => {
    if (!dateStr) return 'Never'
    return new Date(dateStr).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

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

  const getNoticeTypeBadge = (noticeType: string) => {
    const colors: Record<string, string> = {
      o: 'bg-blue-100 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400',
      p: 'bg-purple-100 dark:bg-purple-900/20 text-purple-700 dark:text-purple-400',
      k: 'bg-indigo-100 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-400',
      r: 'bg-amber-100 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400',
      s: 'bg-emerald-100 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400',
      a: 'bg-cyan-100 dark:bg-cyan-900/20 text-cyan-700 dark:text-cyan-400',
    }
    return colors[noticeType] || 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
  }

  const getNoticeTypeLabel = (noticeType: string) => {
    const labels: Record<string, string> = {
      o: 'Solicitation',
      p: 'Presolicitation',
      k: 'Combined Synopsis',
      r: 'Sources Sought',
      s: 'Special Notice',
      a: 'Award',
      i: 'Intent to Bundle',
      g: 'Sale of Surplus',
    }
    return labels[noticeType] || noticeType.toUpperCase()
  }

  const totalPages = Math.ceil(total / pageSize)

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
            <Link href="/sam">
              <Button variant="secondary" className="gap-2">
                <ArrowLeft className="w-4 h-4" />
                Back to SAM Searches
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
          href="/sam"
          className="inline-flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to SAM Searches
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
                disabled={isPulling}
                className="gap-2 shadow-lg shadow-blue-500/25"
              >
                {isPulling ? (
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
          <div className="mb-8">
            <SamSearchForm
              search={search}
              onSuccess={handleEditSuccess}
              onCancel={() => setShowEditForm(false)}
            />
          </div>
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

        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-2 mb-2">
              <FileText className="w-4 h-4 text-blue-500" />
              <span className="text-xs text-gray-500 dark:text-gray-400">Solicitations</span>
            </div>
            <p className="text-2xl font-bold text-gray-900 dark:text-white">{search.solicitation_count}</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Zap className="w-4 h-4 text-purple-500" />
              <span className="text-xs text-gray-500 dark:text-gray-400">Notices</span>
            </div>
            <p className="text-2xl font-bold text-gray-900 dark:text-white">{search.notice_count}</p>
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

        {/* Filters */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 mb-6">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-gray-400" />
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Filters:</span>
            </div>

            {/* Status Filter */}
            <select
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
              className="px-3 py-1.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
            >
              <option value="">All Statuses</option>
              <option value="active">Active</option>
              <option value="awarded">Awarded</option>
              <option value="cancelled">Cancelled</option>
            </select>

            {/* Notice Type Filter */}
            <select
              value={noticeTypeFilter}
              onChange={(e) => { setNoticeTypeFilter(e.target.value); setPage(1); }}
              className="px-3 py-1.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
            >
              <option value="">All Notice Types</option>
              <option value="o">Solicitation</option>
              <option value="p">Presolicitation</option>
              <option value="k">Combined Synopsis</option>
              <option value="r">Sources Sought</option>
              <option value="s">Special Notice</option>
              <option value="a">Award</option>
            </select>

            {/* NAICS Filter */}
            <input
              type="text"
              placeholder="NAICS Code"
              value={naicsFilter}
              onChange={(e) => { setNaicsFilter(e.target.value); setPage(1); }}
              className="w-32 px-3 py-1.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400"
            />

            {/* Clear Filters */}
            {(statusFilter || noticeTypeFilter || naicsFilter) && (
              <button
                onClick={() => {
                  setStatusFilter('')
                  setNoticeTypeFilter('')
                  setNaicsFilter('')
                  setPage(1)
                }}
                className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              >
                Clear
              </button>
            )}

            <div className="flex-1" />

            {/* Results count */}
            <span className="text-sm text-gray-500 dark:text-gray-400">
              {total} solicitation{total !== 1 ? 's' : ''}
            </span>
          </div>
        </div>

        {/* Solicitations List */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          {isLoadingSolicitations ? (
            <div className="flex flex-col items-center justify-center py-12">
              <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
              <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">Loading solicitations...</p>
            </div>
          ) : solicitations.length === 0 ? (
            <div className="text-center py-12">
              <FileText className="w-12 h-12 mx-auto text-gray-300 dark:text-gray-600 mb-4" />
              <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">No Solicitations Found</h3>
              <p className="text-gray-500 dark:text-gray-400 mb-6">
                {statusFilter || noticeTypeFilter || naicsFilter
                  ? 'Try adjusting your filters or trigger a pull to fetch new data.'
                  : 'Trigger a pull to fetch solicitations from SAM.gov.'}
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
                        Solicitation
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Organization
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Type
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        NAICS
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Posted
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Deadline
                      </th>
                      <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Items
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Status
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                    {solicitations.map((sol) => (
                      <tr
                        key={sol.id}
                        onClick={() => router.push(`/sam/solicitation/${sol.id}`)}
                        className="hover:bg-gray-50 dark:hover:bg-gray-900/50 cursor-pointer transition-colors"
                      >
                        <td className="px-4 py-4">
                          <div className="max-w-md">
                            <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                              {sol.title}
                            </p>
                            <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
                              {sol.solicitation_number || sol.notice_id}
                            </p>
                          </div>
                        </td>
                        <td className="px-4 py-4">
                          <div className="max-w-[200px]">
                            {sol.agency_name && (
                              <p className="text-xs font-medium text-gray-700 dark:text-gray-300 truncate" title={sol.agency_name}>
                                {sol.agency_name}
                              </p>
                            )}
                            {sol.bureau_name && (
                              <p className="text-xs text-gray-500 dark:text-gray-400 truncate" title={sol.bureau_name}>
                                {sol.bureau_name}
                              </p>
                            )}
                            {sol.office_name && (
                              <p className="text-xs text-gray-400 dark:text-gray-500 truncate" title={sol.office_name}>
                                {sol.office_name}
                              </p>
                            )}
                            {!sol.agency_name && !sol.bureau_name && !sol.office_name && (
                              <span className="text-xs text-gray-400">-</span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-4">
                          <span className={`inline-flex px-2 py-0.5 text-xs font-medium rounded ${getNoticeTypeBadge(sol.notice_type)}`}>
                            {getNoticeTypeLabel(sol.notice_type)}
                          </span>
                        </td>
                        <td className="px-4 py-4">
                          {sol.naics_code && (
                            <span className="text-xs font-mono text-gray-600 dark:text-gray-400">
                              {sol.naics_code}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-4 text-xs text-gray-500 dark:text-gray-400">
                          {formatDate(sol.posted_date)}
                        </td>
                        <td className="px-4 py-4">
                          {sol.response_deadline ? (
                            <span className={`text-xs ${
                              new Date(sol.response_deadline) < new Date()
                                ? 'text-red-600 dark:text-red-400'
                                : 'text-gray-600 dark:text-gray-400'
                            }`}>
                              {formatDate(sol.response_deadline)}
                            </span>
                          ) : (
                            <span className="text-xs text-gray-400">-</span>
                          )}
                        </td>
                        <td className="px-4 py-4 text-center">
                          <div className="flex items-center justify-center gap-2">
                            <span className="text-xs text-gray-500 dark:text-gray-400">
                              <Zap className="w-3 h-3 inline mr-1" />
                              {sol.notice_count}
                            </span>
                            <span className="text-xs text-gray-500 dark:text-gray-400">
                              <FileText className="w-3 h-3 inline mr-1" />
                              {sol.attachment_count}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-4">
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded ${
                            sol.status === 'active'
                              ? 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400'
                              : sol.status === 'awarded'
                              ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400'
                              : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
                          }`}>
                            {sol.status === 'active' && <CheckCircle className="w-3 h-3" />}
                            {sol.status === 'cancelled' && <XCircle className="w-3 h-3" />}
                            {sol.status}
                          </span>
                        </td>
                      </tr>
                    ))}
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
      </div>
    </div>
  )
}

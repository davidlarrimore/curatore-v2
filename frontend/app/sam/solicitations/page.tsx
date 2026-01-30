'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { samApi, SamSolicitation } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import SamNavigation from '@/components/sam/SamNavigation'
import { NoticeTypeBadge, SolicitationBadge, SamSummaryStatusBadge } from '@/components/sam/SamStatusBadge'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  Building2,
  RefreshCw,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Filter,
  X,
  Calendar,
  FileText,
  Sparkles,
} from 'lucide-react'

export default function SamSolicitationsPage() {
  return (
    <ProtectedRoute>
      <SamSolicitationsContent />
    </ProtectedRoute>
  )
}

function SamSolicitationsContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { token } = useAuth()

  // State
  const [solicitations, setSolicitations] = useState<SamSolicitation[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  // Filters
  const [showFilters, setShowFilters] = useState(false)
  const [statusFilter, setStatusFilter] = useState(searchParams.get('status') || '')
  const [noticeTypeFilter, setNoticeTypeFilter] = useState(searchParams.get('notice_type') || '')
  const [naicsFilter, setNaicsFilter] = useState(searchParams.get('naics_code') || '')
  const [page, setPage] = useState(1)
  const pageSize = 25

  // Load solicitations
  const loadSolicitations = useCallback(async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const params: any = {
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
      setIsLoading(false)
    }
  }, [token, page, statusFilter, noticeTypeFilter, naicsFilter])

  useEffect(() => {
    if (token) {
      loadSolicitations()
    }
  }, [token, loadSolicitations])

  const clearFilters = () => {
    setStatusFilter('')
    setNoticeTypeFilter('')
    setNaicsFilter('')
    setPage(1)
  }

  const hasFilters = statusFilter || noticeTypeFilter || naicsFilter

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-'
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  }

  // Check if solicitation is new (created within last 7 days)
  const isNew = (sol: SamSolicitation) => {
    const created = new Date(sol.created_at)
    const sevenDaysAgo = new Date()
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7)
    return created >= sevenDaysAgo
  }

  // Check if solicitation was updated (updated !== created and within last 7 days)
  const isUpdated = (sol: SamSolicitation) => {
    if (sol.created_at === sol.updated_at) return false
    const updated = new Date(sol.updated_at)
    const sevenDaysAgo = new Date()
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7)
    return updated >= sevenDaysAgo && sol.notice_count > 1
  }

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-purple-500 to-indigo-600 text-white shadow-lg shadow-purple-500/25">
                <Building2 className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  All Solicitations
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  {total.toLocaleString()} solicitations across all searches
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
                onClick={loadSolicitations}
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

        {/* Filters Panel */}
        {showFilters && (
          <div className="mb-6 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex flex-wrap items-end gap-4">
              <div className="w-[150px]">
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Status
                </label>
                <select
                  value={statusFilter}
                  onChange={(e) => {
                    setStatusFilter(e.target.value)
                    setPage(1)
                  }}
                  className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
                >
                  <option value="">All</option>
                  <option value="active">Active</option>
                  <option value="awarded">Awarded</option>
                  <option value="cancelled">Cancelled</option>
                </select>
              </div>

              <div className="w-[180px]">
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
                  <option value="o">Combined Synopsis/Solicitation</option>
                  <option value="p">Presolicitation</option>
                  <option value="k">Sources Sought</option>
                  <option value="r">Special Notice</option>
                  <option value="s">Award Notice</option>
                </select>
              </div>

              <div className="flex-1 min-w-[150px]">
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                  NAICS Code
                </label>
                <input
                  type="text"
                  value={naicsFilter}
                  onChange={(e) => {
                    setNaicsFilter(e.target.value)
                    setPage(1)
                  }}
                  placeholder="e.g., 541512"
                  className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
                />
              </div>

              {hasFilters && (
                <Button
                  variant="secondary"
                  onClick={clearFilters}
                  className="gap-1"
                >
                  <X className="w-4 h-4" />
                  Clear
                </Button>
              )}
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

        {/* Loading State */}
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-purple-500 animate-spin" />
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading solicitations...</p>
          </div>
        ) : solicitations.length === 0 ? (
          <div className="text-center py-16">
            <Building2 className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <p className="text-gray-500 dark:text-gray-400">
              {hasFilters ? 'No solicitations match your filters.' : 'No solicitations found.'}
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
                      <th className="text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider px-4 py-3">
                        Sol #
                      </th>
                      <th className="text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider px-4 py-3">
                        Title
                      </th>
                      <th className="text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider px-4 py-3">
                        Agency
                      </th>
                      <th className="text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider px-4 py-3">
                        Type
                      </th>
                      <th className="text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider px-4 py-3">
                        Status
                      </th>
                      <th className="text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider px-4 py-3">
                        Deadline
                      </th>
                      <th className="text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider px-4 py-3">
                        Summary
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                    {solicitations.map((sol) => (
                      <tr
                        key={sol.id}
                        onClick={() => router.push(`/sam/solicitations/${sol.id}`)}
                        className="hover:bg-gray-50 dark:hover:bg-gray-750 cursor-pointer transition-colors"
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-mono text-gray-900 dark:text-white">
                              {sol.solicitation_number || '-'}
                            </span>
                            <SolicitationBadge isNew={isNew(sol)} isUpdated={!isNew(sol) && isUpdated(sol)} />
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-sm font-medium text-gray-900 dark:text-white truncate max-w-[250px]">
                            {sol.title}
                          </p>
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-sm text-gray-600 dark:text-gray-400 truncate max-w-[150px]">
                            {sol.agency_name || '-'}
                          </p>
                        </td>
                        <td className="px-4 py-3">
                          <NoticeTypeBadge type={sol.notice_type} />
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-xs px-2 py-1 rounded-full ${
                            sol.status === 'active'
                              ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300'
                              : sol.status === 'awarded'
                              ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                              : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
                          }`}>
                            {sol.status}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-sm text-gray-600 dark:text-gray-400">
                            {formatDate(sol.response_deadline)}
                          </p>
                        </td>
                        <td className="px-4 py-3">
                          <SamSummaryStatusBadge status={sol.summary_status} />
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

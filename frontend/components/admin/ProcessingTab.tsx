'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { useAuth } from '@/lib/auth-context'
import { runsApi, RunStats } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { formatDateTime, formatTimeAgo, formatDuration } from '@/lib/date-utils'
import {
  Activity,
  CheckCircle,
  XCircle,
  Clock,
  Loader2,
  RefreshCw,
  ChevronRight,
  AlertTriangle,
  FileText,
  Wrench,
  Globe,
  Zap,
  Search,
} from 'lucide-react'
import clsx from 'clsx'

interface Run {
  id: string
  run_type: string
  origin: string
  status: string
  input_asset_ids: string[]
  config: Record<string, any>
  progress: Record<string, any> | null
  results_summary: Record<string, any> | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

interface ProcessingTabProps {
  onError?: (message: string) => void
}

export default function ProcessingTab({ onError }: ProcessingTabProps) {
  const { token } = useAuth()
  const [stats, setStats] = useState<RunStats | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [selectedRun, setSelectedRun] = useState<Run | null>(null)
  const [filter, setFilter] = useState<'all' | 'running' | 'completed' | 'failed'>('all')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [page, setPage] = useState(0)
  const [total, setTotal] = useState(0)
  const pageSize = 20

  const loadData = useCallback(async (showRefreshing = false) => {
    if (!token) return

    if (showRefreshing) setIsRefreshing(true)
    else setIsLoading(true)

    try {
      const [statsData, runsData] = await Promise.all([
        runsApi.getStats(token),
        runsApi.listRuns(token, {
          status: filter === 'all' ? undefined : filter,
          run_type: typeFilter === 'all' ? undefined : typeFilter,
          limit: pageSize,
          offset: page * pageSize,
        }),
      ])

      setStats(statsData)
      setRuns(runsData.items || [])
      setTotal(runsData.total || 0)
    } catch (err: any) {
      console.error('Failed to load processing data:', err)
      onError?.(err.message || 'Failed to load processing data')
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [token, filter, typeFilter, page, onError])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Auto-refresh every 10 seconds
  useEffect(() => {
    const interval = setInterval(() => loadData(true), 10000)
    return () => clearInterval(interval)
  }, [loadData])

  const getRunTypeIcon = (runType: string) => {
    switch (runType) {
      case 'extraction':
        return <FileText className="w-4 h-4" />
      case 'extraction_enhancement':
        return <Zap className="w-4 h-4" />
      case 'system_maintenance':
        return <Wrench className="w-4 h-4" />
      case 'scrape':
        return <Globe className="w-4 h-4" />
      case 'sam_pull':
        return <Search className="w-4 h-4" />
      default:
        return <Activity className="w-4 h-4" />
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20'
      case 'failed':
        return 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20'
      case 'running':
        return 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20'
      case 'pending':
        return 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20'
      case 'cancelled':
        return 'text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-900/20'
      default:
        return 'text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-900/20'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-4 h-4 text-emerald-500" />
      case 'failed':
        return <XCircle className="w-4 h-4 text-red-500" />
      case 'running':
        return <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
      case 'pending':
        return <Clock className="w-4 h-4 text-amber-500" />
      case 'cancelled':
        return <XCircle className="w-4 h-4 text-gray-500" />
      default:
        return <Activity className="w-4 h-4 text-gray-500" />
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="text-center">
          <Loader2 className="w-8 h-8 text-indigo-600 animate-spin mx-auto" />
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">Loading processing data...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header with refresh */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Processing Overview</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Monitor extraction runs, system maintenance, and processing jobs
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => loadData(true)}
          disabled={isRefreshing}
        >
          <RefreshCw className={clsx("w-4 h-4 mr-2", isRefreshing && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {/* Active Runs */}
          <div className="bg-indigo-50 dark:bg-indigo-900/20 rounded-xl p-4 border border-indigo-100 dark:border-indigo-800/50">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-indigo-500 flex items-center justify-center">
                <Activity className="w-5 h-5 text-white" />
              </div>
              <div>
                <p className="text-2xl font-bold text-indigo-700 dark:text-indigo-300">
                  {(stats.runs.by_status['running'] || 0) + (stats.runs.by_status['pending'] || 0)}
                </p>
                <p className="text-xs text-indigo-600 dark:text-indigo-400">Active Runs</p>
              </div>
            </div>
          </div>

          {/* Completed Today */}
          <div className="bg-emerald-50 dark:bg-emerald-900/20 rounded-xl p-4 border border-emerald-100 dark:border-emerald-800/50">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-500 flex items-center justify-center">
                <CheckCircle className="w-5 h-5 text-white" />
              </div>
              <div>
                <p className="text-2xl font-bold text-emerald-700 dark:text-emerald-300">
                  {stats.recent_24h.by_status['completed'] || 0}
                </p>
                <p className="text-xs text-emerald-600 dark:text-emerald-400">Completed (24h)</p>
              </div>
            </div>
          </div>

          {/* Failed Today */}
          <div className="bg-red-50 dark:bg-red-900/20 rounded-xl p-4 border border-red-100 dark:border-red-800/50">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-red-500 flex items-center justify-center">
                <XCircle className="w-5 h-5 text-white" />
              </div>
              <div>
                <p className="text-2xl font-bold text-red-700 dark:text-red-300">
                  {stats.recent_24h.by_status['failed'] || 0}
                </p>
                <p className="text-xs text-red-600 dark:text-red-400">Failed (24h)</p>
              </div>
            </div>
          </div>

          {/* Queue Size */}
          <div className="bg-amber-50 dark:bg-amber-900/20 rounded-xl p-4 border border-amber-100 dark:border-amber-800/50">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-amber-500 flex items-center justify-center">
                <Clock className="w-5 h-5 text-white" />
              </div>
              <div>
                <p className="text-2xl font-bold text-amber-700 dark:text-amber-300">
                  {(stats.queues.processing || 0) + (stats.queues.processing_priority || 0)}
                </p>
                <p className="text-xs text-amber-600 dark:text-amber-400">In Queue</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Run Type Breakdown */}
      {stats && (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">Runs by Type</h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.runs.by_type).map(([type, count]) => (
              <div
                key={type}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-900/50 text-sm"
              >
                {getRunTypeIcon(type)}
                <span className="text-gray-700 dark:text-gray-300 capitalize">
                  {type.replace(/_/g, ' ')}
                </span>
                <span className="font-mono font-medium text-gray-900 dark:text-white">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-4">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500 dark:text-gray-400">Status:</span>
          <div className="flex gap-1">
            {['all', 'running', 'completed', 'failed'].map((f) => (
              <button
                key={f}
                onClick={() => { setFilter(f as any); setPage(0) }}
                className={clsx(
                  "px-3 py-1 text-xs font-medium rounded-lg transition-colors",
                  filter === f
                    ? "bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300"
                    : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700"
                )}
              >
                {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500 dark:text-gray-400">Type:</span>
          <select
            value={typeFilter}
            onChange={(e) => { setTypeFilter(e.target.value); setPage(0) }}
            className="px-3 py-1 text-xs font-medium rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 border-0 focus:ring-2 focus:ring-indigo-500"
          >
            <option value="all">All Types</option>
            <option value="extraction">Extraction</option>
            <option value="extraction_enhancement">Enhancement</option>
            <option value="system_maintenance">Maintenance</option>
            <option value="scrape">Scrape</option>
            <option value="sam_pull">SAM Pull</option>
          </select>
        </div>
      </div>

      {/* Runs Table */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-900/50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider w-8">
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                  Type
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                  Origin
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                  Duration
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                  Time
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {runs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-500 dark:text-gray-400">
                    No runs found matching your filters
                  </td>
                </tr>
              ) : (
                runs.map((run) => {
                  const isExpanded = selectedRun?.id === run.id
                  return (
                    <React.Fragment key={run.id}>
                      <tr
                        className={clsx(
                          "hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors cursor-pointer",
                          isExpanded && "bg-indigo-50 dark:bg-indigo-900/20"
                        )}
                        onClick={() => setSelectedRun(isExpanded ? null : run)}
                      >
                        <td className="px-4 py-3 whitespace-nowrap">
                          <ChevronRight className={clsx(
                            "w-4 h-4 text-gray-400 transition-transform duration-200",
                            isExpanded && "rotate-90"
                          )} />
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            <span className="text-gray-500 dark:text-gray-400">
                              {getRunTypeIcon(run.run_type)}
                            </span>
                            <span className="text-sm text-gray-900 dark:text-white capitalize">
                              {run.run_type.replace(/_/g, ' ')}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <span className={clsx(
                            "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium",
                            getStatusColor(run.status)
                          )}>
                            {getStatusIcon(run.status)}
                            {run.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600 dark:text-gray-400 capitalize">
                          {run.origin}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-sm font-mono text-gray-600 dark:text-gray-400">
                          {formatDuration(run.started_at, run.completed_at)}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600 dark:text-gray-400">
                          {formatTimeAgo(run.created_at)}
                        </td>
                      </tr>
                      {/* Accordion Detail Row */}
                      {isExpanded && (
                        <tr className="bg-gray-50 dark:bg-gray-900/30">
                          <td colSpan={6} className="px-4 py-0">
                            <div className="py-4 border-l-4 border-indigo-500 pl-4 ml-2">
                              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                                <div>
                                  <p className="text-xs text-gray-500 dark:text-gray-400">Run ID</p>
                                  <p className="text-sm font-mono text-gray-900 dark:text-white truncate">{run.id}</p>
                                </div>
                                <div>
                                  <p className="text-xs text-gray-500 dark:text-gray-400">Created</p>
                                  <p className="text-sm text-gray-900 dark:text-white">
                                    {formatDateTime(run.created_at)}
                                  </p>
                                </div>
                                <div>
                                  <p className="text-xs text-gray-500 dark:text-gray-400">Started</p>
                                  <p className="text-sm text-gray-900 dark:text-white">
                                    {formatDateTime(run.started_at)}
                                  </p>
                                </div>
                                <div>
                                  <p className="text-xs text-gray-500 dark:text-gray-400">Completed</p>
                                  <p className="text-sm text-gray-900 dark:text-white">
                                    {formatDateTime(run.completed_at)}
                                  </p>
                                </div>
                              </div>

                              {run.error_message && (
                                <div className="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/50">
                                  <div className="flex items-start gap-2">
                                    <AlertTriangle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
                                    <div>
                                      <p className="text-sm font-medium text-red-800 dark:text-red-200">Error</p>
                                      <p className="text-sm text-red-700 dark:text-red-300 mt-1 break-all">
                                        {run.error_message}
                                      </p>
                                    </div>
                                  </div>
                                </div>
                              )}

                              {run.results_summary && Object.keys(run.results_summary).length > 0 && (
                                <div className="mb-4">
                                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">Results Summary</p>
                                  <pre className="text-xs bg-white dark:bg-gray-800 p-3 rounded-lg overflow-auto max-h-48 text-gray-700 dark:text-gray-300 border border-gray-200 dark:border-gray-700">
                                    {JSON.stringify(run.results_summary, null, 2)}
                                  </pre>
                                </div>
                              )}

                              {run.config && Object.keys(run.config).length > 0 && (
                                <div>
                                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">Configuration</p>
                                  <pre className="text-xs bg-white dark:bg-gray-800 p-3 rounded-lg overflow-auto max-h-32 text-gray-700 dark:text-gray-300 border border-gray-200 dark:border-gray-700">
                                    {JSON.stringify(run.config, null, 2)}
                                  </pre>
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {total > pageSize && (
          <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-700 flex items-center justify-between">
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Showing {page * pageSize + 1} - {Math.min((page + 1) * pageSize, total)} of {total}
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setPage(p => p - 1)}
                disabled={page === 0}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setPage(p => p + 1)}
                disabled={(page + 1) * pageSize >= total}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

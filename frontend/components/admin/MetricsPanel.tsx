'use client'

import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '@/lib/auth-context'
import { metricsApi } from '@/lib/api'
import {
  BarChart3,
  RefreshCw,
  Loader2,
  CheckCircle,
  AlertTriangle,
  Clock,
  Zap,
  TrendingUp,
} from 'lucide-react'

interface ProcedureMetrics {
  period_days: number
  total_runs: number
  avg_duration_ms: number
  success_rate: number
  by_function: Record<string, { calls: number; avg_ms: number; errors: number }>
}

const PERIOD_OPTIONS = [7, 14, 30, 60, 90] as const

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}

export default function MetricsPanel() {
  const { token } = useAuth()
  const [metrics, setMetrics] = useState<ProcedureMetrics | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [days, setDays] = useState<number>(7)
  const [autoRefresh, setAutoRefresh] = useState(false)

  const fetchMetrics = useCallback(async () => {
    if (!token) return

    try {
      setError(null)
      const data = await metricsApi.getProcedureMetrics(token, days)
      setMetrics(data)
    } catch (err: unknown) {
      console.error('Failed to fetch metrics:', err)
      setError(err instanceof Error ? err.message : 'Failed to load metrics')
    } finally {
      setIsLoading(false)
    }
  }, [token, days])

  useEffect(() => {
    setIsLoading(true)
    fetchMetrics()
  }, [fetchMetrics])

  useEffect(() => {
    if (!autoRefresh) return
    const interval = setInterval(fetchMetrics, 30000)
    return () => clearInterval(interval)
  }, [autoRefresh, fetchMetrics])

  const handleRefresh = async () => {
    setIsLoading(true)
    await fetchMetrics()
  }

  const functionEntries = metrics
    ? Object.entries(metrics.by_function).sort(
        ([, a], [, b]) => b.calls - a.calls
      )
    : []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Procedure Metrics
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Execution metrics from procedure runs
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Period Selector */}
          <div className="flex items-center gap-1 bg-gray-100 dark:bg-gray-800 rounded-lg p-0.5">
            {PERIOD_OPTIONS.map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
                  days === d
                    ? 'bg-white dark:bg-gray-700 text-indigo-600 dark:text-indigo-400 shadow-sm'
                    : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
                }`}
              >
                {d}d
              </button>
            ))}
          </div>

          {/* Auto-refresh Toggle */}
          <label className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400 cursor-pointer">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
            />
            Auto
          </label>

          {/* Refresh Button */}
          <button
            onClick={handleRefresh}
            disabled={isLoading}
            className="p-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/50 p-4">
          <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
        </div>
      )}

      {isLoading && !metrics ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 text-gray-400 animate-spin" />
        </div>
      ) : metrics ? (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Total Runs */}
            <div className="bg-gradient-to-br from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-xl p-4 border border-indigo-100 dark:border-indigo-800/30">
              <div className="flex items-center gap-2 mb-2">
                <BarChart3 className="w-4 h-4 text-indigo-500" />
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                  Total Runs
                </span>
              </div>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">
                {metrics.total_runs.toLocaleString()}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Last {metrics.period_days} days
              </p>
            </div>

            {/* Success Rate */}
            <div className="bg-gradient-to-br from-emerald-50 to-teal-50 dark:from-emerald-900/20 dark:to-teal-900/20 rounded-xl p-4 border border-emerald-100 dark:border-emerald-800/30">
              <div className="flex items-center gap-2 mb-2">
                <CheckCircle className="w-4 h-4 text-emerald-500" />
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                  Success Rate
                </span>
              </div>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">
                {metrics.total_runs > 0
                  ? `${(metrics.success_rate * 100).toFixed(1)}%`
                  : 'N/A'}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                {metrics.total_runs > 0
                  ? `${Math.round(metrics.success_rate * metrics.total_runs)} successful`
                  : 'No data'}
              </p>
            </div>

            {/* Avg Duration */}
            <div className="bg-gradient-to-br from-blue-50 to-cyan-50 dark:from-blue-900/20 dark:to-cyan-900/20 rounded-xl p-4 border border-blue-100 dark:border-blue-800/30">
              <div className="flex items-center gap-2 mb-2">
                <Clock className="w-4 h-4 text-blue-500" />
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                  Avg Duration
                </span>
              </div>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">
                {metrics.total_runs > 0
                  ? formatDuration(metrics.avg_duration_ms)
                  : 'N/A'}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Per procedure run
              </p>
            </div>

            {/* Functions Used */}
            <div className="bg-gradient-to-br from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/20 rounded-xl p-4 border border-amber-100 dark:border-amber-800/30">
              <div className="flex items-center gap-2 mb-2">
                <Zap className="w-4 h-4 text-amber-500" />
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                  Functions Used
                </span>
              </div>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">
                {functionEntries.length}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Distinct functions
              </p>
            </div>
          </div>

          {/* Per-Function Breakdown */}
          <div>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-gray-400" />
              Per-Function Breakdown
            </h3>
            {functionEntries.length === 0 ? (
              <div className="text-center py-8 text-sm text-gray-500 dark:text-gray-400 border border-dashed border-gray-200 dark:border-gray-700 rounded-xl">
                No function-level data available for this period.
              </div>
            ) : (
              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
                {/* Table Header */}
                <div className="bg-gray-50 dark:bg-gray-800/50 border-b border-gray-200 dark:border-gray-700 px-4 py-2.5 grid grid-cols-12 gap-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  <div className="col-span-5">Function</div>
                  <div className="col-span-2 text-right">Calls</div>
                  <div className="col-span-2 text-right">Avg Latency</div>
                  <div className="col-span-2 text-right">Errors</div>
                  <div className="col-span-1 text-right">Rate</div>
                </div>

                {/* Table Body */}
                <div className="divide-y divide-gray-100 dark:divide-gray-800">
                  {functionEntries.map(([name, data]) => {
                    const errorRate =
                      data.calls > 0
                        ? (data.errors / data.calls) * 100
                        : 0
                    return (
                      <div
                        key={name}
                        className="px-4 py-3 grid grid-cols-12 gap-4 items-center hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors"
                      >
                        <div className="col-span-5">
                          <span className="text-sm font-medium text-gray-900 dark:text-white font-mono">
                            {name}
                          </span>
                        </div>
                        <div className="col-span-2 text-right">
                          <span className="text-sm text-gray-700 dark:text-gray-300">
                            {data.calls.toLocaleString()}
                          </span>
                        </div>
                        <div className="col-span-2 text-right">
                          <span className="text-sm font-mono text-gray-700 dark:text-gray-300">
                            {formatDuration(data.avg_ms)}
                          </span>
                        </div>
                        <div className="col-span-2 text-right">
                          {data.errors > 0 ? (
                            <span className="inline-flex items-center gap-1 text-sm text-red-600 dark:text-red-400">
                              <AlertTriangle className="w-3 h-3" />
                              {data.errors}
                            </span>
                          ) : (
                            <span className="text-sm text-gray-400 dark:text-gray-500">
                              0
                            </span>
                          )}
                        </div>
                        <div className="col-span-1 text-right">
                          <span
                            className={`text-xs font-medium ${
                              errorRate === 0
                                ? 'text-emerald-600 dark:text-emerald-400'
                                : errorRate < 10
                                ? 'text-amber-600 dark:text-amber-400'
                                : 'text-red-600 dark:text-red-400'
                            }`}
                          >
                            {errorRate === 0
                              ? '100%'
                              : `${(100 - errorRate).toFixed(0)}%`}
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        </>
      ) : null}
    </div>
  )
}

'use client'

import { useEffect, useState } from 'react'
import { useAuth } from '@/lib/auth-context'
import { jobsApi } from '@/lib/api'
import { Briefcase, Clock, TrendingUp, HardDrive, Activity, CheckCircle } from 'lucide-react'

interface JobStats {
  // Current state
  active_jobs: number
  queued_jobs: number
  concurrency_limit: number

  // Time-based totals
  total_jobs_24h: number
  total_jobs_7d: number
  total_jobs_30d: number

  // Performance metrics
  avg_processing_time_seconds: number
  success_rate_percentage: number

  // Storage
  storage_usage_bytes: number
}

export function JobStatsWidget() {
  const { accessToken, user } = useAuth()
  const [stats, setStats] = useState<JobStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!accessToken || user?.role !== 'org_admin') {
      setLoading(false)
      return
    }

    const loadStats = async () => {
      try {
        setLoading(true)
        setError(null)

        // Get org-wide statistics
        const orgStats = await jobsApi.getOrgStats(accessToken)

        // Transform to expected format
        setStats({
          active_jobs: orgStats.active_jobs || 0,
          queued_jobs: orgStats.queued_jobs || 0,
          concurrency_limit: orgStats.concurrency_limit || 3,
          total_jobs_24h: orgStats.total_jobs || 0, // Backend should provide time-filtered counts
          total_jobs_7d: orgStats.total_jobs || 0,
          total_jobs_30d: orgStats.total_jobs || 0,
          avg_processing_time_seconds: 0, // To be implemented in backend
          success_rate_percentage: 0, // To be calculated from completed/failed
          storage_usage_bytes: 0, // To be implemented in backend
        })
      } catch (err: any) {
        console.error('Failed to load org job stats:', err)
        setError(err.message || 'Failed to load statistics')
      } finally {
        setLoading(false)
      }
    }

    loadStats()

    // Poll every 30 seconds
    const interval = setInterval(loadStats, 30000)

    return () => clearInterval(interval)
  }, [accessToken, user?.role])

  // Only show to org admins
  if (user?.role !== 'org_admin') {
    return null
  }

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-4 bg-gray-200 rounded w-1/4"></div>
          <div className="space-y-3">
            <div className="h-8 bg-gray-200 rounded"></div>
            <div className="h-8 bg-gray-200 rounded"></div>
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <div className="text-red-600 text-sm">
          <p className="font-semibold">Error loading job statistics</p>
          <p className="mt-1">{error}</p>
        </div>
      </div>
    )
  }

  if (!stats) {
    return null
  }

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
  }

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${seconds}s`
    const minutes = Math.floor(seconds / 60)
    if (minutes < 60) return `${minutes}m ${seconds % 60}s`
    const hours = Math.floor(minutes / 60)
    return `${hours}h ${minutes % 60}m`
  }

  return (
    <div className="bg-white rounded-lg shadow">
      <div className="px-6 py-4 border-b border-gray-200">
        <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <Activity className="w-5 h-5 text-blue-600" />
          Organization Job Statistics
        </h3>
        <p className="mt-1 text-sm text-gray-600">
          Overview of job processing across your organization
        </p>
      </div>

      <div className="p-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {/* Active Jobs */}
          <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg p-4 border border-blue-200">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <div className="p-2 bg-blue-600 rounded-lg">
                  <Briefcase className="w-4 h-4 text-white" />
                </div>
                <span className="text-sm font-medium text-blue-900">Active Jobs</span>
              </div>
            </div>
            <div className="flex items-baseline gap-2">
              <div className="text-3xl font-bold text-blue-900">
                {stats.active_jobs}
              </div>
              <div className="text-sm text-blue-700">
                / {stats.concurrency_limit} limit
              </div>
            </div>
            {stats.queued_jobs > 0 && (
              <div className="mt-2 text-sm text-blue-700">
                + {stats.queued_jobs} queued
              </div>
            )}
          </div>

          {/* Jobs Last 24h/7d/30d */}
          <div className="bg-gradient-to-br from-purple-50 to-purple-100 rounded-lg p-4 border border-purple-200">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 bg-purple-600 rounded-lg">
                <TrendingUp className="w-4 h-4 text-white" />
              </div>
              <span className="text-sm font-medium text-purple-900">Total Jobs</span>
            </div>
            <div className="space-y-1">
              <div className="flex justify-between text-sm">
                <span className="text-purple-700">Last 24h:</span>
                <span className="font-semibold text-purple-900">{stats.total_jobs_24h}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-purple-700">Last 7d:</span>
                <span className="font-semibold text-purple-900">{stats.total_jobs_7d}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-purple-700">Last 30d:</span>
                <span className="font-semibold text-purple-900">{stats.total_jobs_30d}</span>
              </div>
            </div>
          </div>

          {/* Average Processing Time */}
          <div className="bg-gradient-to-br from-green-50 to-green-100 rounded-lg p-4 border border-green-200">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 bg-green-600 rounded-lg">
                <Clock className="w-4 h-4 text-white" />
              </div>
              <span className="text-sm font-medium text-green-900">Avg Processing Time</span>
            </div>
            <div className="text-3xl font-bold text-green-900">
              {stats.avg_processing_time_seconds > 0
                ? formatDuration(stats.avg_processing_time_seconds)
                : 'N/A'
              }
            </div>
            <div className="mt-2 text-sm text-green-700">
              Per document
            </div>
          </div>

          {/* Success Rate */}
          <div className="bg-gradient-to-br from-emerald-50 to-emerald-100 rounded-lg p-4 border border-emerald-200">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 bg-emerald-600 rounded-lg">
                <CheckCircle className="w-4 h-4 text-white" />
              </div>
              <span className="text-sm font-medium text-emerald-900">Success Rate</span>
            </div>
            <div className="flex items-baseline gap-1">
              <div className="text-3xl font-bold text-emerald-900">
                {stats.success_rate_percentage > 0
                  ? `${stats.success_rate_percentage.toFixed(1)}`
                  : 'N/A'
                }
              </div>
              {stats.success_rate_percentage > 0 && (
                <div className="text-xl font-semibold text-emerald-700">%</div>
              )}
            </div>
            <div className="mt-2 text-sm text-emerald-700">
              Completed successfully
            </div>
          </div>

          {/* Storage Usage */}
          <div className="bg-gradient-to-br from-orange-50 to-orange-100 rounded-lg p-4 border border-orange-200">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 bg-orange-600 rounded-lg">
                <HardDrive className="w-4 h-4 text-white" />
              </div>
              <span className="text-sm font-medium text-orange-900">Storage Used</span>
            </div>
            <div className="text-3xl font-bold text-orange-900">
              {stats.storage_usage_bytes > 0
                ? formatBytes(stats.storage_usage_bytes)
                : 'N/A'
              }
            </div>
            <div className="mt-2 text-sm text-orange-700">
              By completed jobs
            </div>
          </div>

          {/* Capacity Indicator */}
          <div className="bg-gradient-to-br from-gray-50 to-gray-100 rounded-lg p-4 border border-gray-200">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 bg-gray-600 rounded-lg">
                <Activity className="w-4 h-4 text-white" />
              </div>
              <span className="text-sm font-medium text-gray-900">Capacity</span>
            </div>
            <div className="space-y-2">
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-gray-700">Utilization</span>
                  <span className="font-semibold text-gray-900">
                    {Math.round((stats.active_jobs / stats.concurrency_limit) * 100)}%
                  </span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div
                    className={`h-2 rounded-full transition-all ${
                      stats.active_jobs >= stats.concurrency_limit
                        ? 'bg-red-600'
                        : stats.active_jobs > stats.concurrency_limit * 0.75
                        ? 'bg-yellow-600'
                        : 'bg-green-600'
                    }`}
                    style={{
                      width: `${Math.min((stats.active_jobs / stats.concurrency_limit) * 100, 100)}%`
                    }}
                  />
                </div>
              </div>
              <div className="text-xs text-gray-600">
                {stats.active_jobs >= stats.concurrency_limit
                  ? 'At capacity - jobs will queue'
                  : `${stats.concurrency_limit - stats.active_jobs} slots available`
                }
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

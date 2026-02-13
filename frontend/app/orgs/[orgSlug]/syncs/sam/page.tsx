'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { useOrgUrl } from '@/lib/org-url-context'
import { samApi, connectionsApi, SamDashboardStats, SamNoticeWithSolicitation } from '@/lib/api'
import { formatDate as formatDateUtil } from '@/lib/date-utils'
import { Button } from '@/components/ui/Button'
import SamNavigation from '@/components/sam/SamNavigation'
import SamConnectionRequired from '@/components/sam/SamConnectionRequired'
import { NoticeTypeBadge } from '@/components/sam/SamStatusBadge'
import {
  Building2,
  RefreshCw,
  AlertTriangle,
  FileText,
  TrendingUp,
  Zap,
  BarChart3,
  ArrowRight,
  AlertCircle,
  Plus,
  Clock,
} from 'lucide-react'

export default function SamDashboardPage() {
  const router = useRouter()
  const { token } = useAuth()
  const { orgSlug } = useOrgUrl()

  // Helper for org-scoped URLs
  const orgUrl = (path: string) => `/orgs/${orgSlug}${path}`

  // State
  const [stats, setStats] = useState<SamDashboardStats | null>(null)
  const [recentNotices, setRecentNotices] = useState<SamNoticeWithSolicitation[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [hasConnection, setHasConnection] = useState<boolean | null>(null)

  // Check for SAM.gov connection
  const checkConnection = useCallback(async () => {
    if (!token) return

    try {
      const response = await connectionsApi.listConnections(token)
      const samConnection = response.connections.find(
        (c: { connection_type: string; is_active: boolean }) => c.connection_type === 'sam_gov' && c.is_active
      )
      setHasConnection(!!samConnection)
    } catch {
      // If we can't check connections, assume no connection
      setHasConnection(false)
    }
  }, [token])

  // Load data
  const loadData = useCallback(async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const [dashboardStats, noticesRes] = await Promise.all([
        samApi.getDashboardStats(token),
        samApi.listAllNotices(token, { limit: 10 }),
      ])
      setStats(dashboardStats)
      setRecentNotices(noticesRes.items)
    } catch (err: unknown) {
      const error = err as { message?: string }
      setError(error.message || 'Failed to load dashboard data')
    } finally {
      setIsLoading(false)
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

  // Use formatDate from date-utils for consistent EST display
  const formatDate = (dateStr: string | null) => formatDateUtil(dateStr)

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-6">
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
              <Link href={orgUrl('/syncs/sam/setup')}>
                <Button variant="secondary" className="gap-2">
                  <Plus className="w-4 h-4" />
                  New Search
                </Button>
              </Link>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <SamNavigation />

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
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-blue-500 animate-spin" />
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading dashboard...</p>
          </div>
        ) : (
          <>
            {/* Stats Cards */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
              <StatsCard
                label="Total Notices"
                value={stats?.total_notices || 0}
                icon={FileText}
                color="blue"
              />
              <StatsCard
                label="Total Solicitations"
                value={stats?.total_solicitations || 0}
                icon={Building2}
                color="purple"
              />
              <StatsCard
                label="New This Week"
                value={stats?.new_solicitations_7d || 0}
                icon={TrendingUp}
                color="emerald"
                subLabel="solicitations"
              />
              <StatsCard
                label="Updated This Week"
                value={stats?.updated_solicitations_7d || 0}
                icon={Zap}
                color="amber"
                subLabel="solicitations"
              />
            </div>

            {/* API Usage Widget */}
            {stats?.api_usage && (
              <div className="mb-8 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center text-white">
                      <BarChart3 className="w-4 h-4" />
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
                        API Usage Today
                      </h3>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        Resets at {new Date(stats.api_usage.reset_at).toLocaleTimeString()}
                      </p>
                    </div>
                  </div>
                  <Link
                    href={orgUrl('/syncs/sam/setup')}
                    className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1"
                  >
                    Details
                    <ArrowRight className="w-3 h-3" />
                  </Link>
                </div>

                <div className="flex items-center gap-4">
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs text-gray-500 dark:text-gray-400">
                        {stats.api_usage.total_calls} / {stats.api_usage.daily_limit} calls
                      </span>
                      <span className={`text-xs font-bold ${
                        stats.api_usage.usage_percent > 80
                          ? 'text-red-600 dark:text-red-400'
                          : stats.api_usage.usage_percent > 50
                          ? 'text-amber-600 dark:text-amber-400'
                          : 'text-emerald-600 dark:text-emerald-400'
                      }`}>
                        {stats.api_usage.usage_percent.toFixed(0)}%
                      </span>
                    </div>
                    <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          stats.api_usage.usage_percent > 80
                            ? 'bg-red-500'
                            : stats.api_usage.usage_percent > 50
                            ? 'bg-amber-500'
                            : 'bg-emerald-500'
                        }`}
                        style={{ width: `${Math.min(stats.api_usage.usage_percent, 100)}%` }}
                      />
                    </div>
                  </div>
                  {stats.api_usage.is_over_limit && (
                    <div className="flex items-center gap-1.5 text-red-600 dark:text-red-400">
                      <AlertCircle className="w-4 h-4" />
                      <span className="text-xs font-medium">Limit exceeded</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Recent Notices */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-700">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center text-white">
                    <Clock className="w-4 h-4" />
                  </div>
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
                    Recent Notices
                  </h3>
                </div>
                <Link
                  href={orgUrl('/syncs/sam/notices')}
                  className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1"
                >
                  View All
                  <ArrowRight className="w-3 h-3" />
                </Link>
              </div>

              {recentNotices.length === 0 ? (
                <div className="px-5 py-12 text-center">
                  <FileText className="w-10 h-10 text-gray-300 dark:text-gray-600 mx-auto mb-3" />
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    No notices yet. Create a search to pull opportunities from SAM.gov.
                  </p>
                  <Link href={orgUrl('/syncs/sam/setup')}>
                    <Button variant="secondary" className="mt-4 gap-2">
                      <Plus className="w-4 h-4" />
                      Create Search
                    </Button>
                  </Link>
                </div>
              ) : (
                <div className="divide-y divide-gray-100 dark:divide-gray-700">
                  {recentNotices.map((notice) => (
                    <Link
                      key={notice.id}
                      href={orgUrl(`/syncs/sam/notices/${notice.id}`)}
                      className="flex items-center gap-4 px-5 py-3 hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors"
                    >
                      <NoticeTypeBadge type={notice.notice_type} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                          {notice.title || 'Untitled Notice'}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          {notice.agency_name || 'Unknown Agency'}
                          {notice.solicitation_number && ` - ${notice.solicitation_number}`}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs text-gray-400 dark:text-gray-500">
                          {formatDate(notice.posted_date)}
                        </p>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </div>

            {/* Quick Actions */}
            <div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-4">
              <Link href={orgUrl('/syncs/sam/setup')} className="group">
                <div className="h-full p-5 rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 hover:border-indigo-300 dark:hover:border-indigo-600 hover:bg-indigo-50/50 dark:hover:bg-indigo-900/10 transition-all">
                  <div className="flex items-center gap-3 mb-2">
                    <Plus className="w-5 h-5 text-indigo-500" />
                    <span className="font-medium text-gray-900 dark:text-white">Create Search</span>
                  </div>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    Set up new search criteria to monitor opportunities
                  </p>
                </div>
              </Link>

              <Link href={orgUrl('/syncs/sam/solicitations')} className="group">
                <div className="h-full p-5 rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 hover:border-purple-300 dark:hover:border-purple-600 hover:bg-purple-50/50 dark:hover:bg-purple-900/10 transition-all">
                  <div className="flex items-center gap-3 mb-2">
                    <Building2 className="w-5 h-5 text-purple-500" />
                    <span className="font-medium text-gray-900 dark:text-white">Browse Solicitations</span>
                  </div>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    View all tracked solicitations with AI summaries
                  </p>
                </div>
              </Link>

              <Link href={orgUrl('/syncs/sam/notices')} className="group">
                <div className="h-full p-5 rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 hover:border-cyan-300 dark:hover:border-cyan-600 hover:bg-cyan-50/50 dark:hover:bg-cyan-900/10 transition-all">
                  <div className="flex items-center gap-3 mb-2">
                    <FileText className="w-5 h-5 text-cyan-500" />
                    <span className="font-medium text-gray-900 dark:text-white">View All Notices</span>
                  </div>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    Search and filter all notices including amendments
                  </p>
                </div>
              </Link>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// Stats Card Component
interface StatsCardProps {
  label: string
  value: number
  icon: React.ElementType
  color: 'blue' | 'purple' | 'emerald' | 'amber'
  subLabel?: string
}

const colorClasses = {
  blue: 'from-blue-500 to-indigo-600 shadow-blue-500/25',
  purple: 'from-purple-500 to-indigo-600 shadow-purple-500/25',
  emerald: 'from-emerald-500 to-teal-600 shadow-emerald-500/25',
  amber: 'from-amber-500 to-orange-600 shadow-amber-500/25',
}

function StatsCard({ label, value, icon: Icon, color, subLabel }: StatsCardProps) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{label}</p>
          <p className="text-2xl font-bold text-gray-900 dark:text-white">
            {value.toLocaleString()}
          </p>
          {subLabel && (
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">{subLabel}</p>
          )}
        </div>
        <div className={`w-10 h-10 rounded-lg bg-gradient-to-br ${colorClasses[color]} flex items-center justify-center text-white shadow-lg`}>
          <Icon className="w-5 h-5" />
        </div>
      </div>
    </div>
  )
}

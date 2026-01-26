'use client'

import { Briefcase, TrendingUp, CheckCircle, XCircle, Clock, Users } from 'lucide-react'

interface UserStats {
  active_jobs: number
  total_jobs_24h: number
  total_jobs_7d: number
  completed_jobs_24h: number
  failed_jobs_24h: number
}

interface OrgStats {
  organization_id: string
  active_jobs: number
  queued_jobs: number
  concurrency_limit: number
  total_jobs: number
  completed_jobs: number
  failed_jobs: number
  cancelled_jobs: number
  total_documents_processed: number
}

interface JobStatsCardProps {
  userStats: UserStats | null
  orgStats: OrgStats | null
  isAdmin: boolean
  isLoading: boolean
}

export function JobStatsCard({ userStats, orgStats, isAdmin, isLoading }: JobStatsCardProps) {
  const successRate = userStats
    ? userStats.total_jobs_24h > 0
      ? Math.round((userStats.completed_jobs_24h / userStats.total_jobs_24h) * 100)
      : 100
    : 0

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden hover:shadow-lg hover:shadow-gray-200/50 dark:hover:shadow-gray-900/50 transition-all duration-200">
      {/* Status bar at top */}
      <div className="h-1 bg-gradient-to-r from-violet-500 to-purple-600" />

      <div className="p-5">
        {/* Header */}
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center text-white shadow-lg shadow-violet-500/25">
            <Briefcase className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">Job Statistics</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">Your processing activity</p>
          </div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="w-6 h-6 rounded-full border-2 border-gray-200 dark:border-gray-700 border-t-violet-500 animate-spin" />
          </div>
        ) : (
          <>
            {/* Main Stats */}
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div className="text-center p-3 bg-gray-50 dark:bg-gray-900/50 rounded-xl">
                <div className="flex items-center justify-center gap-1 mb-1">
                  <Clock className="w-4 h-4 text-blue-500" />
                </div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {userStats?.active_jobs ?? 0}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Active</p>
              </div>
              <div className="text-center p-3 bg-gray-50 dark:bg-gray-900/50 rounded-xl">
                <div className="flex items-center justify-center gap-1 mb-1">
                  <TrendingUp className="w-4 h-4 text-emerald-500" />
                </div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {successRate}%
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Success Rate</p>
              </div>
            </div>

            {/* Detailed Stats */}
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-gray-500 dark:text-gray-400">Last 24h</span>
                <span className="font-medium text-gray-900 dark:text-white">
                  {userStats?.total_jobs_24h ?? 0} jobs
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-500 dark:text-gray-400">Last 7 days</span>
                <span className="font-medium text-gray-900 dark:text-white">
                  {userStats?.total_jobs_7d ?? 0} jobs
                </span>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-gray-500 dark:text-gray-400">
                  <CheckCircle className="w-3.5 h-3.5 text-emerald-500" />
                  <span>Completed (24h)</span>
                </div>
                <span className="font-medium text-emerald-600 dark:text-emerald-400">
                  {userStats?.completed_jobs_24h ?? 0}
                </span>
              </div>
              {(userStats?.failed_jobs_24h ?? 0) > 0 && (
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-gray-500 dark:text-gray-400">
                    <XCircle className="w-3.5 h-3.5 text-red-500" />
                    <span>Failed (24h)</span>
                  </div>
                  <span className="font-medium text-red-600 dark:text-red-400">
                    {userStats?.failed_jobs_24h ?? 0}
                  </span>
                </div>
              )}
            </div>

            {/* Admin: Org Stats */}
            {isAdmin && orgStats && (
              <div className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-700">
                <div className="flex items-center gap-2 mb-3">
                  <Users className="w-4 h-4 text-gray-400" />
                  <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Organization
                  </p>
                </div>
                <div className="space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500 dark:text-gray-400">Concurrency</span>
                    <span className="font-mono text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/50 px-2 py-0.5 rounded">
                      {orgStats.active_jobs} / {orgStats.concurrency_limit}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500 dark:text-gray-400">Total Jobs</span>
                    <span className="font-medium text-gray-900 dark:text-white">
                      {orgStats.total_jobs}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500 dark:text-gray-400">Documents Processed</span>
                    <span className="font-medium text-gray-900 dark:text-white">
                      {orgStats.total_documents_processed}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

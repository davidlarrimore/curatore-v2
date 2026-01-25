'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { jobsApi } from '@/lib/api'

interface JobStats {
  active_jobs: number
  total_jobs_24h: number
  total_jobs_7d: number
  completed_jobs_24h: number
  failed_jobs_24h: number
}

interface OrgStats {
  active_jobs: number
  queued_jobs: number
  concurrency_limit: number
  total_jobs: number
}

export default function JobStatusBar() {
  const router = useRouter()
  const { user, accessToken, isAuthenticated } = useAuth()

  const [userStats, setUserStats] = useState<JobStats | null>(null)
  const [orgStats, setOrgStats] = useState<OrgStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!accessToken || !isAuthenticated) {
      setLoading(false)
      return
    }

    const loadStats = async () => {
      try {
        // Load user stats
        const stats = await jobsApi.getUserStats(accessToken)
        setUserStats(stats)

        // Load org stats if user is admin
        if (user?.role === 'org_admin') {
          try {
            const orgData = await jobsApi.getOrgStats(accessToken)
            setOrgStats(orgData)
          } catch (err) {
            // Not admin or error loading org stats
            console.debug('Could not load org stats:', err)
          }
        }
      } catch (err) {
        console.error('Failed to load job stats:', err)
      } finally {
        setLoading(false)
      }
    }

    loadStats()

    // Poll for updates every 10 seconds
    const interval = setInterval(loadStats, 10000)

    return () => clearInterval(interval)
  }, [accessToken, isAuthenticated, user?.role])

  // Don't show if not authenticated or loading
  if (!isAuthenticated || loading || !userStats) {
    return null
  }

  // Don't show if no jobs in the last 7 days
  if (userStats.total_jobs_7d === 0) {
    return null
  }

  const hasActiveJobs = userStats.active_jobs > 0

  return (
    <div
      onClick={() => router.push('/jobs')}
      className={`fixed bottom-4 right-4 bg-white rounded-lg shadow-lg border-2 cursor-pointer transition-all hover:shadow-xl ${
        hasActiveJobs ? 'border-blue-500' : 'border-gray-300'
      }`}
    >
      <div className="p-4">
        <div className="flex items-center space-x-4">
          {/* User Stats */}
          <div className="flex items-center space-x-2">
            <div className={`w-3 h-3 rounded-full ${hasActiveJobs ? 'bg-blue-500 animate-pulse' : 'bg-gray-400'}`}></div>
            <div>
              <div className="text-xs text-gray-600">Your Jobs</div>
              <div className="text-sm font-semibold text-gray-900">
                {userStats.active_jobs} active
                {userStats.total_jobs_24h > 0 && ` / ${userStats.total_jobs_24h} today`}
              </div>
            </div>
          </div>

          {/* Org Stats (Admin Only) */}
          {orgStats && user?.role === 'org_admin' && (
            <>
              <div className="border-l border-gray-300 h-10"></div>
              <div>
                <div className="text-xs text-gray-600">Organization</div>
                <div className="text-sm font-semibold text-gray-900">
                  {orgStats.active_jobs}/{orgStats.concurrency_limit} active
                </div>
              </div>
            </>
          )}

          {/* Arrow Icon */}
          <div className="text-gray-400">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </div>
        </div>
      </div>
    </div>
  )
}

'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { systemApi, jobsApi, objectStorageApi } from '@/lib/api'
import {
  SystemHealthCard,
  JobStatsCard,
  StorageOverviewCard,
  QuickActionsCard,
  RecentActivityCard,
} from '@/components/dashboard'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import { LayoutDashboard, RefreshCw, Loader2 } from 'lucide-react'

interface HealthData {
  timestamp: string
  overall_status: 'healthy' | 'unhealthy' | 'degraded'
  components: Record<string, any>
  issues?: string[]
}

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

interface StorageHealth {
  status: string
  enabled: boolean
  provider_connected: boolean | null
  buckets: string[] | null
  error: string | null
}

interface Job {
  id: string
  name: string
  status: string
  total_documents: number
  completed_documents: number
  failed_documents: number
  created_at: string
  started_at?: string
  completed_at?: string
}

export default function DashboardPage() {
  return (
    <ProtectedRoute>
      <DashboardContent />
    </ProtectedRoute>
  )
}

function DashboardContent() {
  const router = useRouter()
  const { user, token, isAuthenticated } = useAuth()
  const isAdmin = user?.role === 'org_admin'

  // Data states
  const [healthData, setHealthData] = useState<HealthData | null>(null)
  const [userStats, setUserStats] = useState<UserStats | null>(null)
  const [orgStats, setOrgStats] = useState<OrgStats | null>(null)
  const [storageHealth, setStorageHealth] = useState<StorageHealth | null>(null)
  const [recentJobs, setRecentJobs] = useState<Job[]>([])

  // Loading states
  const [isLoadingHealth, setIsLoadingHealth] = useState(true)
  const [isLoadingStats, setIsLoadingStats] = useState(true)
  const [isLoadingStorage, setIsLoadingStorage] = useState(true)
  const [isLoadingJobs, setIsLoadingJobs] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)

  // Fetch health data
  const fetchHealthData = useCallback(async () => {
    try {
      const health = await systemApi.getComprehensiveHealth()
      setHealthData(health)
    } catch (error) {
      console.error('Failed to fetch health data:', error)
    }
  }, [])

  // Fetch job stats
  const fetchJobStats = useCallback(async () => {
    if (!token) return

    try {
      const [userStatsData, recentJobsData] = await Promise.all([
        jobsApi.getUserStats(token),
        jobsApi.listJobs(token, { page_size: 5 }),
      ])
      setUserStats(userStatsData)
      setRecentJobs(recentJobsData.jobs)

      if (isAdmin) {
        try {
          const orgStatsData = await jobsApi.getOrgStats(token)
          setOrgStats(orgStatsData)
        } catch (error) {
          console.error('Failed to fetch org stats:', error)
        }
      }
    } catch (error) {
      console.error('Failed to fetch job stats:', error)
    }
  }, [token, isAdmin])

  // Fetch storage health
  const fetchStorageHealth = useCallback(async () => {
    try {
      const health = await objectStorageApi.getHealth()
      setStorageHealth(health)
    } catch (error) {
      console.error('Failed to fetch storage health:', error)
    }
  }, [])

  // Initial load
  useEffect(() => {
    const loadAll = async () => {
      setIsLoadingHealth(true)
      setIsLoadingStats(true)
      setIsLoadingStorage(true)
      setIsLoadingJobs(true)

      await Promise.all([
        fetchHealthData().finally(() => setIsLoadingHealth(false)),
        fetchJobStats().finally(() => {
          setIsLoadingStats(false)
          setIsLoadingJobs(false)
        }),
        fetchStorageHealth().finally(() => setIsLoadingStorage(false)),
      ])
    }

    if (isAuthenticated && token) {
      loadAll()
    }
  }, [isAuthenticated, token, fetchHealthData, fetchJobStats, fetchStorageHealth])

  // Refresh all data
  const handleRefreshAll = async () => {
    setIsRefreshing(true)
    await Promise.all([
      fetchHealthData(),
      fetchJobStats(),
      fetchStorageHealth(),
    ])
    setIsRefreshing(false)
  }

  // Calculate overall stats for the stats bar
  const healthyCount = healthData?.components
    ? Object.values(healthData.components).filter((c: any) => c?.status === 'healthy').length
    : 0
  const totalComponents = healthData?.components
    ? Object.keys(healthData.components).length
    : 0
  const successRate = userStats
    ? userStats.total_jobs_24h > 0
      ? Math.round((userStats.completed_jobs_24h / userStats.total_jobs_24h) * 100)
      : 100
    : 0

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25">
                <LayoutDashboard className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  Dashboard
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  Welcome back{user?.full_name ? `, ${user.full_name}` : ''}
                </p>
              </div>
            </div>
            <button
              onClick={handleRefreshAll}
              disabled={isRefreshing}
              className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors shadow-sm"
            >
              <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">Refresh</span>
            </button>
          </div>

          {/* Stats Bar */}
          {!isLoadingHealth && !isLoadingStats && (
            <div className="mt-6 flex flex-wrap items-center gap-4 text-sm">
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300">
                <span className="font-medium">{userStats?.active_jobs ?? 0}</span>
                <span>active jobs</span>
              </div>
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400">
                <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                <span className="font-medium">{healthyCount}</span>
                <span>healthy</span>
              </div>
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-violet-50 dark:bg-violet-900/20 text-violet-700 dark:text-violet-400">
                <span className="font-medium">{successRate}%</span>
                <span>success rate</span>
              </div>
            </div>
          )}
        </div>

        {/* Main Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
          {/* Quick Actions - Full width on small, 1 col on large */}
          <div className="lg:col-span-2 xl:col-span-1">
            <QuickActionsCard isAdmin={isAdmin} />
          </div>

          {/* System Health */}
          <div>
            <SystemHealthCard
              healthData={healthData}
              isLoading={isLoadingHealth}
              onRefresh={fetchHealthData}
            />
          </div>

          {/* Job Statistics */}
          <div>
            <JobStatsCard
              userStats={userStats}
              orgStats={orgStats}
              isAdmin={isAdmin}
              isLoading={isLoadingStats}
            />
          </div>

          {/* Storage Overview */}
          <div>
            <StorageOverviewCard
              storageHealth={storageHealth}
              isLoading={isLoadingStorage}
            />
          </div>

          {/* Recent Activity - Takes 2 columns on xl */}
          <div className="lg:col-span-2">
            <RecentActivityCard
              recentJobs={recentJobs}
              isLoading={isLoadingJobs}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

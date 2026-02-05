// components/layout/StatusBar.tsx
'use client'

import { useState, useEffect, useRef, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { Activity, Clock, ChevronRight, CheckCircle, XCircle, Layers, Play, AlertCircle } from 'lucide-react'
import { API_PATH_VERSION } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import { useQueue } from '@/lib/context-shims'
import { useUnifiedJobs } from '@/lib/unified-jobs-context'
import { formatCurrentTime, DISPLAY_TIMEZONE_ABBR } from '@/lib/date-utils'
import { ConnectionStatusIndicator } from '@/components/ui/ConnectionStatusIndicator'
import clsx from 'clsx'

interface SystemStatus {
  health: string
  llmConnected: boolean
  isLoading: boolean
  supportedFormats: string[]
  maxFileSize: number
  backendVersion?: string
}

interface StatusBarProps {
  systemStatus: SystemStatus
  sidebarCollapsed: boolean
}

export function StatusBar({ systemStatus, sidebarCollapsed }: StatusBarProps) {
  const router = useRouter()
  const { isAuthenticated } = useAuth()
  // Use both legacy and unified context during migration
  const { stats: legacyStats, activeCount: legacyActiveCount } = useQueue()
  const { queueStats, activeCount: unifiedActiveCount, connectionStatus, hasActiveJobs, jobs } = useUnifiedJobs()

  // Prefer unified context stats, fall back to legacy
  const stats = queueStats || legacyStats
  const activeCount = unifiedActiveCount || legacyActiveCount

  const rootRef = useRef<HTMLDivElement | null>(null)
  const [currentTime, setCurrentTime] = useState<Date | null>(null)
  const [isClient, setIsClient] = useState(false)

  // Track previous values for animations
  const prevActiveCount = useRef(activeCount)
  const [activeCountChanged, setActiveCountChanged] = useState(false)

  // Calculate job counts
  const jobCounts = useMemo(() => {
    const queued = stats ? (
      stats.celery_queues.extraction +
      stats.celery_queues.sam +
      stats.celery_queues.scrape +
      stats.celery_queues.sharepoint +
      stats.celery_queues.maintenance +
      stats.celery_queues.processing_priority
    ) : 0

    const pending = stats?.extraction_queue.pending || 0
    const submitted = stats?.extraction_queue.submitted || 0
    const running = Math.max(
      (stats?.extraction_queue.running || 0) + (stats?.workers.tasks_running || 0),
      jobs.length // Include tracked jobs
    )

    return { queued, pending, submitted, running }
  }, [stats, jobs.length])

  // Calculate recent stats (5 min)
  const recentStats = useMemo(() => {
    const completed = stats?.recent_5m?.completed || 0
    const failed = stats?.recent_5m?.failed || 0
    const timedOut = stats?.recent_5m?.timed_out || 0
    const total = completed + failed + timedOut
    const failureRate = total > 0 ? (failed + timedOut) / total : 0

    // Determine health status
    let health: 'good' | 'warning' | 'error' = 'good'
    if (failureRate >= 0.2) health = 'error'
    else if (failureRate > 0) health = 'warning'

    return { completed, failed, timedOut, total, failureRate, health }
  }, [stats])

  // Animate on active count change
  useEffect(() => {
    if (activeCount !== prevActiveCount.current) {
      setActiveCountChanged(true)
      const timer = setTimeout(() => setActiveCountChanged(false), 1000)
      prevActiveCount.current = activeCount
      return () => clearTimeout(timer)
    }
  }, [activeCount])

  // Fix hydration issue by only showing time after client-side hydration
  useEffect(() => {
    setIsClient(true)
    setCurrentTime(new Date())

    const timer = setInterval(() => {
      setCurrentTime(new Date())
    }, 1000)

    return () => clearInterval(timer)
  }, [])

  // formatTime is now handled by formatCurrentTime from date-utils

  const getUptimeDisplay = () => {
    if (!isClient) return '0h 0m'
    const uptime = Math.floor(Date.now() / 1000) % 86400
    const hours = Math.floor(uptime / 3600)
    const minutes = Math.floor((uptime % 3600) / 60)
    return `${hours}h ${minutes}m`
  }

  // Measure and expose status bar height as a CSS variable
  useEffect(() => {
    const el = rootRef.current
    if (!el) return
    const setVar = () => {
      const rect = el.getBoundingClientRect()
      const height = Math.ceil(rect.height)
      const offset = Math.ceil(window.innerHeight - rect.top)
      const cs = window.getComputedStyle(el)
      const borderTop = Math.ceil(parseFloat(cs.borderTopWidth || '0') || 0)
      const safeOffset = offset + borderTop + 2
      document.documentElement.style.setProperty('--statusbar-height', `${height}px`)
      document.documentElement.style.setProperty('--statusbar-offset', `${offset}px`)
      document.documentElement.style.setProperty('--statusbar-safe-offset', `${safeOffset}px`)
    }
    setVar()
    const onResize = () => setVar()
    window.addEventListener('resize', onResize)
    const interval = setInterval(setVar, 1000)
    return () => {
      window.removeEventListener('resize', onResize)
      clearInterval(interval)
    }
  }, [])

  return (
    <div
      ref={rootRef}
      className={clsx(
        "bg-white dark:bg-gray-900 border-t border-gray-200 dark:border-gray-800 px-4 lg:px-6 py-2 flex items-center justify-between transition-all duration-300 z-60 relative",
        sidebarCollapsed ? 'lg:ml-16' : 'lg:ml-64'
      )}
    >
      {/* Left section */}
      <div className="flex items-center gap-4">
        {/* API Status - Links to Infrastructure settings */}
        <button
          onClick={() => router.push('/settings-admin?tab=infrastructure')}
          className={clsx(
            "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
            systemStatus.health === 'healthy'
              ? "bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-100 dark:hover:bg-emerald-900/30"
              : "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/30"
          )}
          title="View infrastructure status"
        >
          <span className={clsx(
            "w-2 h-2 rounded-full",
            systemStatus.health === 'healthy' ? 'bg-emerald-500' : 'bg-red-500',
            systemStatus.isLoading && 'animate-pulse'
          )} />
          <span className="hidden sm:inline">
            {systemStatus.health === 'healthy' ? 'Healthy' : 'Unhealthy'}
          </span>
          <Activity className={clsx("w-3.5 h-3.5", systemStatus.isLoading && 'animate-spin')} />
        </button>

        {/* Connection Status Indicator */}
        <ConnectionStatusIndicator status={connectionStatus} variant="compact" />

        {/* Divider */}
        <div className="hidden lg:block w-px h-4 bg-gray-200 dark:bg-gray-700"></div>

        {/* Jobs Status - Links to Queue Admin */}
        <button
          onClick={() => router.push('/admin/queue')}
          className={clsx(
            "hidden lg:flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all group",
            "hover:bg-gray-100 dark:hover:bg-gray-800",
            activeCountChanged && "ring-2 ring-indigo-400 ring-opacity-50"
          )}
          title="View job queue"
        >
          {/* Active jobs indicator */}
          {jobCounts.running > 0 && (
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-indigo-100 dark:bg-indigo-900/30">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
              </span>
              <span className="font-mono text-xs font-medium text-indigo-700 dark:text-indigo-300">
                {jobCounts.running}
              </span>
              <Play className="w-3 h-3 text-indigo-600 dark:text-indigo-400" />
            </div>
          )}

          {/* Queued jobs indicator */}
          {jobCounts.queued > 0 && (
            <div className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-100 dark:bg-amber-900/30">
              <span className="font-mono text-xs font-medium text-amber-700 dark:text-amber-300">
                {jobCounts.queued}
              </span>
              <Layers className="w-3 h-3 text-amber-600 dark:text-amber-400" />
            </div>
          )}

          {/* Pending jobs indicator */}
          {jobCounts.pending > 0 && (
            <div className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-gray-100 dark:bg-gray-700">
              <span className="font-mono text-xs font-medium text-gray-600 dark:text-gray-300">
                {jobCounts.pending}
              </span>
              <Clock className="w-3 h-3 text-gray-500 dark:text-gray-400" />
            </div>
          )}

          {/* Divider when there's activity */}
          {(jobCounts.running > 0 || jobCounts.queued > 0 || jobCounts.pending > 0) && recentStats.total > 0 && (
            <div className="w-px h-4 bg-gray-200 dark:bg-gray-700"></div>
          )}

          {/* Recent completions (5 min) with health indicator */}
          {recentStats.total > 0 ? (
            <div className={clsx(
              "flex items-center gap-1 px-2 py-0.5 rounded-md",
              recentStats.health === 'good' && "bg-emerald-100 dark:bg-emerald-900/30",
              recentStats.health === 'warning' && "bg-amber-100 dark:bg-amber-900/30",
              recentStats.health === 'error' && "bg-red-100 dark:bg-red-900/30",
            )}>
              <span className={clsx(
                "font-mono text-xs font-medium",
                recentStats.health === 'good' && "text-emerald-700 dark:text-emerald-300",
                recentStats.health === 'warning' && "text-amber-700 dark:text-amber-300",
                recentStats.health === 'error' && "text-red-700 dark:text-red-300",
              )}>
                {recentStats.completed}
              </span>
              {recentStats.health === 'good' ? (
                <CheckCircle className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
              ) : recentStats.health === 'warning' ? (
                <AlertCircle className="w-3 h-3 text-amber-600 dark:text-amber-400" />
              ) : (
                <XCircle className="w-3 h-3 text-red-600 dark:text-red-400" />
              )}
              {(recentStats.failed + recentStats.timedOut) > 0 && (
                <span className={clsx(
                  "font-mono text-xs",
                  recentStats.health === 'warning' && "text-amber-600 dark:text-amber-400",
                  recentStats.health === 'error' && "text-red-600 dark:text-red-400",
                )}>
                  /{recentStats.failed + recentStats.timedOut}
                </span>
              )}
            </div>
          ) : (jobCounts.running === 0 && jobCounts.queued === 0 && jobCounts.pending === 0) && (
            <span className="text-xs text-gray-400 dark:text-gray-500">No activity</span>
          )}

          <ChevronRight className="w-3.5 h-3.5 text-gray-400 group-hover:text-gray-600 dark:group-hover:text-gray-300 transition-colors" />
        </button>
      </div>

      {/* Right section */}
      <div className="flex items-center gap-4 text-xs">
        {/* Uptime */}
        <div className="hidden md:flex items-center gap-1.5 text-gray-500 dark:text-gray-400">
          <Activity className="w-3 h-3" />
          <span className="font-mono">{getUptimeDisplay()}</span>
        </div>

        {/* Divider */}
        <div className="hidden md:block w-px h-4 bg-gray-200 dark:bg-gray-700"></div>

        {/* Time */}
        <div className="flex items-center gap-1.5 text-gray-600 dark:text-gray-300">
          <Clock className="w-3 h-3 text-gray-400 dark:text-gray-500" />
          <span className="font-mono font-medium">
            {isClient && currentTime ? formatCurrentTime() : '--:--:--'}
          </span>
          <span className="text-xs text-gray-400 dark:text-gray-500">{DISPLAY_TIMEZONE_ABBR}</span>
        </div>

        {/* Divider */}
        <div className="hidden sm:block w-px h-4 bg-gray-200 dark:bg-gray-700"></div>

        {/* Version info */}
        <div className="hidden sm:flex items-center gap-3 text-gray-400 dark:text-gray-500">
          <div className="flex items-center gap-1">
            <span>Backend</span>
            <span className="font-mono text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">
              {systemStatus.backendVersion || '?'}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <span>API</span>
            <span className="font-mono text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">
              {API_PATH_VERSION.toUpperCase()}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

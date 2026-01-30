// components/layout/StatusBar.tsx
'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { Activity, Clock, ChevronRight, CheckCircle, XCircle, Loader2 } from 'lucide-react'
import { API_PATH_VERSION, runsApi } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import { formatCurrentTime, DISPLAY_TIMEZONE_ABBR } from '@/lib/date-utils'
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
  const { accessToken, isAuthenticated } = useAuth()
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [currentTime, setCurrentTime] = useState<Date | null>(null)
  const [activeRuns, setActiveRuns] = useState(0)
  const [totalRuns24h, setTotalRuns24h] = useState(0)
  const [completedRuns24h, setCompletedRuns24h] = useState(0)
  const [failedRuns24h, setFailedRuns24h] = useState(0)
  const [isClient, setIsClient] = useState(false)

  // Fix hydration issue by only showing time after client-side hydration
  useEffect(() => {
    setIsClient(true)
    setCurrentTime(new Date())

    const timer = setInterval(() => {
      setCurrentTime(new Date())
    }, 1000)

    return () => clearInterval(timer)
  }, [])

  // Poll run stats from the authenticated runs API
  useEffect(() => {
    if (!accessToken || !isAuthenticated) return

    let mounted = true
    const poll = async () => {
      try {
        const stats = await runsApi.getStats(accessToken)
        if (!mounted) return

        // Calculate active runs (pending + running)
        const runningCount = stats.runs.by_status['running'] || 0
        const pendingCount = stats.runs.by_status['pending'] || 0
        setActiveRuns(runningCount + pendingCount)

        // Get 24h stats
        setTotalRuns24h(stats.recent_24h.total || 0)
        setCompletedRuns24h(stats.recent_24h.by_status['completed'] || 0)
        setFailedRuns24h(stats.recent_24h.by_status['failed'] || 0)
      } catch {
        // ignore transient errors
      }
    }
    poll()
    const interval = setInterval(poll, Number(process.env.NEXT_PUBLIC_JOB_POLL_INTERVAL_MS || 10000))
    return () => { mounted = false; clearInterval(interval) }
  }, [accessToken, isAuthenticated])

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
        {/* API Status */}
        <div className={clsx(
          "flex items-center gap-2 px-3 py-1 rounded-lg text-xs font-medium transition-colors",
          systemStatus.health === 'healthy'
            ? "bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400"
            : "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400"
        )}>
          <span className={clsx(
            "w-1.5 h-1.5 rounded-full",
            systemStatus.health === 'healthy' ? 'bg-emerald-500' : 'bg-red-500'
          )} />
          <span className="hidden sm:inline">API</span>
          <span>{systemStatus.health === 'healthy' ? 'Healthy' : 'Error'}</span>
        </div>

        {/* Divider */}
        <div className="hidden lg:block w-px h-4 bg-gray-200 dark:bg-gray-700"></div>

        {/* Processing Button */}
        <button
          onClick={() => router.push('/settings-admin?tab=processing')}
          className={clsx(
            "hidden lg:flex items-center gap-3 px-3 py-1.5 rounded-lg transition-all group",
            activeRuns > 0
              ? "bg-indigo-50 dark:bg-indigo-900/20 hover:bg-indigo-100 dark:hover:bg-indigo-900/30"
              : "hover:bg-gray-100 dark:hover:bg-gray-800"
          )}
        >
          <div className="flex items-center gap-2">
            <Activity className={clsx(
              "w-4 h-4",
              activeRuns > 0 ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-500 dark:text-gray-400'
            )} />
            <span className={clsx(
              "text-xs font-medium",
              activeRuns > 0 ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-700 dark:text-gray-300'
            )}>
              Processing
            </span>
          </div>

          {/* Run stats */}
          <div className="flex items-center gap-2 text-xs">
            {activeRuns > 0 ? (
              <div className="flex items-center gap-1.5 text-indigo-600 dark:text-indigo-400">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
                </span>
                <span className="font-mono font-medium">{activeRuns}</span>
                <span className="text-indigo-500 dark:text-indigo-400">active</span>
              </div>
            ) : totalRuns24h > 0 ? (
              <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
                <div className="flex items-center gap-1">
                  <CheckCircle className="w-3 h-3 text-emerald-500" />
                  <span className="font-mono text-emerald-600 dark:text-emerald-400">{completedRuns24h}</span>
                </div>
                {failedRuns24h > 0 && (
                  <>
                    <span className="text-gray-300 dark:text-gray-600">|</span>
                    <div className="flex items-center gap-1">
                      <XCircle className="w-3 h-3 text-red-500" />
                      <span className="font-mono text-red-600 dark:text-red-400">{failedRuns24h}</span>
                    </div>
                  </>
                )}
                <span className="text-gray-400">today</span>
              </div>
            ) : (
              <span className="text-gray-400 dark:text-gray-500">No recent activity</span>
            )}
          </div>

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

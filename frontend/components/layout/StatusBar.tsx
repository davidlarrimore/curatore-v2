// components/layout/StatusBar.tsx
'use client'

import { useState, useEffect, useRef } from 'react'
import { Activity, Zap, HardDrive, Clock, Server, Wifi } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { utils, API_PATH_VERSION, systemApi } from '@/lib/api'

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
  sidebarCollapsed: boolean // NEW: Track sidebar state
}

export function StatusBar({ systemStatus, sidebarCollapsed }: StatusBarProps) {
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [currentTime, setCurrentTime] = useState<Date | null>(null)
  const [connectionCount, setConnectionCount] = useState(0)
  const [runningCount, setRunningCount] = useState(0)
  const [processedCount, setProcessedCount] = useState(0)
  const [totalCount, setTotalCount] = useState(0)
  const [isClient, setIsClient] = useState(false)

  // Fix hydration issue by only showing time after client-side hydration
  useEffect(() => {
    setIsClient(true)
    setCurrentTime(new Date())
    
    // Update time every second only after hydration
    const timer = setInterval(() => {
      setCurrentTime(new Date())
    }, 1000)

    return () => clearInterval(timer)
  }, [])

  // Poll queue health to display number of jobs in the queue
  useEffect(() => {
    let mounted = true
    const poll = async () => {
      try {
        // Try to read active job group from localStorage and fetch group summary
        let usedGroup = false;
        try {
          const raw = localStorage.getItem('curatore:active_jobs');
          if (raw) {
            const g = JSON.parse(raw);
            if (g && Array.isArray(g.job_ids) && g.job_ids.length > 0) {
              const s = await systemApi.getQueueSummaryByJobs(g.job_ids);
              if (!mounted) return;
              setConnectionCount(s.queued ?? 0);
              setRunningCount(s.running ?? 0);
              setProcessedCount(s.done ?? 0);
              setTotalCount(s.total ?? 0);
              usedGroup = true;
            } else if (g && g.batch_id) {
              const s = await systemApi.getQueueSummaryByBatch(g.batch_id);
              if (!mounted) return;
              setConnectionCount(s.queued ?? 0);
              setRunningCount(s.running ?? 0);
              setProcessedCount(s.done ?? 0);
              setTotalCount(s.total ?? 0);
              usedGroup = true;
            }
          }
        } catch {}
        if (!usedGroup) {
          const q = await systemApi.getQueueHealth();
          if (!mounted) return;
          setConnectionCount(q?.pending ?? 0);
          setRunningCount(q?.running ?? 0);
          setProcessedCount(q?.processed ?? 0);
          setTotalCount(q?.total ?? 0);
        }
      } catch {
        // ignore transient errors
      }
    }
    poll()
    const interval = setInterval(poll, Number(process.env.NEXT_PUBLIC_JOB_POLL_INTERVAL_MS || 5000))
    return () => { mounted = false; clearInterval(interval) }
  }, [])

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString([], { 
      hour: '2-digit', 
      minute: '2-digit',
      second: '2-digit'
    })
  }

  const getUptimeDisplay = () => {
    // In a real app, you'd track actual uptime
    if (!isClient) return '0h 0m' // Prevent hydration mismatch
    
    const uptime = Math.floor(Date.now() / 1000) % 86400 // Simulated daily reset
    const hours = Math.floor(uptime / 3600)
    const minutes = Math.floor((uptime % 3600) / 60)
    return `${hours}h ${minutes}m`
  }

  // Measure and expose status bar height as a CSS variable for precise panel positioning
  useEffect(() => {
    const el = rootRef.current
    if (!el) return
    const setVar = () => {
      const rect = el.getBoundingClientRect()
      const height = Math.ceil(rect.height)
      const offset = Math.ceil(window.innerHeight - rect.top)
      const cs = window.getComputedStyle(el)
      const borderTop = Math.ceil(parseFloat(cs.borderTopWidth || '0') || 0)
      const safeOffset = offset + borderTop + 2 // extra 2px buffer for sub-pixel rounding/shadow
      document.documentElement.style.setProperty('--statusbar-height', `${height}px`)
      document.documentElement.style.setProperty('--statusbar-offset', `${offset}px`)
      document.documentElement.style.setProperty('--statusbar-safe-offset', `${safeOffset}px`)
    }
    setVar()
    const onResize = () => setVar()
    window.addEventListener('resize', onResize)
    // Light polling in case dynamic content changes height without resize
    const interval = setInterval(setVar, 1000)
    return () => {
      window.removeEventListener('resize', onResize)
      clearInterval(interval)
    }
  }, [])

  return (
    <div ref={rootRef} className={`bg-gray-50 border-t border-gray-200 px-4 py-2 flex items-center justify-between text-xs text-gray-600 transition-all duration-300 z-60 relative ${
      // Adjust margin based on sidebar state - only on desktop
      `lg:ml-${sidebarCollapsed ? '16' : '64'}`
    }`}>
      <div className="flex items-center space-x-6">
        {/* API Health Status */}
        <div className="flex items-center space-x-1">
          <Activity className="w-3 h-3" />
          <span>API:</span>
          <Badge 
            variant={systemStatus.health === 'healthy' ? 'success' : 'error'} 
            className="text-xs py-0 px-1"
          >
            {systemStatus.health}
          </Badge>
        </div>
        
        {/* LLM Connection Status */}
        <div className="flex items-center space-x-1">
          <Zap className="w-3 h-3" />
          <span>LLM:</span>
          <Badge 
            variant={systemStatus.llmConnected ? 'success' : 'error'} 
            className="text-xs py-0 px-1"
          >
            {systemStatus.llmConnected ? 'Connected' : 'Disconnected'}
          </Badge>
        </div>

        {/* Storage Info */}
        <div className="flex items-center space-x-1">
          <HardDrive className="w-3 h-3" />
          <span>Max Upload:</span>
          <span className="font-mono">{utils.formatFileSize(systemStatus.maxFileSize)}</span>
        </div>

        {/* Supported Formats */}
        <div className="hidden md:flex items-center space-x-1">
          <Server className="w-3 h-3" />
          <span>Formats:</span>
          <span className="font-mono">{systemStatus.supportedFormats.length} types</span>
        </div>

        {/* Active Jobs in Queue */}
        <div className="hidden lg:flex items-center space-x-1">
          <Wifi className="w-3 h-3" />
          <span>Job Queue:</span>
          <span className="font-mono">{connectionCount}</span>
          <span className="mx-1">•</span>
          <span>Running:</span>
          <span className="font-mono">{runningCount}</span>
          <span className="mx-1">•</span>
          <span>Done:</span>
          <span className="font-mono">{processedCount}/{totalCount}</span>
        </div>
      </div>

      <div className="flex items-center space-x-6">
        {/* System Uptime */}
        <div className="hidden md:flex items-center space-x-1">
          <span>Uptime:</span>
          <span className="font-mono">{getUptimeDisplay()}</span>
        </div>
        
        {/* Current Time - Only show after hydration */}
        <div className="flex items-center space-x-1">
          <Clock className="w-3 h-3" />
          <span className="font-mono">
            {isClient && currentTime ? formatTime(currentTime) : '--:--:--'}
          </span>
        </div>
        
        {/* Versions */}
        <div className="flex items-center space-x-2">
          <div className="flex items-center space-x-1">
            <span className="text-gray-400">Backend</span>
            <span className="font-mono text-gray-500">{systemStatus.backendVersion || 'unknown'}</span>
          </div>
          <div className="flex items-center space-x-1">
            <span className="text-gray-400">API</span>
            <span className="font-mono text-gray-500">{API_PATH_VERSION.toUpperCase()}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

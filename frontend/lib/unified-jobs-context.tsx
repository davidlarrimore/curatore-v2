'use client'

/**
 * Unified Jobs Context
 *
 * Global context for tracking all jobs (active jobs, deletion jobs) and queue
 * statistics across all pages. Replaces the separate active-jobs-context,
 * deletion-jobs-context, and queue-context with a single unified provider.
 *
 * Features:
 * - WebSocket-based real-time updates with fallback to polling
 * - Unified job tracking for all job types including deletions
 * - Session storage persistence (survives page navigation)
 * - Automatic state reconciliation on reconnection
 * - Standardized toast notifications via notification-service
 *
 * Usage:
 *   import { useUnifiedJobs } from '@/lib/unified-jobs-context'
 *
 *   const {
 *     jobs,
 *     queueStats,
 *     connectionStatus,
 *     addJob,
 *     updateJob,
 *     removeJob,
 *   } = useUnifiedJobs()
 */

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  ReactNode,
} from 'react'
import { useAuth } from './auth-context'
import { runsApi, queueAdminApi, Run } from './api'
import { JobType, JOB_TYPE_CONFIG, getJobTypeFromRunType } from './job-type-config'
import { notificationService } from './notification-service'
import {
  createWebSocketClient,
  isWebSocketEnabled,
  isWebSocketSupported,
  ConnectionStatus,
  JobUpdateMessage,
  WebSocketClient,
  RunStatusData,
  QueueStatsData,
  InitialStateData,
} from './websocket-client'
import { POLLING } from './polling-config'

// ============================================================================
// Types
// ============================================================================

/**
 * Progress information for a job
 */
export interface JobProgress {
  phase?: string
  current?: number
  total?: number
  percent?: number
  unit?: string
  currentItem?: string
  // Child job tracking (for parent-child patterns)
  childJobsTotal?: number
  childJobsCompleted?: number
  childJobsFailed?: number
}

/**
 * Unified job record that combines active jobs and deletion jobs
 */
export interface UnifiedJob {
  runId: string
  groupId?: string
  jobType: JobType | 'deletion'
  displayName: string
  resourceId: string
  resourceType: string
  status: string
  startedAt: string // ISO string for serialization
  progress?: JobProgress
  errorMessage?: string
  // Deletion-specific fields
  configId?: string
  configType?: 'sharepoint' | 'sam' | 'scrape'
}

/**
 * Queue statistics (from backend)
 */
export interface UnifiedQueueStats {
  extraction_queue: {
    pending: number
    submitted: number
    running: number
    max_concurrent: number
  }
  celery_queues: {
    processing_priority: number
    extraction: number
    sam: number
    scrape: number
    sharepoint: number
    maintenance: number
  }
  throughput: {
    per_minute: number
    avg_extraction_seconds: number | null
  }
  recent_24h: {
    completed: number
    failed: number
    timed_out: number
  }
  workers: {
    active: number
    tasks_running: number
  }
}

/**
 * Unified jobs state
 */
export interface UnifiedJobsState {
  jobs: UnifiedJob[]
  queueStats: UnifiedQueueStats | null
  connectionStatus: ConnectionStatus
  isLoading: boolean
  error: string | null
  lastUpdated: Date | null
}

/**
 * Context value interface
 */
interface UnifiedJobsContextValue {
  // State
  jobs: UnifiedJob[]
  queueStats: UnifiedQueueStats | null
  connectionStatus: ConnectionStatus
  isLoading: boolean
  error: string | null
  lastUpdated: Date | null

  // Job management
  addJob: (job: Omit<UnifiedJob, 'startedAt' | 'status'>) => void
  updateJob: (runId: string, updates: Partial<UnifiedJob>) => void
  removeJob: (runId: string) => void

  // Queries
  getJobsForResource: (resourceType: string, resourceId: string) => UnifiedJob[]
  isResourceBusy: (resourceType: string, resourceId: string) => boolean
  getJobsByType: (jobType: JobType | 'deletion') => UnifiedJob[]

  // Computed
  hasActiveJobs: boolean
  activeCount: number

  // Actions
  refresh: () => Promise<void>
}

// ============================================================================
// Constants
// ============================================================================

// Session storage key (new key to avoid conflicts during migration)
const STORAGE_KEY = 'curatore_unified_jobs'

// Polling intervals (fallback mode)
const JOB_POLL_INTERVAL = POLLING.QUEUE_STATS_MS // 5 seconds
const STATS_POLL_INTERVAL = 10000 // 10 seconds

// ============================================================================
// Context
// ============================================================================

const UnifiedJobsContext = createContext<UnifiedJobsContextValue | undefined>(undefined)

// ============================================================================
// Provider
// ============================================================================

export function UnifiedJobsProvider({ children }: { children: ReactNode }) {
  const { token, isAuthenticated, handleUnauthorized } = useAuth()

  // State
  const [jobs, setJobs] = useState<UnifiedJob[]>([])
  const [queueStats, setQueueStats] = useState<UnifiedQueueStats | null>(null)
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('disconnected')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  // Refs
  const wsClientRef = useRef<WebSocketClient | null>(null)
  const jobPollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const statsPollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const isPollingRef = useRef(false)
  const previousConnectionStatus = useRef<ConnectionStatus>('disconnected')
  const wasEverConnected = useRef(false)

  // ============================================================================
  // Session Storage
  // ============================================================================

  // Load jobs from session storage on mount
  useEffect(() => {
    const stored = sessionStorage.getItem(STORAGE_KEY)
    if (stored) {
      try {
        const parsed = JSON.parse(stored) as UnifiedJob[]
        setJobs(parsed)
      } catch {
        sessionStorage.removeItem(STORAGE_KEY)
      }
    }
  }, [])

  // Save jobs to session storage when they change
  useEffect(() => {
    if (jobs.length > 0) {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(jobs))
    } else {
      sessionStorage.removeItem(STORAGE_KEY)
    }
  }, [jobs])

  // ============================================================================
  // Job Management
  // ============================================================================

  // Convert run data to unified job
  const runToJob = useCallback((run: RunStatusData, existingJob?: UnifiedJob): UnifiedJob | null => {
    const jobType = getJobTypeFromRunType(run.run_type)
    if (!jobType && run.run_type !== 'deletion') {
      return null
    }

    // Use existing job data as base if available
    const baseJob = existingJob || {
      runId: run.run_id,
      displayName: run.results_summary?.name || run.results_summary?.display_name || 'Unknown',
      resourceId: run.results_summary?.resource_id || run.run_id,
      resourceType: run.results_summary?.resource_type || run.run_type,
    }

    const progress: JobProgress = {}
    if (run.progress) {
      progress.phase = run.progress.phase
      progress.current = run.progress.current
      progress.total = run.progress.total
      progress.percent = run.progress.percent
      progress.unit = run.progress.unit
      // Child job tracking
      if (run.results_summary?.total_children !== undefined) {
        progress.childJobsTotal = run.results_summary.total_children
        progress.childJobsCompleted = run.results_summary.completed_children
        progress.childJobsFailed = run.results_summary.failed_children
      }
    }

    return {
      ...baseJob,
      runId: run.run_id,
      groupId: run.results_summary?.group_id,
      jobType: run.run_type === 'deletion' ? 'deletion' : (jobType || 'extraction' as JobType),
      status: run.status,
      startedAt: run.started_at || run.created_at || new Date().toISOString(),
      progress: Object.keys(progress).length > 0 ? progress : undefined,
      errorMessage: run.error_message || undefined,
    }
  }, [])

  // Handle job status update from WebSocket
  const handleJobStatusUpdate = useCallback((data: RunStatusData, skipNotification = false) => {
    // Check for terminal status (completed, failed, cancelled)
    const isTerminal = ['completed', 'failed', 'cancelled', 'timed_out'].includes(data.status)

    // Track what notification to show (determined before state update)
    let notificationToShow: { type: 'completed' | 'failed' | 'cancelled', jobType: string, displayName: string, error?: string } | null = null

    setJobs(prev => {
      const existingJob = prev.find(j => j.runId === data.run_id)
      const updatedJob = runToJob(data, existingJob)

      if (!updatedJob) return prev

      if (isTerminal && existingJob && !skipNotification) {
        // Only notify for jobs we were tracking (existingJob exists)
        notificationToShow = {
          type: data.status === 'completed' ? 'completed' : data.status === 'cancelled' ? 'cancelled' : 'failed',
          jobType: updatedJob.jobType,
          displayName: updatedJob.displayName,
          error: data.error_message || undefined,
        }
      }

      if (isTerminal) {
        // Remove from tracked jobs
        return prev.filter(j => j.runId !== data.run_id)
      }

      // Update existing job or add new one
      if (existingJob) {
        return prev.map(j => j.runId === data.run_id ? updatedJob : j)
      }

      // New job - don't add to tracked list automatically
      // Jobs should be added explicitly via addJob()
      return prev
    })

    // Show notification after state update (outside of render)
    if (notificationToShow) {
      // Use setTimeout to ensure we're outside of React's render phase
      setTimeout(() => {
        if (notificationToShow!.type === 'completed') {
          notificationService.jobCompleted(notificationToShow!.jobType as any, notificationToShow!.displayName)
        } else if (notificationToShow!.type === 'failed') {
          notificationService.jobFailed(notificationToShow!.jobType as any, notificationToShow!.displayName, notificationToShow!.error)
        } else if (notificationToShow!.type === 'cancelled') {
          notificationService.jobCancelled(notificationToShow!.jobType as any, notificationToShow!.displayName)
        }
      }, 0)
    }
  }, [runToJob])

  // Handle WebSocket message
  const handleWebSocketMessage = useCallback((message: JobUpdateMessage) => {
    switch (message.type) {
      case 'run_status':
        handleJobStatusUpdate(message.data as RunStatusData)
        setLastUpdated(new Date())
        break

      case 'run_progress':
        const progressData = message.data as RunStatusData
        setJobs(prev => prev.map(job => {
          if (job.runId !== progressData.run_id) return job
          const progress: JobProgress = {
            ...job.progress,
            phase: progressData.progress?.phase,
            current: progressData.progress?.current,
            total: progressData.progress?.total,
            percent: progressData.progress?.percent,
            unit: progressData.progress?.unit,
          }
          return { ...job, progress }
        }))
        break

      case 'queue_stats':
        setQueueStats(message.data as QueueStatsData)
        setLastUpdated(new Date())
        break

      case 'initial_state':
        const initialData = message.data as InitialStateData
        // Update queue stats
        if (initialData.queue_stats) {
          setQueueStats(initialData.queue_stats)
        }
        // Reconcile active runs with local state
        // Note: We don't replace local jobs, just update status for ones we're tracking
        initialData.active_runs?.forEach(run => {
          setJobs(prev => {
            const existingJob = prev.find(j => j.runId === run.run_id)
            if (existingJob) {
              const updatedJob = runToJob(run, existingJob)
              if (updatedJob) {
                return prev.map(j => j.runId === run.run_id ? updatedJob : j)
              }
            }
            return prev
          })
        })
        setLastUpdated(new Date())
        setIsLoading(false)
        break

      case 'pong':
        // Heartbeat response, no action needed
        break
    }
  }, [handleJobStatusUpdate, runToJob])

  // Handle connection status change
  // Note: We don't show toast notifications for connection changes - the StatusBar
  // has a ConnectionStatusIndicator that shows the current state. Toasts are too
  // intrusive for connection status which can fluctuate.
  const handleConnectionChange = useCallback((status: ConnectionStatus) => {
    setConnectionStatus(status)

    // Track if we ever successfully connected (used for fallback decisions)
    if (status === 'connected') {
      wasEverConnected.current = true
    }

    previousConnectionStatus.current = status
  }, [])

  // Handle fallback to polling
  // Note: No toast notification - the StatusBar indicator shows "Polling" status
  const handleFallbackToPolling = useCallback(() => {
    startPolling()
  }, [])

  // Handle WebSocket auth error (token expired)
  // This triggers the auth context to redirect to login
  const handleWebSocketAuthError = useCallback(() => {
    console.log('WebSocket auth error - triggering session expiration')
    handleUnauthorized()
  }, [handleUnauthorized])

  // ============================================================================
  // Polling (Fallback)
  // ============================================================================

  // Poll job statuses
  const pollJobStatuses = useCallback(async () => {
    if (!token || jobs.length === 0 || isPollingRef.current) return

    isPollingRef.current = true

    for (const job of jobs) {
      try {
        const run = await runsApi.getRun(job.runId, token)
        handleJobStatusUpdate({
          run_id: run.id,
          run_type: run.run_type,
          status: run.status,
          progress: run.progress,
          results_summary: run.results_summary,
          error_message: run.error_message,
          created_at: run.created_at,
          started_at: run.started_at,
          completed_at: run.completed_at,
        })
      } catch (err: any) {
        if (err?.status === 404) {
          // Run doesn't exist, remove from tracked jobs
          setJobs(prev => prev.filter(j => j.runId !== job.runId))
        }
        console.warn(`Failed to poll job status for ${job.runId}:`, err)
      }
    }

    isPollingRef.current = false
  }, [token, jobs, handleJobStatusUpdate])

  // Poll queue stats
  const pollQueueStats = useCallback(async () => {
    if (!token || !isAuthenticated) return

    try {
      const stats = await queueAdminApi.getUnifiedStats(token)
      setQueueStats(stats)
      setLastUpdated(new Date())
      setError(null)
    } catch (err: any) {
      console.warn('Failed to poll queue stats:', err)
      if (!queueStats) {
        setError(err.message || 'Failed to load queue stats')
      }
    } finally {
      setIsLoading(false)
    }
  }, [token, isAuthenticated, queueStats])

  // Start polling (fallback mode)
  const startPolling = useCallback(() => {
    // Stop any existing polling
    stopPolling()

    // Poll jobs every 5 seconds
    jobPollIntervalRef.current = setInterval(pollJobStatuses, JOB_POLL_INTERVAL)

    // Poll queue stats every 10 seconds
    statsPollIntervalRef.current = setInterval(pollQueueStats, STATS_POLL_INTERVAL)

    // Initial poll
    pollJobStatuses()
    pollQueueStats()
  }, [pollJobStatuses, pollQueueStats])

  // Stop polling
  const stopPolling = useCallback(() => {
    if (jobPollIntervalRef.current) {
      clearInterval(jobPollIntervalRef.current)
      jobPollIntervalRef.current = null
    }
    if (statsPollIntervalRef.current) {
      clearInterval(statsPollIntervalRef.current)
      statsPollIntervalRef.current = null
    }
  }, [])

  // ============================================================================
  // WebSocket Connection
  // ============================================================================

  useEffect(() => {
    if (!token || !isAuthenticated) {
      setIsLoading(false)
      return
    }

    // Check if WebSocket is supported and enabled
    if (!isWebSocketSupported() || !isWebSocketEnabled()) {
      console.log('WebSocket not available or disabled, using polling')
      setConnectionStatus('polling')
      startPolling()
      return
    }

    // Create WebSocket client with error handling
    try {
      wsClientRef.current = createWebSocketClient({
        token,
        onMessage: handleWebSocketMessage,
        onConnectionChange: handleConnectionChange,
        onFallbackToPolling: handleFallbackToPolling,
        onAuthError: handleWebSocketAuthError,
        enabled: true,
      })
    } catch (err) {
      console.error('Failed to create WebSocket client:', err)
      setConnectionStatus('polling')
      startPolling()
    }

    return () => {
      wsClientRef.current?.disconnect()
      wsClientRef.current = null
      stopPolling()
    }
  }, [token, isAuthenticated, handleWebSocketMessage, handleConnectionChange, handleFallbackToPolling, handleWebSocketAuthError, startPolling, stopPolling])

  // Start polling when in polling mode
  useEffect(() => {
    if (connectionStatus === 'polling' && token && isAuthenticated) {
      startPolling()
    } else if (connectionStatus === 'connected') {
      stopPolling()
    }
  }, [connectionStatus, token, isAuthenticated, startPolling, stopPolling])

  // ============================================================================
  // Public Methods
  // ============================================================================

  // Add a new job
  const addJob = useCallback((job: Omit<UnifiedJob, 'startedAt' | 'status'>) => {
    const newJob: UnifiedJob = {
      ...job,
      startedAt: new Date().toISOString(),
      status: 'pending',
    }

    setJobs(prev => {
      // Check if job already exists
      if (prev.some(j => j.runId === job.runId)) {
        return prev
      }
      return [...prev, newJob]
    })

    // Show start toast
    notificationService.jobStarted(job.jobType, job.displayName)
  }, [])

  // Update a job
  const updateJob = useCallback((runId: string, updates: Partial<UnifiedJob>) => {
    setJobs(prev => prev.map(job =>
      job.runId === runId ? { ...job, ...updates } : job
    ))
  }, [])

  // Remove a job
  const removeJob = useCallback((runId: string) => {
    setJobs(prev => prev.filter(job => job.runId !== runId))
  }, [])

  // Get jobs for a specific resource
  const getJobsForResource = useCallback(
    (resourceType: string, resourceId: string): UnifiedJob[] => {
      return jobs.filter(
        job => job.resourceType === resourceType && job.resourceId === resourceId
      )
    },
    [jobs]
  )

  // Check if a resource has any active jobs
  const isResourceBusy = useCallback(
    (resourceType: string, resourceId: string): boolean => {
      return jobs.some(
        job => job.resourceType === resourceType && job.resourceId === resourceId
      )
    },
    [jobs]
  )

  // Get jobs by type
  const getJobsByType = useCallback(
    (jobType: JobType | 'deletion'): UnifiedJob[] => {
      return jobs.filter(job => job.jobType === jobType)
    },
    [jobs]
  )

  // Manual refresh
  const refresh = useCallback(async () => {
    await pollQueueStats()
    await pollJobStatuses()
  }, [pollQueueStats, pollJobStatuses])

  // ============================================================================
  // Computed Values
  // ============================================================================

  const hasActiveJobs = jobs.length > 0
  // Count active jobs across ALL queues, not just extraction
  const activeCount = queueStats
    ? (
        // Extraction queue (pending + submitted + running)
        queueStats.extraction_queue.pending +
        queueStats.extraction_queue.submitted +
        queueStats.extraction_queue.running +
        // Other Celery queues (these show queued tasks, which are active)
        queueStats.celery_queues.sharepoint +
        queueStats.celery_queues.sam +
        queueStats.celery_queues.scrape +
        queueStats.celery_queues.maintenance
      )
    : 0

  // ============================================================================
  // Context Value
  // ============================================================================

  const value: UnifiedJobsContextValue = {
    // State
    jobs,
    queueStats,
    connectionStatus,
    isLoading,
    error,
    lastUpdated,

    // Job management
    addJob,
    updateJob,
    removeJob,

    // Queries
    getJobsForResource,
    isResourceBusy,
    getJobsByType,

    // Computed
    hasActiveJobs,
    activeCount,

    // Actions
    refresh,
  }

  return (
    <UnifiedJobsContext.Provider value={value}>
      {children}
    </UnifiedJobsContext.Provider>
  )
}

// ============================================================================
// Hook
// ============================================================================

/**
 * Hook to access unified jobs context.
 *
 * @throws Error if used outside of UnifiedJobsProvider
 */
export function useUnifiedJobs(): UnifiedJobsContextValue {
  const context = useContext(UnifiedJobsContext)
  if (context === undefined) {
    throw new Error('useUnifiedJobs must be used within a UnifiedJobsProvider')
  }
  return context
}

export default UnifiedJobsProvider

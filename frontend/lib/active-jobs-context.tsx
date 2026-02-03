'use client'

/**
 * Active Jobs Context
 *
 * Global context for tracking parent jobs (SAM.gov pull, SharePoint Sync,
 * Web Scraping, File Upload, Pipelines, Procedures) across all pages.
 *
 * Provides:
 * - Tracking of in-flight parent jobs
 * - Session storage persistence (survives page navigation)
 * - Polling for run status with child job counts
 * - Toast notifications on job start/completion/failure
 *
 * Pattern based on deletion-jobs-context.tsx
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
import toast from 'react-hot-toast'
import { runsApi, Run } from './api'
import { useAuth } from './auth-context'
import { JobType, JOB_TYPE_CONFIG, getJobTypeFromRunType } from './job-type-config'

// Progress information for a job
export interface JobProgress {
  phase?: string
  processed?: number
  total?: number
  currentItem?: string
  // Child job tracking (for parent-child patterns)
  childJobsTotal?: number
  childJobsCompleted?: number
  childJobsFailed?: number
}

// Active job record
export interface ActiveJob {
  runId: string
  groupId?: string // Run group ID for parent-child tracking
  jobType: JobType
  displayName: string
  resourceId: string
  resourceType: string
  startedAt: string // ISO string for serialization
  progress?: JobProgress
}

// Context value interface
interface ActiveJobsContextValue {
  activeJobs: ActiveJob[]
  addJob: (job: Omit<ActiveJob, 'startedAt'>) => void
  updateJobProgress: (runId: string, progress: JobProgress) => void
  removeJob: (runId: string) => void
  getJobsForResource: (resourceType: string, resourceId: string) => ActiveJob[]
  isResourceBusy: (resourceType: string, resourceId: string) => boolean
  hasActiveJobs: boolean
}

// Session storage key
const STORAGE_KEY = 'curatore_active_jobs'

// Polling interval in milliseconds
const POLL_INTERVAL = 5000

// Create context
const ActiveJobsContext = createContext<ActiveJobsContextValue | undefined>(undefined)

// Provider component
export function ActiveJobsProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth()
  const [activeJobs, setActiveJobs] = useState<ActiveJob[]>([])
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const isPollingRef = useRef(false)

  // Load jobs from session storage on mount
  useEffect(() => {
    const stored = sessionStorage.getItem(STORAGE_KEY)
    if (stored) {
      try {
        const parsed = JSON.parse(stored) as ActiveJob[]
        setActiveJobs(parsed)
      } catch {
        sessionStorage.removeItem(STORAGE_KEY)
      }
    }
  }, [])

  // Save jobs to session storage when they change
  useEffect(() => {
    if (activeJobs.length > 0) {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(activeJobs))
    } else {
      sessionStorage.removeItem(STORAGE_KEY)
    }
  }, [activeJobs])

  // Check status of all active jobs
  const checkJobStatuses = useCallback(async () => {
    if (!token || activeJobs.length === 0 || isPollingRef.current) return

    isPollingRef.current = true

    const jobsToRemove: string[] = []
    const jobUpdates: Map<string, Partial<ActiveJob>> = new Map()

    for (const job of activeJobs) {
      try {
        const run = await runsApi.getRun(job.runId, token)
        const config = JOB_TYPE_CONFIG[job.jobType]

        // Update progress from run results_summary
        if (run.results_summary) {
          const summary = run.results_summary as Record<string, any>
          const progress: JobProgress = {
            phase: summary.phase || summary.current_phase,
            processed: summary.processed || summary.files_processed,
            total: summary.total || summary.total_files,
            currentItem: summary.current_item,
          }

          // Check for child job counts (from run groups)
          if (summary.total_children !== undefined) {
            progress.childJobsTotal = summary.total_children
            progress.childJobsCompleted = summary.completed_children
            progress.childJobsFailed = summary.failed_children
          }

          jobUpdates.set(job.runId, { progress })
        }

        // Check if run completed
        if (run.status === 'completed') {
          toast.success(config.completedToast(job.displayName), {
            duration: 5000,
          })
          jobsToRemove.push(job.runId)
        } else if (run.status === 'failed') {
          toast.error(config.failedToast(job.displayName, run.error_message), {
            duration: 8000,
          })
          jobsToRemove.push(job.runId)
        } else if (run.status === 'cancelled') {
          toast.error(`${config.label} cancelled: ${job.displayName}`, {
            duration: 5000,
          })
          jobsToRemove.push(job.runId)
        }
        // If still pending/running, keep polling
      } catch (err: any) {
        // If we get a 404, the run doesn't exist
        if (err?.status === 404) {
          jobsToRemove.push(job.runId)
        }
        console.warn(`Failed to check job status for ${job.runId}:`, err)
      }
    }

    // Apply updates and removals
    if (jobsToRemove.length > 0 || jobUpdates.size > 0) {
      setActiveJobs(prev =>
        prev
          .filter(job => !jobsToRemove.includes(job.runId))
          .map(job => {
            const update = jobUpdates.get(job.runId)
            return update ? { ...job, ...update } : job
          })
      )
    }

    isPollingRef.current = false
  }, [token, activeJobs])

  // Start/stop polling based on active jobs
  useEffect(() => {
    if (activeJobs.length > 0 && token) {
      if (!pollIntervalRef.current) {
        // Check immediately
        checkJobStatuses()
        // Then poll periodically
        pollIntervalRef.current = setInterval(checkJobStatuses, POLL_INTERVAL)
      }
    } else {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
        pollIntervalRef.current = null
      }
    }

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
        pollIntervalRef.current = null
      }
    }
  }, [activeJobs.length, token, checkJobStatuses])

  // Add a new job
  const addJob = useCallback((job: Omit<ActiveJob, 'startedAt'>) => {
    const newJob: ActiveJob = {
      ...job,
      startedAt: new Date().toISOString(),
    }
    setActiveJobs(prev => {
      // Check if job with same runId already exists
      if (prev.some(j => j.runId === job.runId)) {
        return prev
      }
      return [...prev, newJob]
    })

    // Show start toast
    const config = JOB_TYPE_CONFIG[job.jobType]
    toast.success(`${config.label} started: ${job.displayName}`, {
      duration: 3000,
    })
  }, [])

  // Update job progress
  const updateJobProgress = useCallback((runId: string, progress: JobProgress) => {
    setActiveJobs(prev =>
      prev.map(job =>
        job.runId === runId
          ? { ...job, progress: { ...job.progress, ...progress } }
          : job
      )
    )
  }, [])

  // Remove a job by runId
  const removeJob = useCallback((runId: string) => {
    setActiveJobs(prev => prev.filter(job => job.runId !== runId))
  }, [])

  // Get jobs for a specific resource
  const getJobsForResource = useCallback(
    (resourceType: string, resourceId: string): ActiveJob[] => {
      return activeJobs.filter(
        job => job.resourceType === resourceType && job.resourceId === resourceId
      )
    },
    [activeJobs]
  )

  // Check if a resource has any active jobs
  const isResourceBusy = useCallback(
    (resourceType: string, resourceId: string): boolean => {
      return activeJobs.some(
        job => job.resourceType === resourceType && job.resourceId === resourceId
      )
    },
    [activeJobs]
  )

  const value: ActiveJobsContextValue = {
    activeJobs,
    addJob,
    updateJobProgress,
    removeJob,
    getJobsForResource,
    isResourceBusy,
    hasActiveJobs: activeJobs.length > 0,
  }

  return (
    <ActiveJobsContext.Provider value={value}>
      {children}
    </ActiveJobsContext.Provider>
  )
}

// Hook to use the context
export function useActiveJobs(): ActiveJobsContextValue {
  const context = useContext(ActiveJobsContext)
  if (context === undefined) {
    throw new Error('useActiveJobs must be used within an ActiveJobsProvider')
  }
  return context
}

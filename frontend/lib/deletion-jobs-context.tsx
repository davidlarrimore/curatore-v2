'use client'

/**
 * Global context for tracking async deletion jobs.
 *
 * Provides:
 * - Tracking of in-flight deletion jobs
 * - Session storage persistence (survives page navigation)
 * - Polling for run status
 * - Toast notifications on completion/failure
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

// Types
export interface DeletionJob {
  runId: string
  configId: string
  configName: string
  configType: 'sharepoint' | 'sam' | 'scrape'
  startedAt: string // ISO string for serialization
}

interface DeletionJobsContextValue {
  activeJobs: DeletionJob[]
  addJob: (job: Omit<DeletionJob, 'startedAt'>) => void
  removeJob: (runId: string) => void
  isDeleting: (configId: string) => boolean
  isDeletingAny: boolean
}

// Session storage key
const STORAGE_KEY = 'curatore_deletion_jobs'

// Polling interval in milliseconds
const POLL_INTERVAL = 5000

// Create context
const DeletionJobsContext = createContext<DeletionJobsContextValue | undefined>(undefined)

// Provider component
export function DeletionJobsProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth()
  const [activeJobs, setActiveJobs] = useState<DeletionJob[]>([])
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const isPollingRef = useRef(false)

  // Load jobs from session storage on mount
  useEffect(() => {
    const stored = sessionStorage.getItem(STORAGE_KEY)
    if (stored) {
      try {
        const parsed = JSON.parse(stored) as DeletionJob[]
        setActiveJobs(parsed)
      } catch {
        // Invalid data, clear it
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

    for (const job of activeJobs) {
      try {
        const run = await runsApi.getRun(job.runId, token)

        // Check if run completed
        if (run.status === 'completed') {
          const errorCount = run.results_summary?.errors?.length || 0
          if (errorCount === 0) {
            toast.success(`"${job.configName}" deleted successfully`, {
              duration: 5000,
            })
          } else {
            toast.success(`"${job.configName}" deleted with ${errorCount} minor errors`, {
              duration: 5000,
            })
          }
          jobsToRemove.push(job.runId)
        } else if (run.status === 'failed') {
          toast.error(`Failed to delete "${job.configName}": ${run.error_message || 'Unknown error'}`, {
            duration: 8000,
          })
          jobsToRemove.push(job.runId)
        } else if (run.status === 'cancelled') {
          toast.error(`Deletion of "${job.configName}" was cancelled`, {
            duration: 5000,
          })
          jobsToRemove.push(job.runId)
        }
        // If still pending/running, keep polling
      } catch (err: any) {
        // If we get a 404, the run doesn't exist (maybe config was already deleted)
        if (err?.status === 404) {
          jobsToRemove.push(job.runId)
        }
        // For other errors, log but keep polling
        console.warn(`Failed to check deletion status for ${job.runId}:`, err)
      }
    }

    // Remove completed/failed jobs
    if (jobsToRemove.length > 0) {
      setActiveJobs(prev => prev.filter(job => !jobsToRemove.includes(job.runId)))
    }

    isPollingRef.current = false
  }, [token, activeJobs])

  // Start/stop polling based on active jobs
  useEffect(() => {
    if (activeJobs.length > 0 && token) {
      // Start polling
      if (!pollIntervalRef.current) {
        // Check immediately
        checkJobStatuses()
        // Then poll periodically
        pollIntervalRef.current = setInterval(checkJobStatuses, POLL_INTERVAL)
      }
    } else {
      // Stop polling
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
  const addJob = useCallback((job: Omit<DeletionJob, 'startedAt'>) => {
    const newJob: DeletionJob = {
      ...job,
      startedAt: new Date().toISOString(),
    }
    setActiveJobs(prev => [...prev, newJob])
  }, [])

  // Remove a job by runId
  const removeJob = useCallback((runId: string) => {
    setActiveJobs(prev => prev.filter(job => job.runId !== runId))
  }, [])

  // Check if a specific config is being deleted
  const isDeleting = useCallback((configId: string) => {
    return activeJobs.some(job => job.configId === configId)
  }, [activeJobs])

  // Check if any deletion is in progress
  const isDeletingAny = activeJobs.length > 0

  const value: DeletionJobsContextValue = {
    activeJobs,
    addJob,
    removeJob,
    isDeleting,
    isDeletingAny,
  }

  return (
    <DeletionJobsContext.Provider value={value}>
      {children}
    </DeletionJobsContext.Provider>
  )
}

// Hook to use the context
export function useDeletionJobs(): DeletionJobsContextValue {
  const context = useContext(DeletionJobsContext)
  if (context === undefined) {
    throw new Error('useDeletionJobs must be used within a DeletionJobsProvider')
  }
  return context
}

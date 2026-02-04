/**
 * Context Shims for Backward Compatibility
 *
 * Provides backward-compatible hooks that wrap the unified jobs context,
 * allowing gradual migration of existing components from the old separate
 * contexts (active-jobs-context, deletion-jobs-context, queue-context)
 * to the new unified context.
 *
 * Usage:
 *   // Instead of importing from the old contexts:
 *   // import { useActiveJobs } from '@/lib/active-jobs-context'
 *   // import { useDeletionJobs } from '@/lib/deletion-jobs-context'
 *   // import { useQueue } from '@/lib/queue-context'
 *
 *   // Import from the shims:
 *   import { useActiveJobs, useDeletionJobs, useQueue } from '@/lib/context-shims'
 *
 * These shims will be removed after all components are migrated to use
 * useUnifiedJobs directly.
 */

import { useUnifiedJobs, UnifiedJob, JobProgress as UnifiedJobProgress, UnifiedQueueStats } from './unified-jobs-context'
import { JobType } from './job-type-config'

// Re-export JobProgress for backward compatibility
export type JobProgress = UnifiedJobProgress

// ============================================================================
// Active Jobs Shim
// ============================================================================

/**
 * Active job record (for backward compatibility)
 * @deprecated Use UnifiedJob from unified-jobs-context instead
 */
export interface ActiveJob {
  runId: string
  groupId?: string
  jobType: JobType
  displayName: string
  resourceId: string
  resourceType: string
  startedAt: string
  progress?: JobProgress
}

/**
 * Active jobs context value (for backward compatibility)
 * @deprecated Use useUnifiedJobs instead
 */
interface ActiveJobsContextValue {
  activeJobs: ActiveJob[]
  addJob: (job: Omit<ActiveJob, 'startedAt'>) => void
  updateJobProgress: (runId: string, progress: JobProgress) => void
  removeJob: (runId: string) => void
  getJobsForResource: (resourceType: string, resourceId: string) => ActiveJob[]
  isResourceBusy: (resourceType: string, resourceId: string) => boolean
  hasActiveJobs: boolean
}

/**
 * Backward-compatible hook for active jobs.
 * @deprecated Use useUnifiedJobs instead
 */
export function useActiveJobs(): ActiveJobsContextValue {
  const {
    jobs,
    addJob: addUnifiedJob,
    updateJob,
    removeJob,
    getJobsForResource: getUnifiedJobsForResource,
    isResourceBusy,
    hasActiveJobs,
  } = useUnifiedJobs()

  // Filter to only non-deletion jobs and map to ActiveJob format
  const activeJobs: ActiveJob[] = jobs
    .filter(job => job.jobType !== 'deletion')
    .map(job => ({
      runId: job.runId,
      groupId: job.groupId,
      jobType: job.jobType as JobType,
      displayName: job.displayName,
      resourceId: job.resourceId,
      resourceType: job.resourceType,
      startedAt: job.startedAt,
      progress: job.progress,
    }))

  // Wrap addJob to match old signature
  const addJob = (job: Omit<ActiveJob, 'startedAt'>) => {
    addUnifiedJob({
      runId: job.runId,
      groupId: job.groupId,
      jobType: job.jobType,
      displayName: job.displayName,
      resourceId: job.resourceId,
      resourceType: job.resourceType,
      progress: job.progress,
    })
  }

  // Wrap updateJobProgress
  const updateJobProgress = (runId: string, progress: JobProgress) => {
    updateJob(runId, { progress })
  }

  // Wrap getJobsForResource to return only active jobs
  const getJobsForResource = (resourceType: string, resourceId: string): ActiveJob[] => {
    return getUnifiedJobsForResource(resourceType, resourceId)
      .filter(job => job.jobType !== 'deletion')
      .map(job => ({
        runId: job.runId,
        groupId: job.groupId,
        jobType: job.jobType as JobType,
        displayName: job.displayName,
        resourceId: job.resourceId,
        resourceType: job.resourceType,
        startedAt: job.startedAt,
        progress: job.progress,
      }))
  }

  return {
    activeJobs,
    addJob,
    updateJobProgress,
    removeJob,
    getJobsForResource,
    isResourceBusy,
    hasActiveJobs: activeJobs.length > 0,
  }
}

// ============================================================================
// Deletion Jobs Shim
// ============================================================================

/**
 * Deletion job record (for backward compatibility)
 * @deprecated Use UnifiedJob from unified-jobs-context instead
 */
export interface DeletionJob {
  runId: string
  configId: string
  configName: string
  configType: 'sharepoint' | 'sam' | 'scrape'
  startedAt: string
}

/**
 * Deletion jobs context value (for backward compatibility)
 * @deprecated Use useUnifiedJobs instead
 */
interface DeletionJobsContextValue {
  activeJobs: DeletionJob[]
  addJob: (job: Omit<DeletionJob, 'startedAt'>) => void
  removeJob: (runId: string) => void
  isDeleting: (configId: string) => boolean
  isDeletingAny: boolean
}

/**
 * Backward-compatible hook for deletion jobs.
 * @deprecated Use useUnifiedJobs instead
 */
export function useDeletionJobs(): DeletionJobsContextValue {
  const {
    jobs,
    addJob: addUnifiedJob,
    removeJob,
    getJobsByType,
  } = useUnifiedJobs()

  // Filter to only deletion jobs and map to DeletionJob format
  const activeJobs: DeletionJob[] = jobs
    .filter(job => job.jobType === 'deletion')
    .map(job => ({
      runId: job.runId,
      configId: job.configId || job.resourceId,
      configName: job.displayName,
      configType: (job.configType || 'sharepoint') as 'sharepoint' | 'sam' | 'scrape',
      startedAt: job.startedAt,
    }))

  // Wrap addJob to match old signature
  const addJob = (job: Omit<DeletionJob, 'startedAt'>) => {
    addUnifiedJob({
      runId: job.runId,
      jobType: 'deletion',
      displayName: job.configName,
      resourceId: job.configId,
      resourceType: 'deletion',
      configId: job.configId,
      configType: job.configType,
    })
  }

  // Check if a specific config is being deleted
  const isDeleting = (configId: string): boolean => {
    return activeJobs.some(job => job.configId === configId)
  }

  return {
    activeJobs,
    addJob,
    removeJob,
    isDeleting,
    isDeletingAny: activeJobs.length > 0,
  }
}

// ============================================================================
// Queue Context Shim
// ============================================================================

/**
 * Queue state (for backward compatibility)
 * @deprecated Use useUnifiedJobs instead
 */
interface QueueState {
  stats: UnifiedQueueStats | null
  isLoading: boolean
  error: string | null
  lastUpdated: Date | null
  refresh: () => Promise<void>
  activeCount: number
}

/**
 * Backward-compatible hook for queue statistics.
 * @deprecated Use useUnifiedJobs instead
 */
export function useQueue(): QueueState {
  const {
    queueStats,
    isLoading,
    error,
    lastUpdated,
    refresh,
    activeCount,
  } = useUnifiedJobs()

  return {
    stats: queueStats,
    isLoading,
    error,
    lastUpdated,
    refresh,
    activeCount,
  }
}

/**
 * Backward-compatible hook to check if any extractions are active.
 * @deprecated Use useUnifiedJobs instead
 */
export function useHasActiveExtractions(): boolean {
  const { activeCount } = useUnifiedJobs()
  return activeCount > 0
}

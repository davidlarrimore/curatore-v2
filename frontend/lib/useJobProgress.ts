/**
 * Job Progress Hooks
 *
 * Encapsulates job tracking + completion detection into reusable hooks.
 * Replaces the prevJobCountRef + useEffect boilerplate copy-pasted across pages.
 *
 * Usage:
 *   // Resource-scoped: tracks jobs for a specific resource
 *   const { jobs, isActive, latestJob } = useJobProgress('forecast_sync', syncId, {
 *     onComplete: () => loadData(true),
 *   })
 *
 *   // Type-scoped: tracks all jobs of a given type (for list pages)
 *   const { jobs, isActive } = useJobProgressByType('sam_pull', {
 *     onComplete: () => loadData(true),
 *   })
 */

import { useEffect, useRef, useCallback } from 'react'
import { useUnifiedJobs, UnifiedJob } from './unified-jobs-context'
import { JobType } from './job-type-config'

interface JobProgressOptions {
  /** Called when a tracked job completes (job count decreases) */
  onComplete?: () => void
  /** Called when a new job starts (job count increases) */
  onStart?: () => void
}

interface JobProgressResult {
  /** All active jobs matching the filter */
  jobs: UnifiedJob[]
  /** Whether any matching jobs are active */
  isActive: boolean
  /** The most recently started job (or undefined) */
  latestJob: UnifiedJob | undefined
  /** Progress from the latest job */
  progress: UnifiedJob['progress'] | undefined
  /** Phase label from latest job's progress */
  phase: string | undefined
  /** Percent complete from latest job's progress */
  percent: number | undefined
}

/**
 * Track jobs for a specific resource (detail pages).
 */
export function useJobProgress(
  resourceType: string,
  resourceId: string | undefined,
  options?: JobProgressOptions
): JobProgressResult {
  const { getJobsForResource } = useUnifiedJobs()

  const jobs = resourceId ? getJobsForResource(resourceType, resourceId) : []
  const prevCountRef = useRef(jobs.length)

  const onCompleteRef = useRef(options?.onComplete)
  const onStartRef = useRef(options?.onStart)
  onCompleteRef.current = options?.onComplete
  onStartRef.current = options?.onStart

  useEffect(() => {
    const currentCount = jobs.length
    const prevCount = prevCountRef.current

    if (currentCount < prevCount && onCompleteRef.current) {
      onCompleteRef.current()
    }
    if (currentCount > prevCount && onStartRef.current) {
      onStartRef.current()
    }

    prevCountRef.current = currentCount
  }, [jobs.length])

  const latestJob = jobs.length > 0
    ? jobs.reduce((a, b) => (a.startedAt > b.startedAt ? a : b))
    : undefined

  return {
    jobs,
    isActive: jobs.length > 0,
    latestJob,
    progress: latestJob?.progress,
    phase: latestJob?.progress?.phase,
    percent: latestJob?.progress?.percent,
  }
}

/**
 * Track all jobs of a given type (list pages).
 */
export function useJobProgressByType(
  jobType: JobType,
  options?: JobProgressOptions
): JobProgressResult {
  const { getJobsByType } = useUnifiedJobs()

  const jobs = getJobsByType(jobType)
  const prevCountRef = useRef(jobs.length)

  const onCompleteRef = useRef(options?.onComplete)
  const onStartRef = useRef(options?.onStart)
  onCompleteRef.current = options?.onComplete
  onStartRef.current = options?.onStart

  useEffect(() => {
    const currentCount = jobs.length
    const prevCount = prevCountRef.current

    if (currentCount < prevCount && onCompleteRef.current) {
      onCompleteRef.current()
    }
    if (currentCount > prevCount && onStartRef.current) {
      onStartRef.current()
    }

    prevCountRef.current = currentCount
  }, [jobs.length])

  const latestJob = jobs.length > 0
    ? jobs.reduce((a, b) => (a.startedAt > b.startedAt ? a : b))
    : undefined

  return {
    jobs,
    isActive: jobs.length > 0,
    latestJob,
    progress: latestJob?.progress,
    phase: latestJob?.progress?.phase,
    percent: latestJob?.progress?.percent,
  }
}

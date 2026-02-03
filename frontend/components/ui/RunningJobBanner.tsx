'use client'

/**
 * Running Job Banner Component
 *
 * Reusable banner for displaying active parent jobs with progress,
 * child job counts, and links to the job manager.
 */

import { Loader2, ExternalLink } from 'lucide-react'
import Link from 'next/link'
import { ActiveJob, JobProgress } from '@/lib/active-jobs-context'
import { JOB_TYPE_CONFIG, JobType } from '@/lib/job-type-config'
import { formatTimeAgo } from '@/lib/date-utils'

interface RunningJobBannerProps {
  job: ActiveJob
  variant?: 'default' | 'compact'
  showProgress?: boolean
  showChildJobs?: boolean
  onViewJob?: () => void
}

// Color class mappings for Tailwind (to ensure classes are included in build)
const colorClasses: Record<string, { bg: string; border: string; text: string; progressBg: string }> = {
  purple: {
    bg: 'bg-purple-50 dark:bg-purple-900/20',
    border: 'border-purple-100 dark:border-purple-900/50',
    text: 'text-purple-600 dark:text-purple-400',
    progressBg: 'bg-purple-500',
  },
  blue: {
    bg: 'bg-blue-50 dark:bg-blue-900/20',
    border: 'border-blue-100 dark:border-blue-900/50',
    text: 'text-blue-600 dark:text-blue-400',
    progressBg: 'bg-blue-500',
  },
  emerald: {
    bg: 'bg-emerald-50 dark:bg-emerald-900/20',
    border: 'border-emerald-100 dark:border-emerald-900/50',
    text: 'text-emerald-600 dark:text-emerald-400',
    progressBg: 'bg-emerald-500',
  },
  indigo: {
    bg: 'bg-indigo-50 dark:bg-indigo-900/20',
    border: 'border-indigo-100 dark:border-indigo-900/50',
    text: 'text-indigo-600 dark:text-indigo-400',
    progressBg: 'bg-indigo-500',
  },
  amber: {
    bg: 'bg-amber-50 dark:bg-amber-900/20',
    border: 'border-amber-100 dark:border-amber-900/50',
    text: 'text-amber-600 dark:text-amber-400',
    progressBg: 'bg-amber-500',
  },
  cyan: {
    bg: 'bg-cyan-50 dark:bg-cyan-900/20',
    border: 'border-cyan-100 dark:border-cyan-900/50',
    text: 'text-cyan-600 dark:text-cyan-400',
    progressBg: 'bg-cyan-500',
  },
}

export function RunningJobBanner({
  job,
  variant = 'default',
  showProgress = true,
  showChildJobs = true,
  onViewJob,
}: RunningJobBannerProps) {
  const config = JOB_TYPE_CONFIG[job.jobType]
  const Icon = config.icon
  const colors = colorClasses[config.color] || colorClasses.blue

  // Calculate progress percentage
  const progressPercent =
    job.progress?.total && job.progress?.processed
      ? Math.round((job.progress.processed / job.progress.total) * 100)
      : null

  // Calculate child job progress
  const childJobsPercent =
    job.progress?.childJobsTotal &&
    (job.progress.childJobsCompleted !== undefined || job.progress.childJobsFailed !== undefined)
      ? Math.round(
          ((job.progress.childJobsCompleted || 0) + (job.progress.childJobsFailed || 0)) /
            job.progress.childJobsTotal *
            100
        )
      : null

  if (variant === 'compact') {
    return (
      <div
        className={`flex items-center gap-3 px-4 py-2 rounded-lg ${colors.bg} border ${colors.border}`}
      >
        <Loader2 className={`w-4 h-4 animate-spin ${colors.text}`} />
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
          {config.label}: {job.displayName}
        </span>
        {progressPercent !== null && (
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {progressPercent}%
          </span>
        )}
        <Link
          href={`/admin/queue?run=${job.runId}`}
          className={`text-xs ${colors.text} hover:underline ml-auto`}
          onClick={onViewJob}
        >
          View
        </Link>
      </div>
    )
  }

  return (
    <div className={`rounded-xl ${colors.bg} border ${colors.border} p-4`}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div
            className={`w-10 h-10 rounded-lg flex items-center justify-center ${colors.bg} border ${colors.border}`}
          >
            <Loader2 className={`w-5 h-5 animate-spin ${colors.text}`} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <Icon className={`w-4 h-4 ${colors.text}`} />
              <span className="text-sm font-medium text-gray-900 dark:text-white">
                {config.label}
              </span>
            </div>
            <p className="text-sm text-gray-700 dark:text-gray-300 font-medium">
              {job.displayName}
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              Started {formatTimeAgo(job.startedAt)}
              {job.progress?.phase && (
                <span className="ml-2">
                  - <span className="capitalize">{job.progress.phase}</span>
                </span>
              )}
            </p>
          </div>
        </div>

        <Link
          href={`/admin/queue?run=${job.runId}`}
          className={`flex items-center gap-1 text-sm ${colors.text} hover:underline`}
          onClick={onViewJob}
        >
          View Job
          <ExternalLink className="w-3.5 h-3.5" />
        </Link>
      </div>

      {/* Progress bar */}
      {showProgress && progressPercent !== null && (
        <div className="mt-4">
          <div className="flex items-center justify-between text-xs text-gray-600 dark:text-gray-400 mb-1">
            <span>
              {job.progress?.processed?.toLocaleString()} /{' '}
              {job.progress?.total?.toLocaleString()} items
            </span>
            <span>{progressPercent}%</span>
          </div>
          <div className="h-2 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
            <div
              className={`h-full ${colors.progressBg} transition-all duration-500`}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      )}

      {/* Child jobs grid */}
      {showChildJobs && config.hasChildJobs && job.progress?.childJobsTotal !== undefined && (
        <div className="mt-4 grid grid-cols-3 gap-3">
          <div className="text-center p-2 rounded-lg bg-white/50 dark:bg-gray-800/50">
            <p className="text-lg font-bold text-gray-900 dark:text-white">
              {job.progress.childJobsTotal}
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400">Total</p>
          </div>
          <div className="text-center p-2 rounded-lg bg-white/50 dark:bg-gray-800/50">
            <p className="text-lg font-bold text-emerald-600 dark:text-emerald-400">
              {job.progress.childJobsCompleted || 0}
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400">Completed</p>
          </div>
          <div className="text-center p-2 rounded-lg bg-white/50 dark:bg-gray-800/50">
            <p className="text-lg font-bold text-red-600 dark:text-red-400">
              {job.progress.childJobsFailed || 0}
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400">Failed</p>
          </div>
        </div>
      )}

      {/* Child jobs progress bar */}
      {showChildJobs && childJobsPercent !== null && childJobsPercent < 100 && (
        <div className="mt-3">
          <div className="flex items-center justify-between text-xs text-gray-600 dark:text-gray-400 mb-1">
            <span>Child jobs progress</span>
            <span>{childJobsPercent}%</span>
          </div>
          <div className="h-1.5 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
            <div
              className={`h-full ${colors.progressBg} transition-all duration-500`}
              style={{ width: `${childJobsPercent}%` }}
            />
          </div>
        </div>
      )}

      {/* Current item */}
      {job.progress?.currentItem && (
        <p className="mt-3 text-xs text-gray-500 dark:text-gray-400 truncate">
          Processing: <span className="font-mono">{job.progress.currentItem}</span>
        </p>
      )}
    </div>
  )
}

export default RunningJobBanner

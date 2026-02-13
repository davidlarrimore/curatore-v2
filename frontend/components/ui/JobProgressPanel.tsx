'use client'

/**
 * Job Progress Panel
 *
 * Unified component for displaying active job progress. Drop it on any page
 * with resourceType + resourceId and it handles everything: auto-show/hide,
 * progress bar, phase label, child jobs, View Job link.
 *
 * Two variants:
 *   - default: Full card for detail pages (rich display)
 *   - compact: Slim banner for list pages (one line per job)
 */

import { ReactNode } from 'react'
import { Loader2, ExternalLink } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useJobProgress, useJobProgressByType } from '@/lib/useJobProgress'
import { JOB_TYPE_CONFIG, JobType } from '@/lib/job-type-config'
import { UnifiedJob } from '@/lib/unified-jobs-context'
import { formatTimeAgo } from '@/lib/date-utils'
import { useAuth } from '@/lib/auth-context'
import { useOrganization } from '@/lib/organization-context'

// Color class mappings (explicit to ensure Tailwind includes them in build)
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
  red: {
    bg: 'bg-red-50 dark:bg-red-900/20',
    border: 'border-red-100 dark:border-red-900/50',
    text: 'text-red-600 dark:text-red-400',
    progressBg: 'bg-red-500',
  },
  gray: {
    bg: 'bg-gray-50 dark:bg-gray-900/20',
    border: 'border-gray-200 dark:border-gray-700',
    text: 'text-gray-600 dark:text-gray-400',
    progressBg: 'bg-gray-500',
  },
}

// ============================================================================
// Resource-scoped panel (detail pages)
// ============================================================================

interface JobProgressPanelProps {
  resourceType: string
  resourceId: string | undefined
  onComplete?: () => void
  variant?: 'default' | 'compact'
  className?: string
  /** Optional: inject page-specific stats below the progress bar */
  renderStats?: (job: UnifiedJob) => ReactNode
}

export function JobProgressPanel({
  resourceType,
  resourceId,
  onComplete,
  variant = 'default',
  className = '',
  renderStats,
}: JobProgressPanelProps) {
  const { jobs, isActive } = useJobProgress(resourceType, resourceId, { onComplete })

  if (!isActive) return null

  return (
    <div className={className}>
      {jobs.map(job => (
        <JobCard key={job.runId} job={job} variant={variant} renderStats={renderStats} />
      ))}
    </div>
  )
}

// ============================================================================
// Type-scoped panel (list pages — renders per-resource)
// ============================================================================

interface JobProgressPanelByTypeProps {
  jobType: JobType
  /** Filter to a specific resource */
  resourceId?: string
  onComplete?: () => void
  variant?: 'default' | 'compact'
  className?: string
}

export function JobProgressPanelByType({
  jobType,
  resourceId,
  onComplete,
  variant = 'compact',
  className = '',
}: JobProgressPanelByTypeProps) {
  const { jobs } = useJobProgressByType(jobType, { onComplete })

  const filtered = resourceId
    ? jobs.filter(j => j.resourceId === resourceId)
    : jobs

  if (filtered.length === 0) return null

  return (
    <div className={className}>
      {filtered.map(job => (
        <JobCard key={job.runId} job={job} variant={variant} />
      ))}
    </div>
  )
}

// ============================================================================
// Internal: Job Card rendering
// ============================================================================

interface JobCardProps {
  job: UnifiedJob
  variant: 'default' | 'compact'
  renderStats?: (job: UnifiedJob) => ReactNode
}

function JobCard({ job, variant, renderStats }: JobCardProps) {
  const pathname = usePathname()
  const { isAdmin } = useAuth()
  const { mode, currentOrganization } = useOrganization()

  // Determine if we're in system mode
  const isSystemMode = isAdmin && mode === 'system'

  // Get org slug from URL or context
  const orgSlugMatch = pathname?.match(/^\/orgs\/([^\/]+)/)
  const urlOrgSlug = orgSlugMatch ? orgSlugMatch[1] : null
  const activeOrgSlug = urlOrgSlug || currentOrganization?.slug

  // Build job detail URL - requires org context
  const getJobUrl = (runId: string) => {
    if (isSystemMode) {
      return `/system/jobs/${runId}`
    }
    if (activeOrgSlug) {
      return `/orgs/${activeOrgSlug}/jobs/${runId}`
    }
    // No org context - link to org selection
    return '/orgs'
  }

  const jobType = job.jobType as JobType
  const config = JOB_TYPE_CONFIG[jobType]

  // Fallback for unknown job types (e.g. deletion)
  if (!config) return null

  const Icon = config.icon
  const colors = colorClasses[config.color] || colorClasses.blue

  // Calculate progress percentage
  const progressPercent =
    job.progress?.total && job.progress?.current
      ? Math.round((job.progress.current / job.progress.total) * 100)
      : job.progress?.percent ?? null

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

  // ── Compact variant ──────────────────────────────────────────────────
  if (variant === 'compact') {
    return (
      <div className={`flex items-center gap-3 px-4 py-2 rounded-lg ${colors.bg} border ${colors.border}`}>
        <Loader2 className={`w-4 h-4 animate-spin ${colors.text}`} />
        <Icon className={`w-4 h-4 ${colors.text}`} />
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300 truncate">
          {config.label}: {job.displayName}
        </span>
        {job.progress?.phase && (
          <span className="text-xs text-gray-500 dark:text-gray-400 capitalize hidden sm:inline">
            {job.progress.phase}
          </span>
        )}
        {progressPercent !== null && (
          <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
            {progressPercent}%
          </span>
        )}
        {job.progress?.current !== undefined && job.progress?.total !== undefined && (
          <span className="text-xs text-gray-500 dark:text-gray-400 hidden md:inline">
            {job.progress.current}/{job.progress.total}
          </span>
        )}
        <Link
          href={getJobUrl(job.runId)}
          className={`text-xs ${colors.text} hover:underline ml-auto flex-shrink-0`}
        >
          View Job
        </Link>
      </div>
    )
  }

  // ── Default variant ──────────────────────────────────────────────────
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
              {progressPercent !== null && (
                <span className="text-sm font-medium text-gray-500 dark:text-gray-400">
                  {progressPercent}%
                </span>
              )}
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
          href={getJobUrl(job.runId)}
          className={`flex items-center gap-1 text-sm ${colors.text} hover:underline flex-shrink-0`}
        >
          View Job
          <ExternalLink className="w-3.5 h-3.5" />
        </Link>
      </div>

      {/* Progress bar */}
      {progressPercent !== null && (
        <div className="mt-4">
          <div className="flex items-center justify-between text-xs text-gray-600 dark:text-gray-400 mb-1">
            <span>
              {job.progress?.current !== undefined && job.progress?.total !== undefined
                ? `${job.progress.current.toLocaleString()} / ${job.progress.total.toLocaleString()} items`
                : ''}
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

      {/* Current item */}
      {job.progress?.currentItem && (
        <p className="mt-3 text-xs text-gray-500 dark:text-gray-400 truncate">
          Processing: <span className="font-mono">{job.progress.currentItem}</span>
        </p>
      )}

      {/* Child jobs grid */}
      {config.hasChildJobs && job.progress?.childJobsTotal !== undefined && (
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
      {childJobsPercent !== null && childJobsPercent < 100 && (
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

      {/* Optional page-specific stats */}
      {renderStats && renderStats(job)}
    </div>
  )
}

export default JobProgressPanel

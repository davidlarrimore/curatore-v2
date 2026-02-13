'use client'

import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { useQueue } from '@/lib/context-shims'
import {
  queueAdminApi,
  type ActiveJob,
  type QueueDefinition,
  type QueueRegistryResponse,
  type ChildJobStats,
} from '@/lib/api'
import { formatDateTime, formatTimeAgo, formatShortDateTime } from '@/lib/date-utils'
import { Button } from '@/components/ui/Button'
import { ExtractionStatus } from '@/components/ui/ExtractionStatus'
import {
  RefreshCw,
  Activity,
  Clock,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Loader2,
  ArrowUp,
  Trash2,
  Settings,
  FileText,
  Zap,
  Timer,
  TrendingUp,
  Filter,
  CheckSquare,
  Square,
  Upload,
  Globe,
  Building2,
  FolderSync,
  Wrench,
  RotateCcw,
  Eye,
  Search,
  History,
  Sparkles,
  Workflow,
  GitBranch,
  Database,
} from 'lucide-react'
import ProtectedRoute from '@/components/auth/ProtectedRoute'

export default function JobManagerPage() {
  return (
    <ProtectedRoute>
      <JobManagerContent />
    </ProtectedRoute>
  )
}

// Job type filter options with icons
const JOB_TYPE_TABS = [
  { value: 'all', label: 'All', icon: Activity },
  { value: 'extraction', label: 'Extraction', icon: FileText },
  { value: 'sam_pull', label: 'SAM.gov', icon: Building2 },
  { value: 'scrape', label: 'Web Scrape', icon: Globe },
  { value: 'sharepoint', label: 'SharePoint', icon: FolderSync },
  { value: 'salesforce', label: 'Salesforce', icon: Database },
  { value: 'procedure', label: 'Procedures', icon: Workflow },
  { value: 'pipeline', label: 'Pipelines', icon: GitBranch },
  { value: 'system_maintenance', label: 'Maintenance', icon: Wrench },
]

// Map run_type to parent queue type for filtering
function getQueueType(runType: string): string {
  if (runType.startsWith('sharepoint')) return 'sharepoint'
  if (runType.startsWith('salesforce')) return 'salesforce'
  if (runType === 'sam_pull') return 'sam_pull'
  if (runType === 'extraction_enhancement') return 'extraction'
  if (runType === 'procedure' || runType === 'procedure_run') return 'procedure'
  if (runType === 'pipeline' || runType === 'pipeline_run') return 'pipeline'
  return runType
}

// Status filter type
type StatusFilter = 'all' | 'pending' | 'submitted' | 'running' | 'stale' | 'completed' | 'failed' | 'timed_out'

// Helper to get icon component for a run type
function getJobTypeIcon(runType: string): React.ComponentType<{ className?: string }> {
  const queueType = getQueueType(runType)
  const tab = JOB_TYPE_TABS.find(t => t.value === queueType)
  return tab?.icon || Activity
}

// Helper to get color for a run type
function getJobTypeColor(runType: string): string {
  const queueType = getQueueType(runType)
  switch (queueType) {
    case 'extraction': return 'blue'
    case 'sam_pull': return 'amber'
    case 'scrape': return 'emerald'
    case 'sharepoint': return 'purple'
    case 'salesforce': return 'cyan'
    case 'procedure': return 'teal'
    case 'pipeline': return 'indigo'
    case 'system_maintenance': return 'gray'
    default: return 'gray'
  }
}

// Helper to get status badge classes
function getStatusClasses(status: string): string {
  switch (status) {
    case 'pending':
      return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
    case 'submitted':
      return 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400'
    case 'running':
      return 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400'
    case 'stale':
      return 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400'
    case 'completed':
      return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
    case 'failed':
      return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
    case 'timed_out':
      return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
    case 'cancelled':
      return 'bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-400'
    default:
      return 'bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-400'
  }
}

// Check if a date is within the last 24 hours
function isWithin24Hours(dateStr: string): boolean {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  return diff < 24 * 60 * 60 * 1000
}

// Child job stats component for parent jobs
function ChildJobStatsDisplay({ stats }: { stats: ChildJobStats }) {
  const active = stats.pending + stats.submitted + stats.running
  const done = stats.completed + stats.failed + stats.cancelled + stats.timed_out
  const hasIssues = stats.failed > 0 || stats.timed_out > 0

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-gray-500 dark:text-gray-400">Children:</span>
      {stats.running > 0 && (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400">
          <Loader2 className="w-3 h-3 animate-spin" />
          {stats.running}
        </span>
      )}
      {(stats.pending + stats.submitted) > 0 && (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400">
          <Clock className="w-3 h-3" />
          {stats.pending + stats.submitted}
        </span>
      )}
      {stats.completed > 0 && (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">
          <CheckCircle className="w-3 h-3" />
          {stats.completed}
        </span>
      )}
      {hasIssues && (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400">
          <XCircle className="w-3 h-3" />
          {stats.failed + stats.timed_out}
        </span>
      )}
      <span className="text-gray-400 dark:text-gray-500">
        ({done}/{stats.total})
      </span>
    </div>
  )
}

function JobManagerContent() {
  const router = useRouter()
  const { token } = useAuth()
  const { stats: queueStats, isLoading: queueLoading, refresh: refreshQueue } = useQueue()

  const [registry, setRegistry] = useState<QueueRegistryResponse | null>(null)
  const [allJobs, setAllJobs] = useState<ActiveJob[]>([]) // All jobs for stats
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  // Filters
  const [queueFilter, setQueueFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [searchQuery, setSearchQuery] = useState('')

  // Selection for bulk operations
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [isBulkCancelling, setIsBulkCancelling] = useState(false)

  // Actions in progress
  const [cancellingIds, setCancellingIds] = useState<Set<string>>(new Set())
  const [forceKillingIds, setForceKillingIds] = useState<Set<string>>(new Set())

  // Request ID to prevent stale responses
  const requestIdRef = useRef(0)

  // Load all jobs for accurate stats
  const loadData = useCallback(async (silent = false) => {
    if (!token) return

    const thisRequestId = ++requestIdRef.current

    if (!silent) {
      setIsLoading(true)
    }
    setError('')

    try {
      const [registryData, jobsData] = await Promise.all([
        queueAdminApi.getRegistry(token),
        queueAdminApi.listJobs(token, {
          include_completed: true,
          limit: 500,
        }),
      ])

      if (thisRequestId !== requestIdRef.current) {
        return
      }

      setRegistry(registryData)
      setAllJobs(jobsData.items)
      setSelectedIds(new Set())
    } catch (err: any) {
      if (thisRequestId === requestIdRef.current && !silent) {
        setError(err.message || 'Failed to load job data')
      }
    } finally {
      if (thisRequestId === requestIdRef.current) {
        if (!silent) {
          setIsLoading(false)
        }
        setIsRefreshing(false)
      }
    }
  }, [token])

  // Initial load
  useEffect(() => {
    if (token) {
      loadData()
    }
  }, [token, loadData])

  // Auto-refresh every 5 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      if (!isLoading && !isRefreshing) {
        loadData(true)
      }
    }, 5000)

    return () => clearInterval(interval)
  }, [isLoading, isRefreshing, loadData])

  // Manual refresh
  const handleRefresh = async () => {
    setIsRefreshing(true)
    await Promise.all([loadData(), refreshQueue()])
  }

  // Compute stats for queue tabs (active jobs only: pending + submitted + running + stale)
  const queueStats24h = useMemo(() => {
    const stats: Record<string, number> = { all: 0 }

    for (const job of allJobs) {
      const isActive = ['pending', 'submitted', 'running', 'stale'].includes(job.status)
      if (isActive) {
        stats.all++
        const queueType = getQueueType(job.run_type)
        stats[queueType] = (stats[queueType] || 0) + 1
      }
    }

    return stats
  }, [allJobs])

  // Compute status stats - active for pending/submitted/running/stale, 24h for completed/failed/timed_out
  const statusStats = useMemo(() => {
    const stats = {
      pending: 0,
      submitted: 0,
      running: 0,
      stale: 0,
      completed24h: 0,
      failed24h: 0,
      timedOut24h: 0,
    }

    // Filter by queue first if selected
    const jobsInQueue = queueFilter === 'all'
      ? allJobs
      : allJobs.filter(j => getQueueType(j.run_type) === queueFilter)

    for (const job of jobsInQueue) {
      if (job.status === 'pending') stats.pending++
      else if (job.status === 'submitted') stats.submitted++
      else if (job.status === 'running') stats.running++
      else if (job.status === 'stale') stats.stale++
      else if (job.status === 'completed') {
        if (job.completed_at && isWithin24Hours(job.completed_at)) {
          stats.completed24h++
        }
      }
      else if (job.status === 'failed') {
        if (job.completed_at && isWithin24Hours(job.completed_at)) {
          stats.failed24h++
        }
      }
      else if (job.status === 'timed_out') {
        if (job.completed_at && isWithin24Hours(job.completed_at)) {
          stats.timedOut24h++
        }
      }
    }

    return stats
  }, [allJobs, queueFilter])

  // Filter jobs based on queue and status filters
  const filteredJobs = useMemo(() => {
    let result = [...allJobs]

    // Filter by queue type
    if (queueFilter !== 'all') {
      result = result.filter(j => getQueueType(j.run_type) === queueFilter)
    }

    // Filter by status
    if (statusFilter !== 'all') {
      result = result.filter(j => j.status === statusFilter)
    }

    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase()
      result = result.filter(job => {
        return (
          job.display_name.toLowerCase().includes(query) ||
          job.run_type.toLowerCase().includes(query) ||
          job.status.toLowerCase().includes(query) ||
          (job.display_context && job.display_context.toLowerCase().includes(query)) ||
          (job.filename && job.filename.toLowerCase().includes(query))
        )
      })
    }

    // Sort by created_at descending (most recent first)
    result.sort((a, b) => {
      const aTime = a.created_at || ''
      const bTime = b.created_at || ''
      return bTime.localeCompare(aTime)
    })

    return result
  }, [allJobs, queueFilter, statusFilter, searchQuery])

  // Handle queue filter change
  const handleQueueChange = (value: string) => {
    setQueueFilter(value)
    setSelectedIds(new Set())
  }

  // Handle status filter change
  const handleStatusChange = (value: StatusFilter) => {
    setStatusFilter(value)
    setSelectedIds(new Set())
  }

  // Selection handlers
  const toggleSelectAll = () => {
    if (selectedIds.size === filteredJobs.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(filteredJobs.map(j => j.run_id)))
    }
  }

  const toggleSelect = (runId: string) => {
    const newSelected = new Set(selectedIds)
    if (newSelected.has(runId)) {
      newSelected.delete(runId)
    } else {
      newSelected.add(runId)
    }
    setSelectedIds(newSelected)
  }

  // Get cancellable selected items
  const cancellableSelectedIds = Array.from(selectedIds).filter(id => {
    const job = allJobs.find(j => j.run_id === id)
    return job && job.can_cancel
  })

  // Cancel job
  const handleCancel = async (runId: string) => {
    if (!token) return
    if (!confirm('Cancel this job?')) return

    setCancellingIds(prev => new Set(prev).add(runId))
    try {
      await queueAdminApi.cancelJob(token, runId)
      setSuccessMessage('Job cancelled')
      await loadData(true)
      setTimeout(() => setSuccessMessage(''), 3000)
    } catch (err: any) {
      setError(err.message || 'Failed to cancel job')
      setTimeout(() => setError(''), 5000)
    } finally {
      setCancellingIds(prev => {
        const next = new Set(prev)
        next.delete(runId)
        return next
      })
    }
  }

  // Force kill a stuck job
  const handleForceKill = async (runId: string) => {
    if (!token) return
    if (!confirm('Force kill this job? This will terminate database connections and revoke the Celery task. Use this only for stuck jobs that cannot be cancelled normally.')) return

    setForceKillingIds(prev => new Set(prev).add(runId))
    try {
      await queueAdminApi.forceKillJob(token, runId)
      setSuccessMessage('Job force-killed')
      await loadData(true)
      setTimeout(() => setSuccessMessage(''), 3000)
    } catch (err: any) {
      setError(err.message || 'Failed to force kill job')
      setTimeout(() => setError(''), 5000)
    } finally {
      setForceKillingIds(prev => {
        const next = new Set(prev)
        next.delete(runId)
        return next
      })
    }
  }

  // Bulk cancel jobs
  const handleBulkCancel = async () => {
    if (!token || cancellableSelectedIds.length === 0) return
    if (!confirm(`Cancel ${cancellableSelectedIds.length} job(s)?`)) return

    setIsBulkCancelling(true)
    let successCount = 0
    let failCount = 0

    for (const runId of cancellableSelectedIds) {
      try {
        await queueAdminApi.cancelJob(token, runId)
        successCount++
      } catch {
        failCount++
      }
    }

    if (successCount > 0) {
      setSuccessMessage(`Cancelled ${successCount} job(s)`)
    }
    if (failCount > 0) {
      setError(`Failed to cancel ${failCount} job(s)`)
    }

    setSelectedIds(new Set())
    await loadData(true)
    setIsBulkCancelling(false)
    setTimeout(() => setSuccessMessage(''), 3000)
    setTimeout(() => setError(''), 5000)
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin"></div>
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading job data...</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-start gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25 flex-shrink-0">
                <Activity className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  Job Manager
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  Monitor and manage all background jobs
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                onClick={handleRefresh}
                disabled={isRefreshing}
                className="gap-2"
              >
                <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
            </div>
          </div>

          {/* Success Message */}
          {successMessage && (
            <div className="mt-6 rounded-xl bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-100 dark:border-emerald-900/50 p-4">
              <div className="flex items-center gap-3">
                <CheckCircle className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                <p className="text-sm font-medium text-emerald-800 dark:text-emerald-200">{successMessage}</p>
              </div>
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div className="mt-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
              <div className="flex items-center gap-3">
                <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
                <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
              </div>
            </div>
          )}
        </div>

        {/* Queue Type Tabs */}
        <div className="mb-6">
          <div className="flex flex-wrap gap-2">
            {JOB_TYPE_TABS.map((tab) => {
              const Icon = tab.icon
              const isActive = queueFilter === tab.value
              const count = queueStats24h[tab.value] || 0

              return (
                <button
                  key={tab.value}
                  onClick={() => handleQueueChange(tab.value)}
                  className={`
                    flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors
                    ${isActive
                      ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400'
                      : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 border border-gray-200 dark:border-gray-700'
                    }
                  `}
                >
                  <Icon className="w-4 h-4" />
                  {tab.label}
                  {count > 0 && (
                    <span className={`
                      px-1.5 py-0.5 rounded-full text-xs
                      ${isActive
                        ? 'bg-indigo-200 dark:bg-indigo-800'
                        : 'bg-gray-100 dark:bg-gray-700'
                      }
                    `}>
                      {count}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        </div>

        {/* Status Filter Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
          {/* Pending */}
          <button
            onClick={() => handleStatusChange(statusFilter === 'pending' ? 'all' : 'pending')}
            className={`bg-white dark:bg-gray-800 rounded-xl border-2 p-4 transition-all ${
              statusFilter === 'pending'
                ? 'border-blue-500 ring-2 ring-blue-500/20'
                : 'border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-700'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
                <Clock className="w-5 h-5 text-blue-600 dark:text-blue-400" />
              </div>
              <div className="text-left">
                <p className="text-xs text-gray-500 dark:text-gray-400">Pending</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{statusStats.pending}</p>
              </div>
            </div>
          </button>

          {/* Submitted */}
          <button
            onClick={() => handleStatusChange(statusFilter === 'submitted' ? 'all' : 'submitted')}
            className={`bg-white dark:bg-gray-800 rounded-xl border-2 p-4 transition-all ${
              statusFilter === 'submitted'
                ? 'border-indigo-500 ring-2 ring-indigo-500/20'
                : 'border-gray-200 dark:border-gray-700 hover:border-indigo-300 dark:hover:border-indigo-700'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-indigo-50 dark:bg-indigo-900/20 flex items-center justify-center">
                <Zap className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
              </div>
              <div className="text-left">
                <p className="text-xs text-gray-500 dark:text-gray-400">Submitted</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{statusStats.submitted}</p>
              </div>
            </div>
          </button>

          {/* Running */}
          <button
            onClick={() => handleStatusChange(statusFilter === 'running' ? 'all' : 'running')}
            className={`bg-white dark:bg-gray-800 rounded-xl border-2 p-4 transition-all ${
              statusFilter === 'running'
                ? 'border-purple-500 ring-2 ring-purple-500/20'
                : 'border-gray-200 dark:border-gray-700 hover:border-purple-300 dark:hover:border-purple-700'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-purple-50 dark:bg-purple-900/20 flex items-center justify-center">
                <Loader2 className={`w-5 h-5 text-purple-600 dark:text-purple-400 ${statusStats.running > 0 ? 'animate-spin' : ''}`} />
              </div>
              <div className="text-left">
                <p className="text-xs text-gray-500 dark:text-gray-400">Running</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{statusStats.running}</p>
              </div>
            </div>
          </button>

          {/* Stale (may be stuck) */}
          {statusStats.stale > 0 && (
            <button
              onClick={() => handleStatusChange(statusFilter === 'stale' ? 'all' : 'stale')}
              className={`bg-white dark:bg-gray-800 rounded-xl border-2 p-4 transition-all ${
                statusFilter === 'stale'
                  ? 'border-orange-500 ring-2 ring-orange-500/20'
                  : 'border-gray-200 dark:border-gray-700 hover:border-orange-300 dark:hover:border-orange-700'
              }`}
            >
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-orange-50 dark:bg-orange-900/20 flex items-center justify-center">
                  <AlertTriangle className="w-5 h-5 text-orange-600 dark:text-orange-400" />
                </div>
                <div className="text-left">
                  <p className="text-xs text-gray-500 dark:text-gray-400">Stale</p>
                  <p className="text-xl font-bold text-orange-600 dark:text-orange-400">{statusStats.stale}</p>
                </div>
              </div>
            </button>
          )}

          {/* Completed (24h) */}
          <button
            onClick={() => handleStatusChange(statusFilter === 'completed' ? 'all' : 'completed')}
            className={`bg-white dark:bg-gray-800 rounded-xl border-2 p-4 transition-all ${
              statusFilter === 'completed'
                ? 'border-emerald-500 ring-2 ring-emerald-500/20'
                : 'border-gray-200 dark:border-gray-700 hover:border-emerald-300 dark:hover:border-emerald-700'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center">
                <CheckCircle className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
              </div>
              <div className="text-left">
                <p className="text-xs text-gray-500 dark:text-gray-400">Completed <span className="text-[10px]">(24h)</span></p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{statusStats.completed24h}</p>
              </div>
            </div>
          </button>

          {/* Failed (24h) */}
          <button
            onClick={() => handleStatusChange(statusFilter === 'failed' ? 'all' : 'failed')}
            className={`bg-white dark:bg-gray-800 rounded-xl border-2 p-4 transition-all ${
              statusFilter === 'failed'
                ? 'border-red-500 ring-2 ring-red-500/20'
                : 'border-gray-200 dark:border-gray-700 hover:border-red-300 dark:hover:border-red-700'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-red-50 dark:bg-red-900/20 flex items-center justify-center">
                <XCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
              </div>
              <div className="text-left">
                <p className="text-xs text-gray-500 dark:text-gray-400">Failed <span className="text-[10px]">(24h)</span></p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{statusStats.failed24h}</p>
              </div>
            </div>
          </button>

          {/* Timed Out (24h) */}
          <button
            onClick={() => handleStatusChange(statusFilter === 'timed_out' ? 'all' : 'timed_out')}
            className={`bg-white dark:bg-gray-800 rounded-xl border-2 p-4 transition-all ${
              statusFilter === 'timed_out'
                ? 'border-amber-500 ring-2 ring-amber-500/20'
                : 'border-gray-200 dark:border-gray-700 hover:border-amber-300 dark:hover:border-amber-700'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center">
                <Timer className="w-5 h-5 text-amber-600 dark:text-amber-400" />
              </div>
              <div className="text-left">
                <p className="text-xs text-gray-500 dark:text-gray-400">Timed Out <span className="text-[10px]">(24h)</span></p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{statusStats.timedOut24h}</p>
              </div>
            </div>
          </button>
        </div>

        {/* Active Filters Display */}
        {(queueFilter !== 'all' || statusFilter !== 'all') && (
          <div className="mb-4 flex items-center gap-2 flex-wrap">
            <span className="text-sm text-gray-500 dark:text-gray-400">Filters:</span>
            {queueFilter !== 'all' && (
              <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400">
                {JOB_TYPE_TABS.find(t => t.value === queueFilter)?.label}
                <button onClick={() => handleQueueChange('all')} className="ml-1 hover:text-indigo-900 dark:hover:text-indigo-200">×</button>
              </span>
            )}
            {statusFilter !== 'all' && (
              <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${getStatusClasses(statusFilter)}`}>
                {statusFilter.replace('_', ' ')}
                <button onClick={() => handleStatusChange('all')} className="ml-1 hover:opacity-70">×</button>
              </span>
            )}
            <button
              onClick={() => { handleQueueChange('all'); handleStatusChange('all'); }}
              className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
            >
              Clear all
            </button>
          </div>
        )}

        {/* Jobs Table */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Jobs
                </h2>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  {filteredJobs.length} job{filteredJobs.length !== 1 ? 's' : ''}
                </p>
              </div>

              <div className="flex items-center gap-3">
                {/* Search */}
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Search jobs..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-9 pr-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>

                {/* Bulk actions */}
                {selectedIds.size > 0 && (
                  <div className="flex items-center gap-3">
                    <span className="text-sm text-gray-500 dark:text-gray-400">
                      {selectedIds.size} selected
                    </span>
                    {cancellableSelectedIds.length > 0 && (
                      <Button
                        variant="secondary"
                        onClick={handleBulkCancel}
                        disabled={isBulkCancelling}
                        className="gap-2 text-red-600 dark:text-red-400 border-red-200 dark:border-red-800 hover:bg-red-50 dark:hover:bg-red-900/20"
                      >
                        {isBulkCancelling ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Trash2 className="w-4 h-4" />
                        )}
                        Cancel {cancellableSelectedIds.length}
                      </Button>
                    )}
                    <button
                      onClick={() => setSelectedIds(new Set())}
                      className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
                    >
                      Clear
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>

          {filteredJobs.length === 0 ? (
            <div className="p-12 text-center">
              <Activity className="w-12 h-12 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
              <p className="text-gray-500 dark:text-gray-400">No jobs found</p>
              <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">
                {searchQuery ? 'Try adjusting your search' : 'No jobs match the current filters'}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700">
                    <th className="px-4 py-3 w-10">
                      <button
                        onClick={toggleSelectAll}
                        className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
                        title={selectedIds.size === filteredJobs.length ? 'Deselect all' : 'Select all'}
                      >
                        {selectedIds.size === filteredJobs.length && filteredJobs.length > 0 ? (
                          <CheckSquare className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                        ) : (
                          <Square className="w-4 h-4 text-gray-400" />
                        )}
                      </button>
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Type
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Name / Details
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Created
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {filteredJobs.map((job) => {
                    const Icon = getJobTypeIcon(job.run_type)
                    const color = getJobTypeColor(job.run_type)

                    return (
                      <tr
                        key={job.run_id}
                        onClick={() => router.push(`/admin/queue/${job.run_id}`)}
                        className={`hover:bg-gray-50 dark:hover:bg-gray-900/30 transition-colors cursor-pointer ${
                          selectedIds.has(job.run_id) ? 'bg-indigo-50 dark:bg-indigo-900/10' : ''
                        }`}
                      >
                        <td className="px-4 py-4 w-10" onClick={(e) => e.stopPropagation()}>
                          <button
                            onClick={() => toggleSelect(job.run_id)}
                            className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
                          >
                            {selectedIds.has(job.run_id) ? (
                              <CheckSquare className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                            ) : (
                              <Square className="w-4 h-4 text-gray-400" />
                            )}
                          </button>
                        </td>
                        <td className="px-4 py-4">
                          <div className={`
                            inline-flex items-center gap-2 px-2.5 py-1 rounded-lg text-xs font-medium
                            bg-${color}-50 text-${color}-700 dark:bg-${color}-900/20 dark:text-${color}-400
                          `}>
                            <Icon className="w-3.5 h-3.5" />
                            {JOB_TYPE_TABS.find(t => t.value === getQueueType(job.run_type))?.label || job.run_type}
                          </div>
                        </td>
                        <td className="px-4 py-4" onClick={(e) => e.stopPropagation()}>
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              {job.run_type === 'extraction' && job.asset_id ? (
                                <Link
                                  href={`/assets/${job.asset_id}`}
                                  className="text-sm font-medium text-gray-900 dark:text-white hover:text-indigo-600 dark:hover:text-indigo-400 truncate block max-w-[250px]"
                                >
                                  {job.display_name}
                                </Link>
                              ) : (
                                <span className="text-sm font-medium text-gray-900 dark:text-white truncate block max-w-[250px]">
                                  {job.display_name}
                                </span>
                              )}
                              {job.is_parent_job && (
                                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400">
                                  <GitBranch className="w-3 h-3" />
                                  Parent
                                </span>
                              )}
                              {job.parent_run_id && (
                                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 dark:bg-gray-900/30 text-gray-600 dark:text-gray-400">
                                  Child
                                </span>
                              )}
                            </div>
                            {job.display_context && (
                              <p className="text-xs text-gray-500 dark:text-gray-400 font-mono">
                                {job.display_context}
                              </p>
                            )}
                            {job.is_parent_job && job.child_stats && job.child_stats.total > 0 && (
                              <div className="mt-1">
                                <ChildJobStatsDisplay stats={job.child_stats} />
                              </div>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-4">
                          <div className="flex items-center gap-2">
                            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${getStatusClasses(job.status)}`}>
                              {job.status === 'running' && <Loader2 className="w-3 h-3 animate-spin" />}
                              {job.status === 'pending' && <Clock className="w-3 h-3" />}
                              {job.status === 'stale' && <AlertTriangle className="w-3 h-3" />}
                              {job.status === 'completed' && <CheckCircle className="w-3 h-3" />}
                              {job.status === 'failed' && <XCircle className="w-3 h-3" />}
                              {job.status === 'timed_out' && <Timer className="w-3 h-3" />}
                              {job.status}
                            </span>
                            {job.queue_position && job.status === 'pending' && (
                              <span className="text-xs text-gray-400">#{job.queue_position}</span>
                            )}
                            {job.queue_priority > 0 && (
                              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400">
                                <ArrowUp className="w-3 h-3" />
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-4">
                          <span className="text-xs text-gray-500 dark:text-gray-400">
                            {formatShortDateTime(job.created_at)}
                          </span>
                        </td>
                        <td className="px-4 py-4 text-right" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-end gap-2">
                            {job.can_cancel && (
                              <button
                                onClick={() => handleCancel(job.run_id)}
                                disabled={cancellingIds.has(job.run_id)}
                                className="p-1.5 rounded-lg text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors disabled:opacity-50"
                                title="Cancel job"
                              >
                                {cancellingIds.has(job.run_id) ? (
                                  <Loader2 className="w-4 h-4 animate-spin" />
                                ) : (
                                  <XCircle className="w-4 h-4" />
                                )}
                              </button>
                            )}
                            {['pending', 'submitted', 'running', 'stale'].includes(job.status) && (
                              <button
                                onClick={() => handleForceKill(job.run_id)}
                                disabled={forceKillingIds.has(job.run_id)}
                                className="p-1.5 rounded-lg text-orange-600 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-900/20 transition-colors disabled:opacity-50"
                                title="Force kill job"
                              >
                                {forceKillingIds.has(job.run_id) ? (
                                  <Loader2 className="w-4 h-4 animate-spin" />
                                ) : (
                                  <Zap className="w-4 h-4" />
                                )}
                              </button>
                            )}
                            {job.run_type === 'extraction' && job.asset_id && (
                              <Link
                                href={`/assets/${job.asset_id}`}
                                className="p-1.5 rounded-lg text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors"
                                title="View asset"
                              >
                                <FileText className="w-4 h-4" />
                              </Link>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Queue Registry Info */}
        {registry && (
          <div className="mt-8 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              Queue Configuration
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
              {Object.entries(registry.queues)
                .filter(([_, q]) => q.enabled)
                .map(([queueType, queue]) => (
                <div
                  key={queueType}
                  className="p-4 rounded-lg bg-gray-50 dark:bg-gray-900/50"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-sm font-medium text-gray-900 dark:text-white">
                      {queue.label}
                    </span>
                  </div>
                  <div className="space-y-1 text-xs text-gray-500 dark:text-gray-400">
                    <p>Max concurrent: {queue.max_concurrent ?? 'Unlimited'}</p>
                    <p>Timeout: {queue.timeout_seconds}s</p>
                    <div className="flex gap-2 mt-2">
                      {queue.can_cancel && (
                        <span className="px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700">Cancel</span>
                      )}
                      {queue.can_retry && (
                        <span className="px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700">Retry</span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

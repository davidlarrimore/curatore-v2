'use client'

import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '@/lib/auth-context'
import { useActiveJobs } from '@/lib/context-shims'
import { JobProgressPanelByType } from '@/components/ui/JobProgressPanel'
import { useJobProgressByType } from '@/lib/useJobProgress'
import { scheduledTasksApi, ScheduledTask, MaintenanceStats, TaskRun } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { formatDateTime } from '@/lib/date-utils'
import {
  Wrench,
  Calendar,
  Clock,
  Play,
  Pause,
  RefreshCw,
  CheckCircle,
  XCircle,
  AlertCircle,
  Loader2,
  ChevronDown,
  ChevronRight,
  Timer,
  Search,
  Activity,
  Shield,
  FileCheck,
} from 'lucide-react'

interface SystemMaintenanceTabProps {
  onError?: (message: string) => void
}

// Task type icons
const TASK_TYPE_ICONS: Record<string, React.ReactNode> = {
  'orphan.detect': <Search className="w-4 h-4" />,
  'retention.enforce': <Shield className="w-4 h-4" />,
  'health.report': <Activity className="w-4 h-4" />,
}

// Task type colors
const TASK_TYPE_COLORS: Record<string, string> = {
  'orphan.detect': 'from-amber-500 to-yellow-500',
  'retention.enforce': 'from-blue-500 to-cyan-500',
  'health.report': 'from-emerald-500 to-teal-500',
}

// Default config for search.reindex dialog
interface ReindexConfig {
  force: boolean
  data_sources: string[]
}

const ALL_DATA_SOURCES = [
  { key: 'assets', label: 'Assets', description: 'Documents, uploads, and scraped pages' },
  { key: 'sam', label: 'SAM.gov', description: 'Solicitations and notices' },
  { key: 'salesforce', label: 'Salesforce', description: 'Accounts, contacts, and opportunities' },
  { key: 'forecasts', label: 'Forecasts', description: 'AG, APFS, and State forecasts' },
]

export default function SystemMaintenanceTab({ onError }: SystemMaintenanceTabProps) {
  const { token } = useAuth()
  const { addJob } = useActiveJobs()
  const { isActive: hasRunningTasks } = useJobProgressByType('system_maintenance', {
    onComplete: () => loadData(),
  })
  const [tasks, setTasks] = useState<ScheduledTask[]>([])
  const [stats, setStats] = useState<MaintenanceStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [expandedTask, setExpandedTask] = useState<string | null>(null)
  const [taskRuns, setTaskRuns] = useState<Record<string, TaskRun[]>>({})
  const [loadingRuns, setLoadingRuns] = useState<Record<string, boolean>>({})
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  // Reindex config dialog state
  const [reindexDialogTask, setReindexDialogTask] = useState<ScheduledTask | null>(null)
  const [reindexConfig, setReindexConfig] = useState<ReindexConfig>({
    force: false,
    data_sources: ['assets', 'sam', 'salesforce', 'forecasts'],
  })

  const loadData = useCallback(async () => {
    if (!token) return

    setIsLoading(true)
    try {
      const [tasksData, statsData] = await Promise.all([
        scheduledTasksApi.listTasks(token),
        scheduledTasksApi.getStats(token, 7),
      ])
      setTasks(tasksData.tasks)
      setStats(statsData)
    } catch (err: any) {
      console.error('Failed to load maintenance data:', err)
      onError?.(err.message || 'Failed to load maintenance data')
    } finally {
      setIsLoading(false)
    }
  }, [token, onError])

  useEffect(() => {
    loadData()
  }, [loadData])

  const loadTaskRuns = async (taskId: string) => {
    if (!token) return

    setLoadingRuns(prev => ({ ...prev, [taskId]: true }))
    try {
      const runsData = await scheduledTasksApi.getTaskRuns(token, taskId, 10)
      setTaskRuns(prev => ({ ...prev, [taskId]: runsData.runs }))
    } catch (err: any) {
      console.error('Failed to load task runs:', err)
    } finally {
      setLoadingRuns(prev => ({ ...prev, [taskId]: false }))
    }
  }

  const handleToggleExpand = (taskId: string) => {
    if (expandedTask === taskId) {
      setExpandedTask(null)
    } else {
      setExpandedTask(taskId)
      if (!taskRuns[taskId]) {
        loadTaskRuns(taskId)
      }
    }
  }

  const handleToggleEnabled = async (task: ScheduledTask) => {
    if (!token) return

    setActionLoading(task.id)
    try {
      if (task.enabled) {
        await scheduledTasksApi.disableTask(token, task.id)
      } else {
        await scheduledTasksApi.enableTask(token, task.id)
      }
      await loadData()
    } catch (err: any) {
      console.error('Failed to toggle task:', err)
      onError?.(err.message || 'Failed to toggle task')
    } finally {
      setActionLoading(null)
    }
  }

  const handleTriggerTask = async (task: ScheduledTask) => {
    if (!token) return

    // For search.reindex, show config dialog instead of simple confirm
    if (task.task_type === 'search.reindex') {
      setReindexConfig({
        force: false,
        data_sources: ['assets', 'sam', 'salesforce', 'forecasts'],
      })
      setReindexDialogTask(task)
      return
    }

    if (!confirm(`Are you sure you want to trigger "${task.display_name}" now?`)) return
    await executeTrigger(task)
  }

  const handleReindexConfirm = async () => {
    if (!reindexDialogTask) return
    const overrides: Record<string, any> = {}
    if (reindexConfig.force) overrides.force = true
    if (reindexConfig.data_sources.length < 4) overrides.data_sources = reindexConfig.data_sources
    setReindexDialogTask(null)
    await executeTrigger(reindexDialogTask, Object.keys(overrides).length > 0 ? overrides : undefined)
  }

  const executeTrigger = async (task: ScheduledTask, configOverrides?: Record<string, any>) => {
    if (!token) return

    setActionLoading(task.id)
    try {
      const result = await scheduledTasksApi.triggerTask(token, task.id, configOverrides)
      addJob({
        runId: result.run_id,
        jobType: 'system_maintenance',
        displayName: task.display_name,
        resourceId: task.id,
        resourceType: 'system_maintenance',
      })
      await loadData()
      // Refresh runs for this task and expand to show the new run
      setExpandedTask(task.id)
      await loadTaskRuns(task.id)
    } catch (err: any) {
      console.error('Failed to trigger task:', err)
      onError?.(err.message || 'Failed to trigger task')
    } finally {
      setActionLoading(null)
    }
  }

  const formatRelativeTime = (dateStr: string | null) => {
    if (!dateStr) return 'Never'
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = date.getTime() - now.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMs < 0) {
      const absDiffMins = Math.abs(diffMins)
      const absDiffHours = Math.abs(diffHours)
      const absDiffDays = Math.abs(diffDays)
      if (absDiffMins < 60) return `${absDiffMins}m ago`
      if (absDiffHours < 24) return `${absDiffHours}h ago`
      return `${absDiffDays}d ago`
    }

    if (diffMins < 60) return `in ${diffMins}m`
    if (diffHours < 24) return `in ${diffHours}h`
    return `in ${diffDays}d`
  }

  const getStatusBadge = (status: string | null) => {
    if (!status) return <Badge variant="secondary">Not run</Badge>
    switch (status) {
      case 'success':
      case 'completed':
        return <Badge variant="success"><CheckCircle className="w-3 h-3 mr-1" />Success</Badge>
      case 'failed':
        return <Badge variant="error"><XCircle className="w-3 h-3 mr-1" />Failed</Badge>
      case 'running':
        return <Badge variant="info"><Loader2 className="w-3 h-3 mr-1 animate-spin" />Running</Badge>
      case 'pending':
        return <Badge variant="warning"><Clock className="w-3 h-3 mr-1" />Pending</Badge>
      default:
        return <Badge variant="secondary">{status}</Badge>
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 text-indigo-600 dark:text-indigo-400 animate-spin" />
        <span className="ml-3 text-gray-600 dark:text-gray-400">Loading maintenance data...</span>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
          System Maintenance
        </h2>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          Manage scheduled maintenance tasks and monitor system health operations.
        </p>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {/* Tasks Card */}
          <div className="bg-gray-50 dark:bg-gray-800/50 rounded-xl p-4 border border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white">
                <Calendar className="w-5 h-5" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">{stats.total_tasks}</p>
                <p className="text-sm text-gray-500 dark:text-gray-400">Scheduled Tasks</p>
              </div>
            </div>
            <div className="mt-3 flex items-center gap-4 text-xs">
              <span className="text-emerald-600 dark:text-emerald-400">
                {stats.enabled_tasks} enabled
              </span>
              <span className="text-gray-400 dark:text-gray-500">
                {stats.disabled_tasks} disabled
              </span>
            </div>
          </div>

          {/* Runs Card */}
          <div className="bg-gray-50 dark:bg-gray-800/50 rounded-xl p-4 border border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-500 flex items-center justify-center text-white">
                <Activity className="w-5 h-5" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">{stats.total_runs}</p>
                <p className="text-sm text-gray-500 dark:text-gray-400">Runs (7 days)</p>
              </div>
            </div>
            <div className="mt-3 flex items-center gap-4 text-xs">
              <span className="text-emerald-600 dark:text-emerald-400">
                {stats.successful_runs} success
              </span>
              <span className="text-red-500 dark:text-red-400">
                {stats.failed_runs} failed
              </span>
            </div>
          </div>

          {/* Success Rate Card */}
          <div className="bg-gray-50 dark:bg-gray-800/50 rounded-xl p-4 border border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-3">
              <div className={`w-10 h-10 rounded-lg flex items-center justify-center text-white ${
                stats.success_rate >= 90
                  ? 'bg-gradient-to-br from-emerald-500 to-green-500'
                  : stats.success_rate >= 70
                  ? 'bg-gradient-to-br from-amber-500 to-orange-500'
                  : 'bg-gradient-to-br from-red-500 to-rose-500'
              }`}>
                <CheckCircle className="w-5 h-5" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {stats.success_rate.toFixed(1)}%
                </p>
                <p className="text-sm text-gray-500 dark:text-gray-400">Success Rate</p>
              </div>
            </div>
          </div>

          {/* Last Run Card */}
          <div className="bg-gray-50 dark:bg-gray-800/50 rounded-xl p-4 border border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center text-white">
                <Timer className="w-5 h-5" />
              </div>
              <div>
                <p className="text-base font-semibold text-gray-900 dark:text-white">
                  {stats.last_run_at ? formatRelativeTime(stats.last_run_at) : 'Never'}
                </p>
                <p className="text-sm text-gray-500 dark:text-gray-400">Last Run</p>
              </div>
            </div>
            {stats.last_run_status && (
              <div className="mt-3">
                {getStatusBadge(stats.last_run_status)}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Active maintenance jobs */}
      <JobProgressPanelByType
        jobType="system_maintenance"
        variant="compact"
        className="space-y-2"
      />

      {/* Tasks List */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <Wrench className="w-5 h-5 text-indigo-500" />
            Scheduled Tasks
          </h3>
          <Button variant="secondary" size="sm" onClick={loadData}>
            <RefreshCw className="w-4 h-4 mr-1" />
            Refresh
          </Button>
        </div>

        {tasks.length === 0 ? (
          <div className="text-center py-12 bg-gray-50 dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700">
            <Wrench className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
              No Scheduled Tasks
            </h3>
            <p className="text-gray-500 dark:text-gray-400">
              Run the database seed command to create default maintenance tasks.
            </p>
            <code className="block mt-4 text-sm bg-gray-100 dark:bg-gray-800 px-3 py-2 rounded">
              python -m app.commands.seed --create-admin
            </code>
          </div>
        ) : (
          <div className="space-y-3">
            {tasks.map((task) => (
              <div
                key={task.id}
                className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden transition-all hover:border-gray-300 dark:hover:border-gray-600"
              >
                {/* Task Header */}
                <div className="p-4">
                  <div className="flex items-center gap-4">
                    {/* Task Icon */}
                    <div className={`w-10 h-10 rounded-lg bg-gradient-to-br ${TASK_TYPE_COLORS[task.task_type] || 'from-gray-500 to-gray-600'} flex items-center justify-center text-white`}>
                      {TASK_TYPE_ICONS[task.task_type] || <Wrench className="w-5 h-5" />}
                    </div>

                    {/* Task Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h4 className="font-medium text-gray-900 dark:text-white truncate">
                          {task.display_name}
                        </h4>
                        <Badge variant={task.enabled ? 'success' : 'secondary'}>
                          {task.enabled ? 'Enabled' : 'Disabled'}
                        </Badge>
                        {task.scope_type === 'global' && (
                          <Badge variant="info">Global</Badge>
                        )}
                      </div>
                      <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                        {task.schedule_description} | Last run: {task.last_run_at ? formatRelativeTime(task.last_run_at) : 'Never'}
                      </p>
                    </div>

                    {/* Status Badge */}
                    <div className="flex items-center gap-2">
                      {task.last_run_status && getStatusBadge(task.last_run_status)}
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => handleToggleEnabled(task)}
                        disabled={actionLoading === task.id}
                      >
                        {actionLoading === task.id ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : task.enabled ? (
                          <Pause className="w-4 h-4" />
                        ) : (
                          <Play className="w-4 h-4" />
                        )}
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => handleTriggerTask(task)}
                        disabled={actionLoading === task.id}
                        title="Run now"
                      >
                        {actionLoading === task.id ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Play className="w-4 h-4 text-emerald-500" />
                        )}
                      </Button>
                      <button
                        onClick={() => handleToggleExpand(task.id)}
                        className="p-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
                      >
                        {expandedTask === task.id ? (
                          <ChevronDown className="w-4 h-4" />
                        ) : (
                          <ChevronRight className="w-4 h-4" />
                        )}
                      </button>
                    </div>
                  </div>
                </div>

                {/* Expanded Details */}
                {expandedTask === task.id && (
                  <div className="border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 p-4">
                    <div className="grid grid-cols-2 gap-4 mb-4">
                      <div>
                        <p className="text-xs text-gray-500 dark:text-gray-400 uppercase font-medium mb-1">Schedule</p>
                        <p className="text-sm text-gray-900 dark:text-white font-mono">{task.schedule_expression}</p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500 dark:text-gray-400 uppercase font-medium mb-1">Next Run</p>
                        <p className="text-sm text-gray-900 dark:text-white">
                          {task.next_run_at ? formatDateTime(task.next_run_at) : 'Not scheduled'}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500 dark:text-gray-400 uppercase font-medium mb-1">Task Type</p>
                        <p className="text-sm text-gray-900 dark:text-white">{task.task_type}</p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500 dark:text-gray-400 uppercase font-medium mb-1">Description</p>
                        <p className="text-sm text-gray-900 dark:text-white">{task.description || 'No description'}</p>
                      </div>
                    </div>

                    {/* Recent Runs */}
                    <div>
                      <h5 className="text-sm font-medium text-gray-900 dark:text-white mb-2">Recent Runs</h5>
                      {loadingRuns[task.id] ? (
                        <div className="flex items-center justify-center py-4">
                          <Loader2 className="w-5 h-5 text-indigo-500 animate-spin" />
                        </div>
                      ) : taskRuns[task.id]?.length > 0 ? (
                        <div className="space-y-2">
                          {taskRuns[task.id].slice(0, 5).map((run) => (
                            <div
                              key={run.id}
                              className="flex items-center justify-between bg-white dark:bg-gray-800 rounded-lg px-3 py-2 border border-gray-200 dark:border-gray-700"
                            >
                              <div className="flex items-center gap-3">
                                {getStatusBadge(run.status)}
                                <span className="text-sm text-gray-600 dark:text-gray-400">
                                  {run.origin === 'scheduled' ? 'Scheduled' : 'Manual'}
                                </span>
                              </div>
                              <div className="text-sm text-gray-500 dark:text-gray-400">
                                {formatDateTime(run.created_at)}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-sm text-gray-500 dark:text-gray-400 py-4 text-center">
                          No runs yet
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Search Reindex Config Dialog */}
      {reindexDialogTask && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/50" onClick={() => setReindexDialogTask(null)} />
          <div className="relative bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 w-full max-w-md mx-4 p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
              Search Index Rebuild
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-5">
              Re-indexes content for full-text and semantic search. Only items that have changed since the last index will be processed unless force rebuild is enabled.
            </p>

            {/* Data Sources */}
            <div className="mb-5">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Data Sources
              </label>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
                Select which content types to include in the rebuild.
              </p>
              <div className="space-y-2">
                {ALL_DATA_SOURCES.map((source) => (
                  <label
                    key={source.key}
                    className="flex items-start gap-3 p-2.5 rounded-lg border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={reindexConfig.data_sources.includes(source.key)}
                      onChange={(e) => {
                        setReindexConfig(prev => ({
                          ...prev,
                          data_sources: e.target.checked
                            ? [...prev.data_sources, source.key]
                            : prev.data_sources.filter(s => s !== source.key),
                        }))
                      }}
                      className="mt-0.5 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                    />
                    <div>
                      <span className="text-sm font-medium text-gray-900 dark:text-white">
                        {source.label}
                      </span>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {source.description}
                      </p>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            {/* Force Rebuild */}
            <div className="mb-6">
              <label className="flex items-start gap-3 p-2.5 rounded-lg border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/20 cursor-pointer transition-colors">
                <input
                  type="checkbox"
                  checked={reindexConfig.force}
                  onChange={(e) => setReindexConfig(prev => ({ ...prev, force: e.target.checked }))}
                  className="mt-0.5 h-4 w-4 rounded border-gray-300 text-amber-600 focus:ring-amber-500"
                />
                <div>
                  <span className="text-sm font-medium text-gray-900 dark:text-white">
                    Force full rebuild
                  </span>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Re-index all items even if they haven&apos;t changed. Use this after updating indexing logic or to fix a corrupted index. Significantly slower on large datasets.
                  </p>
                </div>
              </label>
            </div>

            {/* Actions */}
            <div className="flex justify-end gap-3">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setReindexDialogTask(null)}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={handleReindexConfirm}
                disabled={reindexConfig.data_sources.length === 0}
              >
                <Play className="w-4 h-4 mr-1" />
                Start Rebuild
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

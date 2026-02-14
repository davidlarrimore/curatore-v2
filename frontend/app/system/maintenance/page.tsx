'use client'

/**
 * System Maintenance page.
 *
 * Manage system maintenance tasks — powered by real scheduled task backend.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Wrench,
  Play,
  Clock,
  CheckCircle,
  XCircle,
  AlertTriangle,
  RefreshCw,
  Pause,
  ChevronDown,
  ChevronRight,
  Activity,
  BarChart3,
} from 'lucide-react'
import { scheduledTasksApi, ScheduledTask, MaintenanceStats, TaskRun } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import toast from 'react-hot-toast'

export default function SystemMaintenancePage() {
  const { token } = useAuth()
  const [tasks, setTasks] = useState<ScheduledTask[]>([])
  const [stats, setStats] = useState<MaintenanceStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [triggeringTaskId, setTriggeringTaskId] = useState<string | null>(null)
  const [togglingTaskId, setTogglingTaskId] = useState<string | null>(null)
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null)
  const [taskRuns, setTaskRuns] = useState<Record<string, TaskRun[]>>({})
  const [loadingRuns, setLoadingRuns] = useState<string | null>(null)

  const loadData = useCallback(async () => {
    if (!token) return

    try {
      const [tasksRes, statsRes] = await Promise.all([
        scheduledTasksApi.listTasks(token),
        scheduledTasksApi.getStats(token, 7),
      ])
      setTasks(tasksRes.tasks)
      setStats(statsRes)
    } catch (error) {
      console.error('Failed to load maintenance data:', error)
      toast.error('Failed to load maintenance tasks')
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [token])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleRefresh = () => {
    setIsRefreshing(true)
    loadData()
  }

  const handleTrigger = async (taskId: string, displayName: string) => {
    if (!token) return
    setTriggeringTaskId(taskId)
    const toastId = `trigger-${taskId}`

    try {
      toast.loading(`Triggering ${displayName}...`, { id: toastId })
      const result = await scheduledTasksApi.triggerTask(token, taskId)
      toast.success(`${displayName} triggered (Run ${result.run_id.slice(0, 8)})`, { id: toastId })
      await loadData()
    } catch (error) {
      console.error('Failed to trigger task:', error)
      toast.error(`Failed to trigger ${displayName}`, { id: toastId })
    } finally {
      setTriggeringTaskId(null)
    }
  }

  const handleToggleEnabled = async (task: ScheduledTask) => {
    if (!token) return
    setTogglingTaskId(task.id)

    try {
      if (task.enabled) {
        await scheduledTasksApi.disableTask(token, task.id)
        toast.success(`${task.display_name} disabled`)
      } else {
        await scheduledTasksApi.enableTask(token, task.id)
        toast.success(`${task.display_name} enabled`)
      }
      await loadData()
    } catch (error) {
      console.error('Failed to toggle task:', error)
      toast.error(`Failed to ${task.enabled ? 'disable' : 'enable'} task`)
    } finally {
      setTogglingTaskId(null)
    }
  }

  const handleExpandTask = async (taskId: string) => {
    if (expandedTaskId === taskId) {
      setExpandedTaskId(null)
      return
    }
    setExpandedTaskId(taskId)

    if (!taskRuns[taskId] && token) {
      setLoadingRuns(taskId)
      try {
        const res = await scheduledTasksApi.getTaskRuns(token, taskId, 5)
        setTaskRuns((prev) => ({ ...prev, [taskId]: res.runs }))
      } catch (error) {
        console.error('Failed to load task runs:', error)
      } finally {
        setLoadingRuns(null)
      }
    }
  }

  const getStatusIcon = (status: string | null) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'failed':
        return <XCircle className="h-4 w-4 text-red-500" />
      case 'running':
      case 'submitted':
        return <RefreshCw className="h-4 w-4 text-blue-500 animate-spin" />
      case 'cancelled':
      case 'timed_out':
        return <AlertTriangle className="h-4 w-4 text-amber-500" />
      default:
        return <Clock className="h-4 w-4 text-gray-400" />
    }
  }

  const getStatusBadge = (status: string | null) => {
    const base = 'px-2 py-0.5 text-xs font-medium rounded-full'
    switch (status) {
      case 'completed':
        return <span className={`${base} bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400`}>Completed</span>
      case 'failed':
        return <span className={`${base} bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400`}>Failed</span>
      case 'running':
        return <span className={`${base} bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400`}>Running</span>
      case 'submitted':
        return <span className={`${base} bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400`}>Submitted</span>
      case 'cancelled':
        return <span className={`${base} bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400`}>Cancelled</span>
      case 'timed_out':
        return <span className={`${base} bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400`}>Timed Out</span>
      default:
        return <span className={`${base} bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400`}>Never Run</span>
    }
  }

  const formatDateTime = (iso: string | null) => {
    if (!iso) return '-'
    const d = new Date(iso)
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const formatRelativeTime = (iso: string | null) => {
    if (!iso) return null
    const d = new Date(iso)
    const now = new Date()
    const diffMs = d.getTime() - now.getTime()
    const absDiffMs = Math.abs(diffMs)

    if (absDiffMs < 60_000) return diffMs > 0 ? 'in <1 min' : '<1 min ago'
    if (absDiffMs < 3_600_000) {
      const mins = Math.round(absDiffMs / 60_000)
      return diffMs > 0 ? `in ${mins} min` : `${mins} min ago`
    }
    if (absDiffMs < 86_400_000) {
      const hrs = Math.round(absDiffMs / 3_600_000)
      return diffMs > 0 ? `in ${hrs}h` : `${hrs}h ago`
    }
    const days = Math.round(absDiffMs / 86_400_000)
    return diffMs > 0 ? `in ${days}d` : `${days}d ago`
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-600"></div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            System Maintenance
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Manage scheduled maintenance tasks and system health
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={isRefreshing}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-indigo-100 dark:bg-indigo-900/30 rounded-lg">
                <Activity className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
              </div>
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Total Tasks</p>
                <p className="text-xl font-semibold text-gray-900 dark:text-white">
                  {stats.total_tasks}
                </p>
              </div>
            </div>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-green-100 dark:bg-green-900/30 rounded-lg">
                <CheckCircle className="h-5 w-5 text-green-600 dark:text-green-400" />
              </div>
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Enabled</p>
                <p className="text-xl font-semibold text-gray-900 dark:text-white">
                  {stats.enabled_tasks}
                  <span className="text-sm font-normal text-gray-400 ml-1">
                    / {stats.total_tasks}
                  </span>
                </p>
              </div>
            </div>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
                <BarChart3 className="h-5 w-5 text-blue-600 dark:text-blue-400" />
              </div>
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Runs (7d)</p>
                <p className="text-xl font-semibold text-gray-900 dark:text-white">
                  {stats.total_runs}
                </p>
              </div>
            </div>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className={`p-2 rounded-lg ${
                stats.success_rate >= 90
                  ? 'bg-green-100 dark:bg-green-900/30'
                  : stats.success_rate >= 70
                    ? 'bg-amber-100 dark:bg-amber-900/30'
                    : 'bg-red-100 dark:bg-red-900/30'
              }`}>
                <Activity className={`h-5 w-5 ${
                  stats.success_rate >= 90
                    ? 'text-green-600 dark:text-green-400'
                    : stats.success_rate >= 70
                      ? 'text-amber-600 dark:text-amber-400'
                      : 'text-red-600 dark:text-red-400'
                }`} />
              </div>
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Success Rate</p>
                <p className="text-xl font-semibold text-gray-900 dark:text-white">
                  {stats.total_runs > 0 ? `${Math.round(stats.success_rate)}%` : '-'}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Task List */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Scheduled Tasks
          </h2>
        </div>
        <div className="divide-y divide-gray-200 dark:divide-gray-700">
          {tasks.length === 0 && (
            <div className="text-center py-12">
              <Wrench className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
              <p className="text-gray-500 dark:text-gray-400">
                No scheduled tasks found. Run the seed command to create baseline tasks.
              </p>
            </div>
          )}
          {tasks.map((task) => {
            const isExpanded = expandedTaskId === task.id
            const runs = taskRuns[task.id]
            const isRunning = task.last_run_status === 'running' || task.last_run_status === 'submitted'

            return (
              <div key={task.id}>
                <div className="px-6 py-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4 min-w-0 flex-1">
                      {/* Expand toggle */}
                      <button
                        onClick={() => handleExpandTask(task.id)}
                        className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors flex-shrink-0"
                      >
                        {isExpanded ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </button>

                      {/* Status indicator */}
                      <div className="flex-shrink-0">
                        {getStatusIcon(task.last_run_status)}
                      </div>

                      {/* Task info */}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <h3 className="font-medium text-gray-900 dark:text-white truncate">
                            {task.display_name}
                          </h3>
                          {!task.enabled && (
                            <span className="flex-shrink-0 px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400 rounded-full">
                              Disabled
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-gray-500 dark:text-gray-400 truncate">
                          {task.description || task.task_type}
                        </p>
                        <div className="flex items-center gap-4 mt-1 text-xs text-gray-400">
                          <span title={task.schedule_expression}>
                            {task.schedule_description}
                          </span>
                          {task.last_run_at && (
                            <span title={new Date(task.last_run_at).toLocaleString()}>
                              Last: {formatRelativeTime(task.last_run_at)}
                            </span>
                          )}
                          {task.enabled && task.next_run_at && (
                            <span title={new Date(task.next_run_at).toLocaleString()}>
                              Next: {formatRelativeTime(task.next_run_at)}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2 flex-shrink-0 ml-4">
                      <button
                        onClick={() => handleToggleEnabled(task)}
                        disabled={togglingTaskId === task.id}
                        className={`p-2 rounded-lg transition-colors ${
                          task.enabled
                            ? 'text-green-600 hover:bg-green-100 dark:hover:bg-green-900/30'
                            : 'text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'
                        } disabled:opacity-50`}
                        title={task.enabled ? 'Disable task' : 'Enable task'}
                      >
                        {task.enabled ? (
                          <Pause className="h-4 w-4" />
                        ) : (
                          <Play className="h-4 w-4" />
                        )}
                      </button>
                      <button
                        onClick={() => handleTrigger(task.id, task.display_name)}
                        disabled={triggeringTaskId === task.id || isRunning}
                        className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-white bg-amber-600 rounded-lg hover:bg-amber-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Run now"
                      >
                        {triggeringTaskId === task.id ? (
                          <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Play className="h-3.5 w-3.5" />
                        )}
                        Run Now
                      </button>
                    </div>
                  </div>
                </div>

                {/* Expanded run history */}
                {isExpanded && (
                  <div className="px-6 pb-4 ml-8">
                    <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4">
                      <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
                        Recent Runs
                      </h4>
                      {loadingRuns === task.id ? (
                        <div className="flex items-center gap-2 text-sm text-gray-400">
                          <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                          Loading...
                        </div>
                      ) : runs && runs.length > 0 ? (
                        <div className="space-y-2">
                          {runs.map((run) => (
                            <div
                              key={run.id}
                              className="flex items-center justify-between text-sm"
                            >
                              <div className="flex items-center gap-3">
                                {getStatusIcon(run.status)}
                                <span className="font-mono text-xs text-gray-500 dark:text-gray-400">
                                  {run.id.slice(0, 8)}
                                </span>
                                {getStatusBadge(run.status)}
                                <span className="text-xs text-gray-400">
                                  {run.origin === 'scheduled' ? 'Scheduled' : 'Manual'}
                                </span>
                              </div>
                              <div className="text-xs text-gray-400">
                                {formatDateTime(run.started_at || run.created_at)}
                                {run.error_message && (
                                  <span className="ml-2 text-red-400" title={run.error_message}>
                                    Error
                                  </span>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-sm text-gray-400">No runs recorded yet.</p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Info Card */}
      <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/50 rounded-xl p-6">
        <div className="flex items-start gap-4">
          <div className="p-2 bg-amber-100 dark:bg-amber-900/30 rounded-lg">
            <Wrench className="h-5 w-5 text-amber-600 dark:text-amber-400" />
          </div>
          <div>
            <h3 className="font-medium text-amber-900 dark:text-amber-200">
              About Maintenance Tasks
            </h3>
            <p className="text-sm text-amber-700 dark:text-amber-300 mt-1">
              Tasks run automatically on their configured schedules via Celery Beat.
              Use &ldquo;Run Now&rdquo; to trigger a task immediately. Disable a task to pause
              its schedule without removing it. Click a task row to view its run history.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

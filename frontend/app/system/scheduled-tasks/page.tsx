'use client'

/**
 * System Scheduled Tasks page.
 *
 * View and manage scheduled tasks.
 */

import { useState, useEffect } from 'react'
import {
  Calendar,
  Clock,
  Play,
  Pause,
  RefreshCw,
  CheckCircle,
  XCircle,
  AlertTriangle,
} from 'lucide-react'
import { useAuth } from '@/lib/auth-context'
import toast from 'react-hot-toast'

interface ScheduledTask {
  id: string
  name: string
  task_type: string
  schedule: string
  is_active: boolean
  last_run?: string
  next_run?: string
  last_status?: string
}

export default function SystemScheduledTasksPage() {
  const { token } = useAuth()
  const [tasks, setTasks] = useState<ScheduledTask[]>([])
  const [isLoading, setIsLoading] = useState(true)

  const loadTasks = async () => {
    if (!token) return

    try {
      // TODO: Call the scheduled tasks endpoint
      // For now, show sample data
      setTasks([
        {
          id: '1',
          name: 'Daily Cleanup',
          task_type: 'cleanup',
          schedule: '0 3 * * *',
          is_active: true,
          last_run: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
          next_run: new Date(Date.now() + 12 * 60 * 60 * 1000).toISOString(),
          last_status: 'completed',
        },
        {
          id: '2',
          name: 'Weekly Report',
          task_type: 'report',
          schedule: '0 8 * * 1',
          is_active: true,
          last_run: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
          next_run: new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString(),
          last_status: 'completed',
        },
        {
          id: '3',
          name: 'Search Index Update',
          task_type: 'reindex',
          schedule: '0 */6 * * *',
          is_active: false,
          last_run: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(),
          last_status: 'failed',
        },
      ])
    } catch (error) {
      console.error('Failed to load scheduled tasks:', error)
      toast.error('Failed to load scheduled tasks')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadTasks()
  }, [token])

  const toggleTask = (taskId: string) => {
    setTasks((prev) =>
      prev.map((t) =>
        t.id === taskId ? { ...t, is_active: !t.is_active } : t
      )
    )
    toast.success('Task updated')
  }

  const getStatusIcon = (status?: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'failed':
        return <XCircle className="h-4 w-4 text-red-500" />
      case 'running':
        return <RefreshCw className="h-4 w-4 text-blue-500 animate-spin" />
      default:
        return <Clock className="h-4 w-4 text-gray-400" />
    }
  }

  const formatSchedule = (schedule: string) => {
    // Simple cron description
    if (schedule === '0 3 * * *') return 'Daily at 3:00 AM'
    if (schedule === '0 8 * * 1') return 'Weekly on Monday at 8:00 AM'
    if (schedule === '0 */6 * * *') return 'Every 6 hours'
    return schedule
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
            Scheduled Tasks
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Manage automated scheduled tasks
          </p>
        </div>
        <button
          onClick={loadTasks}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {/* Tasks Table */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead className="bg-gray-50 dark:bg-gray-900/50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Task
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Schedule
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Last Run
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Next Run
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Status
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
            {tasks.map((task) => (
              <tr key={task.id} className="hover:bg-gray-50 dark:hover:bg-gray-900/30">
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-amber-100 dark:bg-amber-900/30 rounded-lg">
                      <Calendar className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                    </div>
                    <div>
                      <p className="font-medium text-gray-900 dark:text-white">
                        {task.name}
                      </p>
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        {task.task_type}
                      </p>
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <p className="text-sm text-gray-700 dark:text-gray-300">
                    {formatSchedule(task.schedule)}
                  </p>
                  <p className="text-xs text-gray-400 font-mono">
                    {task.schedule}
                  </p>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="flex items-center gap-2">
                    {getStatusIcon(task.last_status)}
                    <span className="text-sm text-gray-500 dark:text-gray-400">
                      {task.last_run
                        ? new Date(task.last_run).toLocaleDateString()
                        : 'Never'}
                    </span>
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <span className="text-sm text-gray-500 dark:text-gray-400">
                    {task.next_run && task.is_active
                      ? new Date(task.next_run).toLocaleDateString()
                      : '-'}
                  </span>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  {task.is_active ? (
                    <span className="flex items-center gap-1 px-2 py-1 text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400 rounded-full w-fit">
                      <CheckCircle className="h-3 w-3" />
                      Active
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 px-2 py-1 text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400 rounded-full w-fit">
                      <Pause className="h-3 w-3" />
                      Paused
                    </span>
                  )}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-right">
                  <div className="flex items-center justify-end gap-2">
                    <button
                      onClick={() => toggleTask(task.id)}
                      className={`p-2 rounded-lg transition-colors ${
                        task.is_active
                          ? 'text-amber-600 hover:bg-amber-100 dark:hover:bg-amber-900/30'
                          : 'text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'
                      }`}
                      title={task.is_active ? 'Pause task' : 'Resume task'}
                    >
                      {task.is_active ? (
                        <Pause className="h-4 w-4" />
                      ) : (
                        <Play className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {tasks.length === 0 && (
          <div className="text-center py-12">
            <Calendar className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <p className="text-gray-500 dark:text-gray-400">
              No scheduled tasks configured
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

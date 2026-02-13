'use client'

/**
 * System Maintenance page.
 *
 * Manage system maintenance tasks and queues.
 */

import { useState } from 'react'
import {
  Wrench,
  Play,
  Clock,
  CheckCircle,
  AlertTriangle,
  Trash2,
  RefreshCw,
  Database,
  Search,
  FileText,
} from 'lucide-react'
import toast from 'react-hot-toast'

interface MaintenanceTask {
  id: string
  name: string
  description: string
  lastRun?: string
  status: 'idle' | 'running' | 'completed' | 'failed'
  icon: React.ComponentType<{ className?: string }>
}

const maintenanceTasks: MaintenanceTask[] = [
  {
    id: 'cleanup_temp_files',
    name: 'Cleanup Temporary Files',
    description: 'Remove temporary files older than 24 hours',
    icon: Trash2,
    status: 'idle',
  },
  {
    id: 'reindex_search',
    name: 'Reindex Search',
    description: 'Rebuild search indexes for all assets',
    icon: Search,
    status: 'idle',
  },
  {
    id: 'vacuum_database',
    name: 'Vacuum Database',
    description: 'Optimize database storage and performance',
    icon: Database,
    status: 'idle',
  },
  {
    id: 'cleanup_orphan_files',
    name: 'Cleanup Orphan Files',
    description: 'Remove files not linked to any asset',
    icon: FileText,
    status: 'idle',
  },
]

export default function SystemMaintenancePage() {
  const [tasks, setTasks] = useState(maintenanceTasks)
  const [isRefreshing, setIsRefreshing] = useState(false)

  const handleRunTask = async (taskId: string) => {
    setTasks((prev) =>
      prev.map((t) =>
        t.id === taskId ? { ...t, status: 'running' as const } : t
      )
    )

    // Simulate task execution
    toast.loading(`Running ${taskId}...`, { id: taskId })

    setTimeout(() => {
      setTasks((prev) =>
        prev.map((t) =>
          t.id === taskId
            ? { ...t, status: 'completed' as const, lastRun: new Date().toISOString() }
            : t
        )
      )
      toast.success(`Task completed`, { id: taskId })
    }, 3000)
  }

  const handleRefresh = () => {
    setIsRefreshing(true)
    setTimeout(() => {
      setIsRefreshing(false)
    }, 1000)
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'running':
        return <RefreshCw className="h-4 w-4 animate-spin text-blue-500" />
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'failed':
        return <AlertTriangle className="h-4 w-4 text-red-500" />
      default:
        return <Clock className="h-4 w-4 text-gray-400" />
    }
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
            Run maintenance tasks and manage system health
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

      {/* Maintenance Tasks */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Maintenance Tasks
          </h2>
        </div>
        <div className="divide-y divide-gray-200 dark:divide-gray-700">
          {tasks.map((task) => {
            const Icon = task.icon
            return (
              <div
                key={task.id}
                className="px-6 py-4 flex items-center justify-between"
              >
                <div className="flex items-center gap-4">
                  <div className="p-2 bg-amber-100 dark:bg-amber-900/30 rounded-lg">
                    <Icon className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                  </div>
                  <div>
                    <h3 className="font-medium text-gray-900 dark:text-white">
                      {task.name}
                    </h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {task.description}
                    </p>
                    {task.lastRun && (
                      <p className="text-xs text-gray-400 mt-1">
                        Last run: {new Date(task.lastRun).toLocaleString()}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  {getStatusIcon(task.status)}
                  <button
                    onClick={() => handleRunTask(task.id)}
                    disabled={task.status === 'running'}
                    className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-amber-600 rounded-lg hover:bg-amber-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Play className="h-4 w-4" />
                    Run
                  </button>
                </div>
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
              Maintenance tasks help keep the system running smoothly. Some tasks
              may take several minutes to complete. Running tasks during off-peak
              hours is recommended for large datasets.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

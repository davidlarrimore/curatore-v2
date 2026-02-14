'use client'

import { useState, useEffect } from 'react'
import {
  CheckCircle,
  XCircle,
  AlertCircle,
  Loader2,
  Server,
  Database,
  Cpu,
  HardDrive,
  Zap,
  Cloud,
  RefreshCw
} from 'lucide-react'

interface ComponentHealth {
  status: 'healthy' | 'unhealthy' | 'degraded' | 'not_configured' | 'unknown' | 'not_enabled'
  message: string
  [key: string]: string | number | boolean | null | undefined
}

interface HealthData {
  timestamp: string
  overall_status: 'healthy' | 'unhealthy' | 'degraded'
  components: {
    backend?: ComponentHealth
    database?: ComponentHealth
    redis?: ComponentHealth
    celery_worker?: ComponentHealth
    extraction_service?: ComponentHealth
    llm?: ComponentHealth
    object_storage?: ComponentHealth
    [key: string]: ComponentHealth | undefined
  }
  issues?: string[]
}

interface SystemHealthCardProps {
  healthData: HealthData | null
  isLoading: boolean
  onRefresh: () => void
}

const componentConfig: Record<string, { name: string; icon: React.ComponentType<{ className?: string }> }> = {
  backend: { name: 'Backend', icon: Server },
  database: { name: 'Database', icon: Database },
  redis: { name: 'Redis', icon: Database },
  celery_worker: { name: 'Celery', icon: Cpu },
  extraction_service: { name: 'Extraction', icon: Zap },
  llm: { name: 'LLM', icon: Zap },
  object_storage: { name: 'Storage', icon: HardDrive },
  playwright: { name: 'Playwright', icon: Cloud },
}

export function SystemHealthCard({ healthData, isLoading, onRefresh }: SystemHealthCardProps) {
  const getStatusIcon = (status?: string) => {
    switch (status) {
      case 'healthy':
        return <CheckCircle className="w-4 h-4 text-emerald-500" />
      case 'unhealthy':
        return <XCircle className="w-4 h-4 text-red-500" />
      case 'degraded':
        return <AlertCircle className="w-4 h-4 text-amber-500" />
      case 'not_configured':
      case 'not_enabled':
        return <AlertCircle className="w-4 h-4 text-gray-400" />
      default:
        return <AlertCircle className="w-4 h-4 text-gray-400" />
    }
  }

  const getStatusColor = (status?: string) => {
    switch (status) {
      case 'healthy':
        return 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400'
      case 'unhealthy':
        return 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400'
      case 'degraded':
        return 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400'
      default:
        return 'bg-gray-50 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
    }
  }

  const getOverallStatusGradient = (status?: string) => {
    switch (status) {
      case 'healthy':
        return 'from-emerald-500 to-teal-500'
      case 'unhealthy':
        return 'from-red-500 to-rose-500'
      case 'degraded':
        return 'from-amber-500 to-orange-500'
      default:
        return 'from-gray-400 to-gray-500'
    }
  }

  // Filter components to show only the important ones
  const displayComponents = ['backend', 'database', 'redis', 'celery_worker', 'llm', 'object_storage', 'extraction_service', 'playwright']

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden hover:shadow-lg hover:shadow-gray-200/50 dark:hover:shadow-gray-900/50 transition-all duration-200">
      {/* Status bar at top */}
      <div className={`h-1 bg-gradient-to-r ${getOverallStatusGradient(healthData?.overall_status)}`} />

      <div className="p-5">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-500 flex items-center justify-center text-white shadow-lg shadow-emerald-500/25">
              <Server className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-gray-900 dark:text-white">System Health</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {healthData?.overall_status === 'healthy' ? 'All systems operational' :
                 healthData?.overall_status === 'degraded' ? 'Some issues detected' :
                 healthData?.overall_status === 'unhealthy' ? 'System issues' : 'Checking...'}
              </p>
            </div>
          </div>
          <button
            onClick={onRefresh}
            disabled={isLoading}
            className="p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-all"
            title="Refresh health status"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        {/* Loading State */}
        {isLoading && !healthData ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 text-gray-400 animate-spin" />
          </div>
        ) : (
          <>
            {/* Component Status Grid */}
            <div className="grid grid-cols-2 gap-2">
              {displayComponents.map((key) => {
                const component = healthData?.components?.[key]
                const config = componentConfig[key] || { name: key, icon: Server }
                const Icon = config.icon

                return (
                  <div
                    key={key}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg ${getStatusColor(component?.status)}`}
                    title={component?.message}
                  >
                    {getStatusIcon(component?.status)}
                    <span className="text-xs font-medium truncate">{config.name}</span>
                  </div>
                )
              })}
            </div>

            {/* Issues List */}
            {healthData?.issues && healthData.issues.length > 0 && (
              <div className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-700">
                <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">Issues:</p>
                <ul className="space-y-1">
                  {healthData.issues.slice(0, 3).map((issue, i) => (
                    <li key={i} className="text-xs text-red-600 dark:text-red-400 truncate">
                      {issue}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

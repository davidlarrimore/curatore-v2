// components/admin/InfrastructureHealthPanel.tsx
'use client'

import { useState, useEffect } from 'react'
import { systemApi } from '@/lib/api'
import { RefreshCw, CheckCircle, XCircle, AlertCircle, AlertTriangle, HelpCircle, Loader2, ExternalLink, Filter } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { formatTime, DISPLAY_TIMEZONE_ABBR } from '@/lib/date-utils'

interface ComponentHealth {
  status: 'healthy' | 'unhealthy' | 'degraded' | 'unknown' | 'not_configured' | 'not_enabled' | 'checking'
  message: string
  database_type?: string
  migration_version?: string
  database_size_mb?: number
  version?: string
  url?: string
  endpoint?: string
  model?: string
  worker_count?: number
  broker_url?: string
  queue?: string
  engine?: string
  tenant_id?: string
}

type ComponentKey =
  | 'backend'
  | 'database'
  | 'redis'
  | 'celery_worker'
  | 'extraction_service'
  | 'object_storage'
  | 'llm'
  | 'playwright'
  | 'sharepoint'

const CORE_COMPONENTS: ComponentKey[] = ['backend', 'database', 'redis', 'celery_worker']

const COMPONENT_MAP: Record<ComponentKey, {
  displayName: string
  description: string
  docsUrl?: string | (() => string)
}> = {
  backend: {
    displayName: 'Backend API',
    description: 'FastAPI application server',
    docsUrl: () => {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      return `${apiBase}/docs`
    }
  },
  database: {
    displayName: 'Database',
    description: 'PostgreSQL data store'
  },
  redis: {
    displayName: 'Redis',
    description: 'Message broker and cache'
  },
  celery_worker: {
    displayName: 'Celery Worker',
    description: 'Async task processor'
  },
  extraction_service: {
    displayName: 'Document Service',
    description: 'Document conversion microservice'
  },
  object_storage: {
    displayName: 'Object Storage',
    description: 'S3/MinIO file storage'
  },
  llm: {
    displayName: 'LLM Connection',
    description: 'AI language model provider'
  },
  playwright: {
    displayName: 'Playwright',
    description: 'Browser rendering service'
  },
  sharepoint: {
    displayName: 'SharePoint',
    description: 'Microsoft Graph API integration'
  },
}

const ALL_COMPONENTS = Object.keys(COMPONENT_MAP) as ComponentKey[]

const DEFAULT_CHECKING: ComponentHealth = { status: 'checking', message: 'Checking...' }

function buildCheckingState(): Record<ComponentKey, ComponentHealth> {
  const state: Partial<Record<ComponentKey, ComponentHealth>> = {}
  for (const key of ALL_COMPONENTS) {
    state[key] = { ...DEFAULT_CHECKING }
  }
  return state as Record<ComponentKey, ComponentHealth>
}

export default function InfrastructureHealthPanel() {
  const [components, setComponents] = useState<Record<ComponentKey, ComponentHealth>>(buildCheckingState)
  const [lastChecked, setLastChecked] = useState<Date | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [retesting, setRetesting] = useState<Set<ComponentKey>>(new Set())
  const [showAll, setShowAll] = useState(false)

  const visibleComponents = showAll ? ALL_COMPONENTS : CORE_COMPONENTS

  const loadAllHealthData = async () => {
    setIsRefreshing(true)
    setComponents(buildCheckingState())

    try {
      const rawData = await systemApi.getComprehensiveHealth()
      const data = rawData as { components?: Record<string, ComponentHealth> }
      const newComponents = buildCheckingState()

      if (data.components) {
        for (const [key, value] of Object.entries(data.components)) {
          if (key in newComponents) {
            newComponents[key as ComponentKey] = value as ComponentHealth
          }
        }
      }

      setComponents(newComponents)
    } catch (error) {
      console.error('Failed to load comprehensive health:', error)
      // Mark all as unhealthy on error
      const errorState = buildCheckingState()
      for (const key of ALL_COMPONENTS) {
        errorState[key] = {
          status: 'unhealthy',
          message: `Health check failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
        }
      }
      setComponents(errorState)
    }

    setLastChecked(new Date())
    setIsRefreshing(false)
  }

  const retestComponent = async (key: ComponentKey) => {
    setRetesting(prev => new Set(prev).add(key))
    setComponents(prev => ({
      ...prev,
      [key]: { status: 'checking', message: 'Checking...' }
    }))

    // Retest via the comprehensive endpoint to get fresh data for this component
    try {
      const rawData = await systemApi.getComprehensiveHealth()
      const data = rawData as { components?: Record<string, ComponentHealth> }
      if (data.components && data.components[key]) {
        setComponents(prev => ({
          ...prev,
          [key]: data.components![key]
        }))
      }
    } catch (error) {
      console.error(`Failed to retest ${key}:`, error)
      setComponents(prev => ({
        ...prev,
        [key]: {
          status: 'unhealthy',
          message: `Failed to check health: ${error instanceof Error ? error.message : 'Unknown error'}`
        }
      }))
    }

    setRetesting(prev => {
      const next = new Set(prev)
      next.delete(key)
      return next
    })
  }

  useEffect(() => {
    loadAllHealthData()
  }, [])

  const getOverallStatus = (): 'healthy' | 'degraded' | 'unhealthy' | 'checking' => {
    const statuses = Object.values(components).map(c => c.status)

    if (statuses.some(s => s === 'checking')) return 'checking'
    if (statuses.some(s => s === 'unhealthy')) return 'unhealthy'
    if (statuses.some(s => s === 'degraded' || s === 'unknown')) return 'degraded'
    return 'healthy'
  }

  const getIssues = (): string[] => {
    const issues: string[] = []
    Object.entries(components).forEach(([key, component]) => {
      if (component.status === 'unhealthy' || component.status === 'degraded') {
        const displayName = COMPONENT_MAP[key as ComponentKey]?.displayName || key
        issues.push(`${displayName}: ${component.message}`)
      }
    })
    return issues
  }

  const getStatusIcon = (status: ComponentHealth['status']) => {
    switch (status) {
      case 'healthy':
        return <CheckCircle className="w-5 h-5 text-green-500" />
      case 'unhealthy':
        return <XCircle className="w-5 h-5 text-red-500" />
      case 'degraded':
        return <AlertTriangle className="w-5 h-5 text-yellow-500" />
      case 'not_configured':
      case 'not_enabled':
        return <AlertCircle className="w-5 h-5 text-gray-400" />
      case 'checking':
        return <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
      case 'unknown':
      default:
        return <HelpCircle className="w-5 h-5 text-gray-400" />
    }
  }

  const getStatusColor = (status: ComponentHealth['status']) => {
    switch (status) {
      case 'healthy':
        return 'bg-green-50 border-green-200 dark:bg-green-900/20 dark:border-green-800'
      case 'unhealthy':
        return 'bg-red-50 border-red-200 dark:bg-red-900/20 dark:border-red-800'
      case 'degraded':
        return 'bg-yellow-50 border-yellow-200 dark:bg-yellow-900/20 dark:border-yellow-800'
      case 'not_configured':
      case 'not_enabled':
        return 'bg-gray-50 border-gray-200 dark:bg-gray-800 dark:border-gray-700 opacity-60'
      case 'checking':
        return 'bg-blue-50 border-blue-200 dark:bg-blue-900/20 dark:border-blue-800 animate-pulse'
      case 'unknown':
      default:
        return 'bg-gray-50 border-gray-200 dark:bg-gray-800 dark:border-gray-700'
    }
  }

  const getOverallStatusBadge = (status: string) => {
    switch (status) {
      case 'healthy':
        return (
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300">
            <CheckCircle className="w-4 h-4 mr-2" />
            All Systems Operational
          </span>
        )
      case 'degraded':
        return (
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300">
            <AlertTriangle className="w-4 h-4 mr-2" />
            Degraded Performance
          </span>
        )
      case 'unhealthy':
        return (
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300">
            <XCircle className="w-4 h-4 mr-2" />
            System Issues Detected
          </span>
        )
      case 'checking':
        return (
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            Checking Systems...
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300">
            <HelpCircle className="w-4 h-4 mr-2" />
            Unknown Status
          </span>
        )
    }
  }

  const getDocsUrl = (key: ComponentKey): string | null => {
    const config = COMPONENT_MAP[key]
    if (!config.docsUrl) return null

    if (typeof config.docsUrl === 'function') {
      return config.docsUrl()
    }
    return config.docsUrl
  }

  const overallStatus = getOverallStatus()
  const issues = getIssues()

  return (
    <div className="space-y-6">
      {/* Header with overall status */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
            Infrastructure Health
          </h2>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Monitor the status of system components
          </p>
        </div>
        <div className="flex items-center space-x-4">
          {getOverallStatusBadge(overallStatus)}
          <Button
            variant="secondary"
            size="sm"
            onClick={loadAllHealthData}
            disabled={isRefreshing}
            className="flex items-center space-x-2"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            <span>Refresh All</span>
          </Button>
        </div>
      </div>

      {lastChecked && (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Last checked: {formatTime(lastChecked)} {DISPLAY_TIMEZONE_ABBR}
        </p>
      )}

      {/* Filter toggle */}
      <div className="flex items-center space-x-2">
        <button
          onClick={() => setShowAll(!showAll)}
          className="inline-flex items-center px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors
            bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600
            text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
        >
          <Filter className="w-4 h-4 mr-2" />
          {showAll ? 'Show Core Only' : 'Show All Components'}
        </button>
        <span className="text-xs text-gray-500 dark:text-gray-400">
          Showing {visibleComponents.length} of {ALL_COMPONENTS.length} components
        </span>
      </div>

      {/* Issues Summary */}
      {issues.length > 0 && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg dark:bg-red-900/20 dark:border-red-800">
          <h3 className="text-sm font-semibold text-red-800 dark:text-red-300 mb-2">Issues Detected:</h3>
          <ul className="list-disc list-inside space-y-1">
            {issues.map((issue, index) => (
              <li key={index} className="text-sm text-red-700 dark:text-red-400">
                {issue}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Component Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {visibleComponents.map((key) => {
          const component = components[key]
          const config = COMPONENT_MAP[key]
          const docsUrl = component.status === 'healthy' ? getDocsUrl(key) : null
          const isRetesting = retesting.has(key)

          return (
            <div
              key={key}
              className={`border-2 rounded-lg p-4 transition-all ${getStatusColor(component.status)}`}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-start space-x-3 flex-1 min-w-0">
                  {getStatusIcon(component.status)}
                  <div className="flex-1 min-w-0">
                    {docsUrl ? (
                      <a
                        href={docsUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-semibold text-gray-900 dark:text-white hover:text-blue-600 dark:hover:text-blue-400 transition-colors flex items-center space-x-1 group"
                        title={`View ${config.displayName} documentation`}
                      >
                        <span>{config.displayName}</span>
                        <ExternalLink className="w-3 h-3 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                      </a>
                    ) : (
                      <h3 className="font-semibold text-gray-900 dark:text-white">
                        {config.displayName}
                      </h3>
                    )}
                    <p className="text-xs text-gray-500 dark:text-gray-400">{config.description}</p>
                  </div>
                </div>
                <div className="flex items-center space-x-2 flex-shrink-0">
                  <button
                    onClick={() => retestComponent(key)}
                    disabled={isRetesting || component.status === 'checking'}
                    className={`p-1.5 rounded-md transition-colors ${
                      isRetesting || component.status === 'checking'
                        ? 'text-gray-400 cursor-not-allowed'
                        : 'text-gray-500 hover:text-gray-700 hover:bg-gray-200 dark:hover:bg-gray-700'
                    }`}
                    title={`Retest ${config.displayName}`}
                    aria-label={`Retest ${config.displayName}`}
                  >
                    <RefreshCw className={`w-4 h-4 ${isRetesting || component.status === 'checking' ? 'animate-spin' : ''}`} />
                  </button>
                  <span className={`text-xs px-2 py-1 rounded-full font-medium ${
                    component.status === 'healthy' ? 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300' :
                    component.status === 'unhealthy' ? 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300' :
                    component.status === 'degraded' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/50 dark:text-yellow-300' :
                    component.status === 'checking' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300' :
                    'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
                  }`}>
                    {component.status === 'not_configured' || component.status === 'not_enabled' ? 'N/A' : component.status}
                  </span>
                </div>
              </div>

              <p className="text-sm text-gray-700 dark:text-gray-300 mb-3">{component.message}</p>

              {/* Additional component details */}
              {component.status !== 'checking' && (
                <div className="space-y-1 text-xs text-gray-600 dark:text-gray-400 pt-2 border-t border-gray-200/50 dark:border-gray-700/50">
                  {/* Database-specific fields */}
                  {component.database_type && (
                    <div className="flex justify-between">
                      <span className="font-medium">Type:</span>
                      <span className="uppercase">{component.database_type}</span>
                    </div>
                  )}
                  {component.migration_version && (
                    <div className="flex justify-between">
                      <span className="font-medium">Migration:</span>
                      <span className="font-mono">{component.migration_version}</span>
                    </div>
                  )}
                  {component.database_size_mb !== undefined && (
                    <div className="flex justify-between">
                      <span className="font-medium">Size:</span>
                      <span>{component.database_size_mb} MB</span>
                    </div>
                  )}

                  {/* Generic fields */}
                  {component.version && (
                    <div className="flex justify-between">
                      <span className="font-medium">Version:</span>
                      <span>{component.version}</span>
                    </div>
                  )}
                  {component.url && (
                    <div className="flex justify-between">
                      <span className="font-medium">URL:</span>
                      <span className="truncate ml-2" title={component.url}>
                        {component.url.replace(/^https?:\/\//, '')}
                      </span>
                    </div>
                  )}
                  {component.endpoint && !component.url && (
                    <div className="flex justify-between">
                      <span className="font-medium">Endpoint:</span>
                      <span className="truncate ml-2" title={component.endpoint}>
                        {component.endpoint.replace(/^https?:\/\//, '')}
                      </span>
                    </div>
                  )}
                  {component.model && (
                    <div className="flex justify-between">
                      <span className="font-medium">Model:</span>
                      <span>{component.model}</span>
                    </div>
                  )}
                  {component.worker_count !== undefined && (
                    <div className="flex justify-between">
                      <span className="font-medium">Workers:</span>
                      <span>{component.worker_count}</span>
                    </div>
                  )}
                  {component.broker_url && (
                    <div className="flex justify-between">
                      <span className="font-medium">Broker:</span>
                      <span className="truncate ml-2" title={component.broker_url}>
                        {component.broker_url.replace(/^redis:\/\//, '')}
                      </span>
                    </div>
                  )}
                  {component.queue && (
                    <div className="flex justify-between">
                      <span className="font-medium">Queue:</span>
                      <span>{component.queue}</span>
                    </div>
                  )}
                  {component.engine && (
                    <div className="flex justify-between">
                      <span className="font-medium">Engine:</span>
                      <span>{component.engine}</span>
                    </div>
                  )}
                  {component.tenant_id && (
                    <div className="flex justify-between">
                      <span className="font-medium">Tenant:</span>
                      <span className="truncate ml-2 font-mono">{component.tenant_id}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Info Box */}
      <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg className="h-5 w-5 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
            </svg>
          </div>
          <div className="ml-3">
            <h3 className="text-sm font-medium text-blue-800 dark:text-blue-200">
              About Infrastructure Health
            </h3>
            <div className="mt-2 text-sm text-blue-700 dark:text-blue-300">
              <ul className="list-disc list-inside space-y-1">
                <li>Health data is fetched from a single comprehensive endpoint</li>
                <li>Components marked N/A are not configured in the current environment</li>
                <li>Use &quot;Show All Components&quot; to see optional services</li>
                <li>Click the refresh icon on any component to recheck individually</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

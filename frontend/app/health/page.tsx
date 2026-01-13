// app/health/page.tsx
'use client'

import { useState, useEffect } from 'react'
import { systemApi } from '@/lib/api'
import { RefreshCw, CheckCircle, XCircle, AlertCircle, AlertTriangle, HelpCircle, Loader2, ExternalLink } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import toast from 'react-hot-toast'

interface ComponentHealth {
  status: 'healthy' | 'unhealthy' | 'degraded' | 'unknown' | 'not_configured' | 'checking'
  message: string
  [key: string]: any
}

type ComponentKey = 'backend' | 'database' | 'redis' | 'celery_worker' | 'extraction_service' | 'docling' | 'llm' | 'sharepoint'

// Map internal Docker URLs to public localhost URLs
const mapToPublicUrl = (internalUrl: string): string => {
  // Get base URLs from environment with fallback defaults matching docker-compose port mappings
  const publicApiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
  const publicExtractionUrl = process.env.NEXT_PUBLIC_EXTRACTION_URL || 'http://localhost:8010'
  const publicDoclingUrl = process.env.NEXT_PUBLIC_DOCLING_URL || 'http://localhost:5151'
  const publicRedisUrl = process.env.NEXT_PUBLIC_REDIS_URL || 'http://localhost:6379'

  // Map internal Docker service names to public URLs (from environment or defaults)
  const dockerToPublic: Record<string, string> = {
    'http://extraction:8010': publicExtractionUrl,
    'http://docling:5001': publicDoclingUrl,
    'http://backend:8000': publicApiUrl,
    'http://redis:6379': publicRedisUrl,
  }

  // Check for exact matches first
  for (const [dockerUrl, publicUrl] of Object.entries(dockerToPublic)) {
    if (internalUrl.startsWith(dockerUrl)) {
      return internalUrl.replace(dockerUrl, publicUrl)
    }
  }

  // If no match, return as-is (might already be a public URL)
  return internalUrl
}

const COMPONENT_MAP: Record<ComponentKey, {
  apiKey: 'backend' | 'database' | 'redis' | 'celery' | 'extraction' | 'docling' | 'llm' | 'sharepoint',
  displayName: string,
  docsUrl?: string | ((component: ComponentHealth) => string | null)
}> = {
  backend: {
    apiKey: 'backend',
    displayName: 'Backend API',
    docsUrl: () => {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      return `${apiBase}/docs`
    }
  },
  database: { apiKey: 'database', displayName: 'Database' },
  redis: { apiKey: 'redis', displayName: 'Redis' },
  celery_worker: { apiKey: 'celery', displayName: 'Celery Worker' },
  extraction_service: {
    apiKey: 'extraction',
    displayName: 'Extraction Service',
    docsUrl: (component) => {
      // Extract base URL from the health check URL and map to public URL
      if (component.url) {
        const match = component.url.match(/^(https?:\/\/[^/]+)/)
        if (match) {
          const publicUrl = mapToPublicUrl(match[1])
          return `${publicUrl}/api/v1/docs`
        }
      }
      return 'http://localhost:8010/api/v1/docs'
    }
  },
  docling: {
    apiKey: 'docling',
    displayName: 'Docling Service',
    docsUrl: (component) => {
      // Map internal Docker URL to public localhost URL
      if (component.url) {
        const publicUrl = mapToPublicUrl(component.url)
        return `${publicUrl}/docs`
      }
      return 'http://localhost:5151/docs'
    }
  },
  llm: { apiKey: 'llm', displayName: 'LLM Connection' },
  sharepoint: {
    apiKey: 'sharepoint',
    displayName: 'SharePoint / Microsoft Graph',
    docsUrl: () => 'https://learn.microsoft.com/en-us/graph/api/overview'
  },
}

export default function SystemHealthPage() {
  const [components, setComponents] = useState<Record<ComponentKey, ComponentHealth>>({
    backend: { status: 'checking', message: 'Checking...' },
    database: { status: 'checking', message: 'Checking...' },
    redis: { status: 'checking', message: 'Checking...' },
    celery_worker: { status: 'checking', message: 'Checking...' },
    extraction_service: { status: 'checking', message: 'Checking...' },
    docling: { status: 'checking', message: 'Checking...' },
    llm: { status: 'checking', message: 'Checking...' },
    sharepoint: { status: 'checking', message: 'Checking...' },
  })

  const [lastChecked, setLastChecked] = useState<Date | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [retesting, setRetesting] = useState<Set<ComponentKey>>(new Set())

  const checkComponentHealth = async (key: ComponentKey) => {
    const componentConfig = COMPONENT_MAP[key]
    try {
      const data = await systemApi.getComponentHealth(componentConfig.apiKey)
      setComponents(prev => ({
        ...prev,
        [key]: data
      }))
    } catch (error) {
      console.error(`Failed to load ${key} health:`, error)
      setComponents(prev => ({
        ...prev,
        [key]: {
          status: 'unhealthy',
          message: `Failed to check health: ${error instanceof Error ? error.message : 'Unknown error'}`
        }
      }))
    }
  }

  const retestComponent = async (key: ComponentKey) => {
    setRetesting(prev => new Set(prev).add(key))

    // Set component to checking state
    setComponents(prev => ({
      ...prev,
      [key]: { status: 'checking', message: 'Checking...' }
    }))

    await checkComponentHealth(key)

    setRetesting(prev => {
      const next = new Set(prev)
      next.delete(key)
      return next
    })
  }

  const loadAllHealthData = async () => {
    setIsRefreshing(true)

    // Reset all to checking state
    setComponents({
      backend: { status: 'checking', message: 'Checking...' },
      database: { status: 'checking', message: 'Checking...' },
      redis: { status: 'checking', message: 'Checking...' },
      celery_worker: { status: 'checking', message: 'Checking...' },
      extraction_service: { status: 'checking', message: 'Checking...' },
      docling: { status: 'checking', message: 'Checking...' },
      llm: { status: 'checking', message: 'Checking...' },
      sharepoint: { status: 'checking', message: 'Checking...' },
    })

    // Fire off all health checks in parallel
    await Promise.all([
      checkComponentHealth('backend'),
      checkComponentHealth('database'),
      checkComponentHealth('redis'),
      checkComponentHealth('celery_worker'),
      checkComponentHealth('extraction_service'),
      checkComponentHealth('docling'),
      checkComponentHealth('llm'),
      checkComponentHealth('sharepoint'),
    ])

    setLastChecked(new Date())
    setIsRefreshing(false)
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
        const displayName = COMPONENT_MAP[key as ComponentKey].displayName
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
        return 'bg-green-50 border-green-200'
      case 'unhealthy':
        return 'bg-red-50 border-red-200'
      case 'degraded':
        return 'bg-yellow-50 border-yellow-200'
      case 'not_configured':
        return 'bg-gray-50 border-gray-200'
      case 'checking':
        return 'bg-blue-50 border-blue-200 animate-pulse'
      case 'unknown':
      default:
        return 'bg-gray-50 border-gray-200'
    }
  }

  const getOverallStatusBadge = (status: string) => {
    switch (status) {
      case 'healthy':
        return (
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-green-100 text-green-800">
            <CheckCircle className="w-4 h-4 mr-2" />
            All Systems Operational
          </span>
        )
      case 'degraded':
        return (
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-yellow-100 text-yellow-800">
            <AlertTriangle className="w-4 h-4 mr-2" />
            Degraded Performance
          </span>
        )
      case 'unhealthy':
        return (
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-red-100 text-red-800">
            <XCircle className="w-4 h-4 mr-2" />
            System Issues Detected
          </span>
        )
      case 'checking':
        return (
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-100 text-blue-800">
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            Checking Systems...
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-gray-100 text-gray-800">
            <HelpCircle className="w-4 h-4 mr-2" />
            Unknown Status
          </span>
        )
    }
  }

  const overallStatus = getOverallStatus()
  const issues = getIssues()

  const getDocsUrl = (key: ComponentKey, component: ComponentHealth): string | null => {
    const config = COMPONENT_MAP[key]
    if (!config.docsUrl) return null

    if (typeof config.docsUrl === 'function') {
      return config.docsUrl(component)
    }
    return config.docsUrl
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">System Health</h1>
              <p className="mt-1 text-sm text-gray-500">
                Monitor the status of all system components
              </p>
            </div>
            <Button
              onClick={loadAllHealthData}
              disabled={isRefreshing}
              className="flex items-center space-x-2"
            >
              <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </Button>
          </div>

          {lastChecked && (
            <p className="mt-2 text-sm text-gray-500">
              Last checked: {lastChecked.toLocaleTimeString()}
            </p>
          )}
        </div>

        {/* Overall Status Card */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 mb-2">Overall Status</h2>
              {getOverallStatusBadge(overallStatus)}
            </div>
            <div className="text-right">
              <p className="text-sm text-gray-500">Components</p>
              <p className="text-2xl font-bold text-gray-900">
                {Object.keys(components).length}
              </p>
            </div>
          </div>

          {issues.length > 0 && (
            <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
              <h3 className="text-sm font-semibold text-red-800 mb-2">Issues Detected:</h3>
              <ul className="list-disc list-inside space-y-1">
                {issues.map((issue, index) => (
                  <li key={index} className="text-sm text-red-700">
                    {issue}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Component Status Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {(Object.entries(components) as [ComponentKey, ComponentHealth][]).map(([key, component]) => {
            const docsUrl = component.status === 'healthy' ? getDocsUrl(key, component) : null
            const isRetesting = retesting.has(key)

            return (
              <div
                key={key}
                className={`border rounded-lg p-6 transition-all ${getStatusColor(component.status)}`}
              >
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center space-x-3 flex-1 min-w-0">
                    {getStatusIcon(component.status)}
                    {docsUrl ? (
                      <a
                        href={docsUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-semibold text-gray-900 hover:text-blue-600 transition-colors flex items-center space-x-1 group"
                        title={`View ${COMPONENT_MAP[key].displayName} API documentation`}
                      >
                        <span className="truncate">{COMPONENT_MAP[key].displayName}</span>
                        <ExternalLink className="w-3 h-3 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                      </a>
                    ) : (
                      <h3 className="font-semibold text-gray-900 truncate">
                        {COMPONENT_MAP[key].displayName}
                      </h3>
                    )}
                  </div>
                  <div className="flex items-center space-x-2 flex-shrink-0">
                    <button
                      onClick={() => retestComponent(key)}
                      disabled={isRetesting || component.status === 'checking'}
                      className={`p-1 rounded transition-colors ${
                        isRetesting || component.status === 'checking'
                          ? 'text-gray-400 cursor-not-allowed'
                          : 'text-gray-500 hover:text-gray-700 hover:bg-gray-200'
                      }`}
                      title={`Retest ${COMPONENT_MAP[key].displayName}`}
                      aria-label={`Retest ${COMPONENT_MAP[key].displayName}`}
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${isRetesting || component.status === 'checking' ? 'animate-spin' : ''}`} />
                    </button>
                    <span className={`text-xs px-2 py-1 rounded-full font-medium ${
                      component.status === 'healthy' ? 'bg-green-100 text-green-700' :
                      component.status === 'unhealthy' ? 'bg-red-100 text-red-700' :
                      component.status === 'degraded' ? 'bg-yellow-100 text-yellow-700' :
                      component.status === 'checking' ? 'bg-blue-100 text-blue-700' :
                      'bg-gray-100 text-gray-700'
                    }`}>
                      {component.status}
                    </span>
                  </div>
                </div>

                <p className="text-sm text-gray-700 mb-3">{component.message}</p>

                {/* Additional component details */}
                {component.status !== 'checking' && (
                  <div className="space-y-1 text-xs text-gray-600">
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
                    {component.tables && Object.keys(component.tables).length > 0 && (
                      <div className="mt-2 pt-2 border-t border-gray-200">
                        <span className="font-medium block mb-1">Tables:</span>
                        {Object.entries(component.tables).map(([table, count]) => (
                          <div key={table} className="flex justify-between ml-2">
                            <span className="capitalize">{table.replace(/_/g, ' ')}:</span>
                            <span>{count}</span>
                          </div>
                        ))}
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
                    {component.worker_count !== undefined && (
                      <div className="flex justify-between">
                        <span className="font-medium">Workers:</span>
                        <span>{component.worker_count}</span>
                      </div>
                    )}
                    {component.model && (
                      <div className="flex justify-between">
                        <span className="font-medium">Model:</span>
                        <span className="truncate ml-2" title={component.model}>
                          {component.model}
                        </span>
                      </div>
                    )}
                    {component.endpoint && (
                      <div className="flex justify-between">
                        <span className="font-medium">Endpoint:</span>
                        <span className="truncate ml-2" title={component.endpoint}>
                          {component.endpoint.replace(/^https?:\/\//, '')}
                        </span>
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
                        <span className="font-medium">Tenant ID:</span>
                        <span className="truncate ml-2" title={component.tenant_id}>
                          {component.tenant_id.substring(0, 8)}...
                        </span>
                      </div>
                    )}
                    {component.graph_endpoint && (
                      <div className="flex justify-between">
                        <span className="font-medium">Graph API:</span>
                        <span className="truncate ml-2" title={component.graph_endpoint}>
                          {component.graph_endpoint.replace(/^https?:\/\//, '')}
                        </span>
                      </div>
                    )}
                    {component.configured !== undefined && (
                      <div className="flex justify-between">
                        <span className="font-medium">Configured:</span>
                        <span>{component.configured ? 'Yes' : 'No'}</span>
                      </div>
                    )}
                    {component.authenticated !== undefined && (
                      <div className="flex justify-between">
                        <span className="font-medium">Authenticated:</span>
                        <span>{component.authenticated ? 'Yes' : 'No'}</span>
                      </div>
                    )}
                    {component.active_tasks && Object.keys(component.active_tasks).length > 0 && (
                      <div className="mt-2 pt-2 border-t border-gray-200">
                        <span className="font-medium">Active Tasks:</span>
                        {Object.entries(component.active_tasks).map(([worker, count]) => (
                          <div key={worker} className="flex justify-between ml-2 mt-1">
                            <span className="truncate" title={worker}>{worker.split('@')[1] || worker}</span>
                            <span>{count}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

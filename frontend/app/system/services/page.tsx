'use client'

/**
 * System Services page.
 *
 * Manage system-scoped services like LLM providers, extraction, etc.
 */

import { useState, useEffect } from 'react'
import {
  Server,
  CheckCircle,
  XCircle,
  RefreshCw,
  Brain,
  FileText,
  Globe,
  Database,
  Radio,
  Share2,
  HardDrive,
} from 'lucide-react'
import { servicesApi, Service } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import toast from 'react-hot-toast'

const serviceIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  llm: Brain,
  extraction: FileText,
  browser: Globe,
  storage: HardDrive,
  queue: Radio,
  database: Database,
  microsoft_graph: Share2,
  default: Server,
}

export default function SystemServicesPage() {
  const { token } = useAuth()
  const [services, setServices] = useState<Service[]>([])
  const [isLoading, setIsLoading] = useState(true)

  const loadServices = async () => {
    if (!token) return

    try {
      const response = await servicesApi.list(token)
      setServices(response.services || [])
    } catch (error) {
      console.error('Failed to load services:', error)
      toast.error('Failed to load services')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadServices()
  }, [token])

  const getServiceIcon = (serviceType: string) => {
    const Icon = serviceIcons[serviceType] || serviceIcons.default
    return Icon
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
            System Services
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            System-wide infrastructure services defined in config.yml
          </p>
        </div>
        <button
          onClick={loadServices}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {/* Services Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {services.map((service) => {
          const Icon = getServiceIcon(service.service_type)
          return (
            <div
              key={service.id}
              className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 hover:border-amber-300 dark:hover:border-amber-700 transition-colors"
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-amber-100 dark:bg-amber-900/30 rounded-lg">
                    <Icon className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-gray-900 dark:text-white capitalize">
                      {service.name}
                    </h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {service.description || service.service_type}
                    </p>
                  </div>
                </div>
                {service.is_active ? (
                  <span className="flex items-center gap-1 px-2 py-1 text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400 rounded-full">
                    <CheckCircle className="h-3 w-3" />
                    Active
                  </span>
                ) : (
                  <span className="flex items-center gap-1 px-2 py-1 text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400 rounded-full">
                    <XCircle className="h-3 w-3" />
                    Inactive
                  </span>
                )}
              </div>

              {/* Configuration details */}
              {service.config && Object.keys(service.config).length > 0 && (
                <div className="space-y-1 text-xs text-gray-600 dark:text-gray-400 pt-3 border-t border-gray-200/50 dark:border-gray-700/50">
                  {Object.entries(service.config).map(([key, value]) => {
                    // Nested object: render as a sub-section (e.g. queue types)
                    if (value && typeof value === 'object' && !Array.isArray(value)) {
                      return (
                        <div key={key} className="pt-2">
                          <span className="font-semibold capitalize text-gray-700 dark:text-gray-300">
                            {key.replace(/_/g, ' ')}
                          </span>
                          <div className="mt-1 space-y-2">
                            {Object.entries(value as Record<string, unknown>).map(([subKey, subVal]) => (
                              <div key={subKey} className="pl-2 border-l-2 border-gray-200 dark:border-gray-700">
                                <span className="font-medium text-gray-700 dark:text-gray-300">{subKey}</span>
                                {subVal && typeof subVal === 'object' && !Array.isArray(subVal) ? (
                                  <div className="ml-2 space-y-0.5">
                                    {Object.entries(subVal as Record<string, unknown>).map(([k, v]) => (
                                      <div key={k} className="flex justify-between">
                                        <span className="capitalize">{k.replace(/_/g, ' ')}:</span>
                                        <span>{v === null ? '—' : typeof v === 'boolean' ? (v ? 'Yes' : 'No') : String(v)}</span>
                                      </div>
                                    ))}
                                  </div>
                                ) : (
                                  <span className="ml-2">{String(subVal)}</span>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )
                    }
                    // Simple value
                    return (
                      <div key={key} className="flex justify-between">
                        <span className="font-medium capitalize">{key.replace(/_/g, ' ')}:</span>
                        <span className="truncate ml-2 text-right max-w-[60%]" title={String(value)}>
                          {typeof value === 'boolean' ? (value ? 'Yes' : 'No')
                           : Array.isArray(value) ? value.join(', ')
                           : value === null ? '—'
                           : String(value)}
                        </span>
                      </div>
                    )
                  })}
                </div>
              )}

            </div>
          )
        })}
      </div>

      {services.length === 0 && (
        <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
          <Server className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
          <p className="text-gray-500 dark:text-gray-400 mb-4">
            No services configured
          </p>
          <p className="text-sm text-gray-400 dark:text-gray-500">
            Services are defined in config.yml and synced on backend startup.
          </p>
        </div>
      )}
    </div>
  )
}

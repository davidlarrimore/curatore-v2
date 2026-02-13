'use client'

/**
 * System Services page.
 *
 * Manage system-scoped services like LLM providers, extraction, etc.
 */

import { useState, useEffect } from 'react'
import {
  Server,
  Plus,
  Settings,
  CheckCircle,
  XCircle,
  RefreshCw,
  Brain,
  FileText,
  Globe,
} from 'lucide-react'
import { servicesApi, Service } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import toast from 'react-hot-toast'

const serviceIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  llm: Brain,
  extraction: FileText,
  browser: Globe,
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
            Configure system-wide infrastructure services
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadServices}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          <button className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-amber-600 rounded-lg hover:bg-amber-700 transition-colors">
            <Plus className="h-4 w-4" />
            Add Service
          </button>
        </div>
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
                      {service.service_type}
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

              <div className="mt-4">
                <button className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors w-full justify-center">
                  <Settings className="h-4 w-4" />
                  Configure
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {services.length === 0 && (
        <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
          <Server className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
          <p className="text-gray-500 dark:text-gray-400 mb-4">
            No services configured yet
          </p>
          <p className="text-sm text-gray-400 dark:text-gray-500">
            Add system services like LLM providers, extraction engines, and browser automation.
          </p>
        </div>
      )}
    </div>
  )
}

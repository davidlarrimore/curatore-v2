'use client'

/**
 * System Connections page.
 *
 * Manage system-scoped connections (SharePoint, Salesforce, SAM.gov, etc.)
 */

import { useState, useEffect } from 'react'
import {
  Plug,
  Plus,
  Settings,
  CheckCircle,
  XCircle,
  Building2,
  RefreshCw,
} from 'lucide-react'
import { useAuth } from '@/lib/auth-context'
import toast from 'react-hot-toast'

interface Connection {
  id: string
  name: string
  connection_type: string
  scope: string
  is_active: boolean
  organization_id: string | null
  enabled_org_count?: number
}

export default function SystemConnectionsPage() {
  const { token } = useAuth()
  const [connections, setConnections] = useState<Connection[]>([])
  const [isLoading, setIsLoading] = useState(true)

  const loadConnections = async () => {
    if (!token) return

    try {
      // For now, show a placeholder since we don't have the system connections endpoint yet
      setConnections([])
    } catch (error) {
      console.error('Failed to load connections:', error)
      toast.error('Failed to load connections')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadConnections()
  }, [token])

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
            System Connections
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Manage external data source connections
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadConnections}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          <button className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-amber-600 rounded-lg hover:bg-amber-700 transition-colors">
            <Plus className="h-4 w-4" />
            Add Connection
          </button>
        </div>
      </div>

      {/* Connections Table */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead className="bg-gray-50 dark:bg-gray-900/50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Connection
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Type
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Scope
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Enabled Orgs
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
            {connections.map((connection) => (
              <tr key={connection.id} className="hover:bg-gray-50 dark:hover:bg-gray-900/30">
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-amber-100 dark:bg-amber-900/30 rounded-lg">
                      <Plug className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                    </div>
                    <span className="font-medium text-gray-900 dark:text-white">
                      {connection.name}
                    </span>
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <span className="text-sm text-gray-500 dark:text-gray-400">
                    {connection.connection_type}
                  </span>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <span className={`px-2 py-1 text-xs font-medium rounded-full ${
                    connection.scope === 'system'
                      ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400'
                      : 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400'
                  }`}>
                    {connection.scope}
                  </span>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400">
                    <Building2 className="h-4 w-4" />
                    <span>{connection.enabled_org_count || 0}</span>
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  {connection.is_active ? (
                    <span className="flex items-center gap-1 text-sm text-green-600 dark:text-green-400">
                      <CheckCircle className="h-4 w-4" />
                      Active
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400">
                      <XCircle className="h-4 w-4" />
                      Inactive
                    </span>
                  )}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-right">
                  <button className="p-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
                    <Settings className="h-4 w-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {connections.length === 0 && (
          <div className="text-center py-12">
            <Plug className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <p className="text-gray-500 dark:text-gray-400 mb-2">
              No system connections configured
            </p>
            <p className="text-sm text-gray-400 dark:text-gray-500">
              Create system-scoped connections that can be enabled per organization.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

'use client'

import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '@/lib/auth-context'
import { connectionsApi } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { RefreshCw, Plus, Link2, Zap, FolderSync, FileText } from 'lucide-react'
import ConnectionForm from '@/components/connections/ConnectionForm'
import ConnectionCard from '@/components/connections/ConnectionCard'

interface Connection {
  id: string
  name: string
  connection_type: string
  config: Record<string, any>
  is_default: boolean
  is_active: boolean
  is_managed?: boolean
  managed_by?: string
  last_tested_at?: string
  health_status?: 'healthy' | 'unhealthy' | 'unknown' | 'checking'
  test_result?: Record<string, any> | null
  created_at: string
  updated_at: string
}

interface ConnectionsTabProps {
  onError?: (message: string) => void
}

export default function ConnectionsTab({ onError }: ConnectionsTabProps) {
  const { token } = useAuth()
  const [connections, setConnections] = useState<Connection[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editingConnection, setEditingConnection] = useState<Connection | null>(null)
  const [checkingConnections, setCheckingConnections] = useState<Set<string>>(new Set())
  const [isRefreshingAll, setIsRefreshingAll] = useState(false)

  // Test a single connection's health
  const testConnectionHealth = useCallback(async (connectionId: string) => {
    if (!token) return

    // Mark as checking
    setCheckingConnections(prev => new Set(prev).add(connectionId))

    try {
      const result = await connectionsApi.testConnection(token, connectionId)
      // Update the connection's health status
      setConnections(prev => prev.map(conn =>
        conn.id === connectionId
          ? {
              ...conn,
              health_status: result.success ? 'healthy' : 'unhealthy',
              last_tested_at: new Date().toISOString(),
              test_result: {
                success: result.success,
                message: result.message,
                details: result.details,
                error: result.error,
              }
            }
          : conn
      ))
    } catch (err) {
      // Mark as unhealthy on error
      setConnections(prev => prev.map(conn =>
        conn.id === connectionId
          ? {
              ...conn,
              health_status: 'unhealthy',
              last_tested_at: new Date().toISOString(),
              test_result: {
                success: false,
                message: 'Connection test failed',
              }
            }
          : conn
      ))
    } finally {
      setCheckingConnections(prev => {
        const next = new Set(prev)
        next.delete(connectionId)
        return next
      })
    }
  }, [token])

  // Test all connections' health
  const testAllConnectionsHealth = useCallback(async (conns: Connection[]) => {
    if (!token || conns.length === 0) return

    // Mark all as checking
    const allIds = new Set(conns.map(c => c.id))
    setCheckingConnections(allIds)

    // Test all in parallel
    await Promise.all(conns.map(conn => testConnectionHealth(conn.id)))
  }, [token, testConnectionHealth])

  // Load connections
  const loadConnections = async (autoTest = true) => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const response = await connectionsApi.listConnections(token)
      // Set all to 'checking' initially if we're going to auto-test
      const connectionsWithCheckingStatus = autoTest
        ? response.connections.map((c: Connection) => ({ ...c, health_status: 'checking' as const }))
        : response.connections
      setConnections(connectionsWithCheckingStatus)

      // Auto-test all connections after loading
      if (autoTest && response.connections.length > 0) {
        // Use setTimeout to allow UI to render first
        setTimeout(() => {
          testAllConnectionsHealth(response.connections)
        }, 100)
      }
    } catch (err: any) {
      const message = err.message || 'Failed to load connections'
      setError(message)
      onError?.(message)
    } finally {
      setIsLoading(false)
    }
  }

  // Refresh all connections
  const handleRefreshAll = async () => {
    setIsRefreshingAll(true)
    // Set all to checking state
    setConnections(prev => prev.map(c => ({ ...c, health_status: 'checking' as const })))
    await testAllConnectionsHealth(connections)
    setIsRefreshingAll(false)
  }

  useEffect(() => {
    if (token) {
      loadConnections()
    }
  }, [token])

  const handleCreateConnection = () => {
    setEditingConnection(null)
    setShowForm(true)
  }

  const handleEditConnection = (connection: Connection) => {
    setEditingConnection(connection)
    setShowForm(true)
  }

  const handleDeleteConnection = async (connectionId: string) => {
    if (!token) return
    if (!confirm('Are you sure you want to delete this connection?')) return

    try {
      await connectionsApi.deleteConnection(token, connectionId)
      await loadConnections(false)
    } catch (err: any) {
      alert(`Failed to delete connection: ${err.message}`)
    }
  }

  const handleTestConnection = async (connectionId: string) => {
    await testConnectionHealth(connectionId)
  }

  const handleSetDefault = async (connectionId: string) => {
    if (!token) return

    try {
      await connectionsApi.setDefaultConnection(token, connectionId)
      await loadConnections(false)
    } catch (err: any) {
      alert(`Failed to set default connection: ${err.message}`)
    }
  }

  const handleFormSuccess = async () => {
    setShowForm(false)
    setEditingConnection(null)
    await loadConnections()
  }

  const handleFormCancel = () => {
    setShowForm(false)
    setEditingConnection(null)
  }

  // Group connections by type
  const connectionsByType = connections.reduce((acc, conn) => {
    if (!acc[conn.connection_type]) {
      acc[conn.connection_type] = []
    }
    acc[conn.connection_type].push(conn)
    return acc
  }, {} as Record<string, Connection[]>)

  const typeConfig: Record<string, { name: string; description: string; icon: React.ReactNode; gradient: string }> = {
    llm: {
      name: 'LLM Providers',
      description: 'AI language models for document processing',
      icon: <Zap className="w-4 h-4" />,
      gradient: 'from-violet-500 to-purple-600'
    },
    sharepoint: {
      name: 'SharePoint',
      description: 'Microsoft SharePoint document libraries',
      icon: <FolderSync className="w-4 h-4" />,
      gradient: 'from-blue-500 to-cyan-500'
    },
    extraction: {
      name: 'Extraction Services',
      description: 'Document conversion engines',
      icon: <FileText className="w-4 h-4" />,
      gradient: 'from-emerald-500 to-teal-500'
    }
  }

  // Calculate health stats
  const healthStats = connections.reduce(
    (acc, conn) => {
      if (conn.health_status === 'healthy') acc.healthy++
      else if (conn.health_status === 'unhealthy') acc.unhealthy++
      else acc.unknown++
      return acc
    },
    { healthy: 0, unhealthy: 0, unknown: 0 }
  )

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <div className="w-10 h-10 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin"></div>
        <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">Loading connections...</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Connections</h2>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-0.5">
            Manage integrations with external services
          </p>
        </div>
        <div className="flex items-center gap-2">
          {connections.length > 0 && (
            <Button
              variant="secondary"
              size="sm"
              onClick={handleRefreshAll}
              disabled={isRefreshingAll || checkingConnections.size > 0}
            >
              <RefreshCw className={`w-4 h-4 ${isRefreshingAll || checkingConnections.size > 0 ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline ml-1.5">Refresh</span>
            </Button>
          )}
          <Button size="sm" onClick={handleCreateConnection}>
            <Plus className="w-4 h-4" />
            <span className="ml-1.5">New Connection</span>
          </Button>
        </div>
      </div>

      {/* Stats Bar */}
      {connections.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300">
            <span className="font-medium">{connections.length}</span>
            <span>total</span>
          </div>
          {healthStats.healthy > 0 && (
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
              <span className="font-medium">{healthStats.healthy}</span>
              <span>healthy</span>
            </div>
          )}
          {healthStats.unhealthy > 0 && (
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500"></span>
              <span className="font-medium">{healthStats.unhealthy}</span>
              <span>unhealthy</span>
            </div>
          )}
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-3">
          <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
        </div>
      )}

      {/* Form */}
      {showForm && (
        <div className="mb-6">
          <ConnectionForm
            connection={editingConnection}
            onSuccess={handleFormSuccess}
            onCancel={handleFormCancel}
          />
        </div>
      )}

      {/* Content */}
      {connections.length === 0 && !showForm ? (
        /* Empty State */
        <div className="relative overflow-hidden rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 px-6 py-12 text-center">
          <div className="mx-auto w-14 h-14 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/25 mb-4">
            <Link2 className="w-7 h-7 text-white" />
          </div>
          <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-1">
            No connections configured
          </h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 max-w-sm mx-auto mb-6">
            Connect your LLM providers, SharePoint, and extraction services.
          </p>
          <Button onClick={handleCreateConnection} size="sm">
            <Plus className="w-4 h-4 mr-1.5" />
            Create your first connection
          </Button>
        </div>
      ) : !showForm && (
        /* Connection List by Type */
        <div className="space-y-6">
          {Object.entries(connectionsByType).map(([type, conns]) => {
            const config = typeConfig[type] || {
              name: type,
              description: '',
              icon: <Link2 className="w-4 h-4" />,
              gradient: 'from-gray-500 to-gray-600'
            }

            return (
              <section key={type}>
                {/* Section Header */}
                <div className="flex items-center gap-3 mb-3">
                  <div className={`w-8 h-8 rounded-lg bg-gradient-to-br ${config.gradient} flex items-center justify-center text-white shadow`}>
                    {config.icon}
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
                        {config.name}
                      </h3>
                      <span className="px-1.5 py-0.5 text-xs font-medium rounded bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400">
                        {conns.length}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Connection Cards Grid */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  {conns.map((connection) => (
                    <ConnectionCard
                      key={connection.id}
                      connection={connection}
                      isChecking={checkingConnections.has(connection.id)}
                      onEdit={() => handleEditConnection(connection)}
                      onDelete={() => handleDeleteConnection(connection.id)}
                      onTest={() => handleTestConnection(connection.id)}
                      onSetDefault={() => handleSetDefault(connection.id)}
                    />
                  ))}
                </div>
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}

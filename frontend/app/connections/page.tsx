'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { connectionsApi } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { RefreshCw, Plus, Link2, Zap, FolderSync, FileText, ArrowRight } from 'lucide-react'
import ConnectionForm from '@/components/connections/ConnectionForm'
import ConnectionCard from '@/components/connections/ConnectionCard'
import ProtectedRoute from '@/components/auth/ProtectedRoute'

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

export default function ConnectionsPage() {
  return (
    <ProtectedRoute>
      <ConnectionsContent />
    </ProtectedRoute>
  )
}

function ConnectionsContent() {
  const router = useRouter()
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
      setError(err.message || 'Failed to load connections')
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
      description: 'AI language models for document processing and optimization',
      icon: <Zap className="w-5 h-5" />,
      gradient: 'from-violet-500 to-purple-600'
    },
    sharepoint: {
      name: 'SharePoint',
      description: 'Microsoft SharePoint document libraries and sites',
      icon: <FolderSync className="w-5 h-5" />,
      gradient: 'from-blue-500 to-cyan-500'
    },
    extraction: {
      name: 'Extraction Services',
      description: 'Document conversion and text extraction engines',
      icon: <FileText className="w-5 h-5" />,
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

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25">
                <Link2 className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  Connections
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  Manage integrations with external services
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {connections.length > 0 && (
                <Button
                  variant="secondary"
                  onClick={handleRefreshAll}
                  disabled={isRefreshingAll || checkingConnections.size > 0}
                  className="gap-2"
                >
                  <RefreshCw className={`w-4 h-4 ${isRefreshingAll || checkingConnections.size > 0 ? 'animate-spin' : ''}`} />
                  <span className="hidden sm:inline">Refresh All</span>
                </Button>
              )}
              <Button onClick={handleCreateConnection} className="gap-2 shadow-lg shadow-blue-500/25">
                <Plus className="w-4 h-4" />
                <span>New Connection</span>
              </Button>
            </div>
          </div>

          {/* Stats Bar */}
          {connections.length > 0 && !isLoading && (
            <div className="mt-6 flex flex-wrap items-center gap-4 text-sm">
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300">
                <span className="font-medium">{connections.length}</span>
                <span>total</span>
              </div>
              {healthStats.healthy > 0 && (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400">
                  <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                  <span className="font-medium">{healthStats.healthy}</span>
                  <span>healthy</span>
                </div>
              )}
              {healthStats.unhealthy > 0 && (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400">
                  <span className="w-2 h-2 rounded-full bg-red-500"></span>
                  <span className="font-medium">{healthStats.unhealthy}</span>
                  <span>unhealthy</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Error State */}
        {error && (
          <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
            <div className="flex items-center gap-3">
              <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                <svg className="w-5 h-5 text-red-600 dark:text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
            </div>
          </div>
        )}

        {/* Form */}
        {showForm && (
          <div className="mb-8">
            <ConnectionForm
              connection={editingConnection}
              onSuccess={handleFormSuccess}
              onCancel={handleFormCancel}
            />
          </div>
        )}

        {/* Content */}
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin"></div>
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading connections...</p>
          </div>
        ) : connections.length === 0 ? (
          /* Empty State */
          <div className="relative overflow-hidden rounded-2xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/50 px-6 py-16 text-center">
            {/* Background decoration */}
            <div className="absolute inset-0 pointer-events-none">
              <div className="absolute -top-24 -right-24 w-64 h-64 rounded-full bg-gradient-to-br from-indigo-500/5 to-purple-500/5 blur-3xl"></div>
              <div className="absolute -bottom-24 -left-24 w-64 h-64 rounded-full bg-gradient-to-br from-blue-500/5 to-cyan-500/5 blur-3xl"></div>
            </div>

            <div className="relative">
              <div className="mx-auto w-20 h-20 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-xl shadow-indigo-500/25 mb-6">
                <Link2 className="w-10 h-10 text-white" />
              </div>
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                No connections configured
              </h3>
              <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto mb-8">
                Connect your LLM providers, SharePoint, and extraction services to start processing documents.
              </p>

              <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
                <Button onClick={handleCreateConnection} size="lg" className="gap-2 shadow-lg shadow-blue-500/25">
                  <Plus className="w-5 h-5" />
                  Create your first connection
                </Button>
              </div>

              {/* Quick start hints */}
              <div className="mt-12 grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-2xl mx-auto">
                {Object.entries(typeConfig).map(([type, config]) => (
                  <button
                    key={type}
                    onClick={handleCreateConnection}
                    className="group flex flex-col items-center p-4 rounded-xl bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 transition-all"
                  >
                    <div className={`w-10 h-10 rounded-lg bg-gradient-to-br ${config.gradient} flex items-center justify-center text-white mb-3 group-hover:scale-110 transition-transform`}>
                      {config.icon}
                    </div>
                    <span className="text-sm font-medium text-gray-900 dark:text-white">{config.name}</span>
                    <ArrowRight className="w-4 h-4 mt-2 text-gray-400 group-hover:text-gray-600 dark:group-hover:text-gray-300 group-hover:translate-x-1 transition-all" />
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          /* Connection List by Type */
          <div className="space-y-10">
            {Object.entries(connectionsByType).map(([type, conns]) => {
              const config = typeConfig[type] || {
                name: type,
                description: '',
                icon: <Link2 className="w-5 h-5" />,
                gradient: 'from-gray-500 to-gray-600'
              }

              return (
                <section key={type}>
                  {/* Section Header */}
                  <div className="flex items-center gap-4 mb-5">
                    <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${config.gradient} flex items-center justify-center text-white shadow-lg`}>
                      {config.icon}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-3">
                        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                          {config.name}
                        </h2>
                        <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400">
                          {conns.length}
                        </span>
                      </div>
                      {config.description && (
                        <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                          {config.description}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Connection Cards Grid */}
                  <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
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
    </div>
  )
}

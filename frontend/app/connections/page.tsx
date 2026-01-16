'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { connectionsApi } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { RefreshCw } from 'lucide-react'
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
              last_tested_at: new Date().toISOString()
            }
          : conn
      ))
    } catch (err) {
      // Mark as unhealthy on error
      setConnections(prev => prev.map(conn =>
        conn.id === connectionId
          ? { ...conn, health_status: 'unhealthy', last_tested_at: new Date().toISOString() }
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

  const typeDisplayNames: Record<string, string> = {
    llm: 'LLM Providers',
    sharepoint: 'SharePoint',
    extraction: 'Extraction Services'
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-7xl">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Connections</h1>
          <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
            Manage your LLM providers, SharePoint, and extraction service connections
          </p>
        </div>
        <div className="flex items-center space-x-3">
          {connections.length > 0 && (
            <Button
              variant="secondary"
              onClick={handleRefreshAll}
              disabled={isRefreshingAll || checkingConnections.size > 0}
              className="flex items-center space-x-2"
            >
              <RefreshCw className={`w-4 h-4 ${isRefreshingAll || checkingConnections.size > 0 ? 'animate-spin' : ''}`} />
              <span>Refresh All</span>
            </Button>
          )}
          <Button onClick={handleCreateConnection}>
            + New Connection
          </Button>
        </div>
      </div>

      {error && (
        <div className="mb-6 rounded-md bg-red-50 dark:bg-red-900/20 p-4">
          <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
        </div>
      )}

      {showForm && (
        <div className="mb-8">
          <ConnectionForm
            connection={editingConnection}
            onSuccess={handleFormSuccess}
            onCancel={handleFormCancel}
          />
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-12">
          <p className="text-gray-600 dark:text-gray-400">Loading connections...</p>
        </div>
      ) : connections.length === 0 ? (
        <div className="text-center py-12 bg-gray-50 dark:bg-gray-800 rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-600">
          <p className="text-gray-600 dark:text-gray-400 mb-4">No connections configured yet</p>
          <Button onClick={handleCreateConnection}>
            Create your first connection
          </Button>
        </div>
      ) : (
        <div className="space-y-8">
          {Object.entries(connectionsByType).map(([type, conns]) => (
            <div key={type}>
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
                {typeDisplayNames[type] || type}
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
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
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

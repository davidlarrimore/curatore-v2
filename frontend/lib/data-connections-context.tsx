'use client'

/**
 * Data Connections context provider.
 *
 * Loads the per-org data connection statuses from the API and exposes
 * helpers to check whether a specific data connection is enabled.
 * Used primarily by the sidebar to conditionally show navigation items.
 *
 * Defaults to all-enabled while loading so features aren't hidden during
 * the initial fetch.  Falls back to all-enabled on error.
 */

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { dataConnectionsApi, type DataConnectionStatus } from './api'
import { useOrganization } from './organization-context'

interface DataConnectionsContextType {
  /** Map of source_type -> is_enabled */
  connections: Record<string, boolean>
  /** Check if a single source type is enabled */
  isEnabled: (sourceType: string) => boolean
  /** Check if ANY of the given source types are enabled (OR logic) */
  isAnyEnabled: (...sourceTypes: string[]) => boolean
  /** Whether the initial load is complete */
  loaded: boolean
  /** Trigger a refresh */
  refresh: () => void
}

const DataConnectionsContext = createContext<DataConnectionsContextType>({
  connections: {},
  isEnabled: () => true,
  isAnyEnabled: () => true,
  loaded: false,
  refresh: () => {},
})

export function DataConnectionsProvider({ children }: { children: React.ReactNode }) {
  const { currentOrganization, mode } = useOrganization()
  const [connections, setConnections] = useState<Record<string, boolean>>({})
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(async () => {
    // In system mode (no org), don't load — default to all enabled
    if (mode === 'system' || !currentOrganization) {
      setConnections({})
      setLoaded(true)
      return
    }

    try {
      const data = await dataConnectionsApi.getMyConnections()
      const map: Record<string, boolean> = {}
      for (const dc of data.data_connections) {
        map[dc.source_type] = dc.is_enabled
      }
      setConnections(map)
    } catch (err) {
      console.warn('Failed to load data connections, defaulting to all enabled:', err)
      setConnections({})
    } finally {
      setLoaded(true)
    }
  }, [currentOrganization?.id, mode])

  useEffect(() => {
    setLoaded(false)
    load()
  }, [load])

  const isEnabled = useCallback(
    (sourceType: string) => {
      // While loading or no data, default to true (don't hide features)
      if (!loaded || Object.keys(connections).length === 0) return true
      return connections[sourceType] ?? true
    },
    [connections, loaded],
  )

  const isAnyEnabled = useCallback(
    (...sourceTypes: string[]) => {
      if (!loaded || Object.keys(connections).length === 0) return true
      return sourceTypes.some((st) => connections[st] ?? true)
    },
    [connections, loaded],
  )

  return (
    <DataConnectionsContext.Provider value={{ connections, isEnabled, isAnyEnabled, loaded, refresh: load }}>
      {children}
    </DataConnectionsContext.Provider>
  )
}

export function useDataConnections() {
  return useContext(DataConnectionsContext)
}

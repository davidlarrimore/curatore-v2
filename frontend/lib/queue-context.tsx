'use client'

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  ReactNode,
} from 'react'
import { useAuth } from './auth-context'
import { queueAdminApi } from './api'
import { POLLING, isDocumentVisible } from './polling-config'

/**
 * Unified queue statistics interface.
 * Matches the backend UnifiedQueueStatsResponse model.
 */
export interface UnifiedQueueStats {
  extraction_queue: {
    pending: number
    submitted: number
    running: number
    max_concurrent: number
  }
  celery_queues: {
    processing_priority: number
    extraction: number
    sam: number
    scrape: number
    sharepoint: number
    maintenance: number
  }
  throughput: {
    per_minute: number
    avg_extraction_seconds: number | null
  }
  recent_24h: {
    completed: number
    failed: number
    timed_out: number
  }
  workers: {
    active: number
    tasks_running: number
  }
}

/**
 * Queue context state.
 */
export interface QueueState {
  /** Current queue statistics (null if not yet loaded) */
  stats: UnifiedQueueStats | null
  /** Whether the initial load is in progress */
  isLoading: boolean
  /** Error message if stats failed to load */
  error: string | null
  /** When stats were last successfully updated */
  lastUpdated: Date | null
  /** Manually refresh stats */
  refresh: () => Promise<void>
  /** Count of active extractions (pending + submitted + running) */
  activeCount: number
}

const QueueContext = createContext<QueueState | undefined>(undefined)

interface QueueProviderProps {
  children: ReactNode
}

/**
 * QueueProvider provides centralized queue state polling.
 *
 * - Polls /api/v1/queue/unified every 5 seconds (configurable)
 * - Pauses polling when the tab is not visible
 * - Shares state across all components via context
 *
 * Usage:
 * ```tsx
 * // In layout.tsx
 * <QueueProvider>
 *   {children}
 * </QueueProvider>
 *
 * // In components
 * const { stats, isLoading, activeCount } = useQueue()
 * ```
 */
export function QueueProvider({ children }: QueueProviderProps) {
  const { accessToken, isAuthenticated } = useAuth()
  const [stats, setStats] = useState<UnifiedQueueStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const fetchStats = useCallback(async () => {
    if (!accessToken || !isAuthenticated) {
      setIsLoading(false)
      return
    }

    try {
      const data = await queueAdminApi.getUnifiedStats(accessToken)
      setStats(data)
      setError(null)
      setLastUpdated(new Date())
    } catch (err: any) {
      // Don't overwrite existing stats on error - just log it
      console.warn('Failed to fetch queue stats:', err.message)
      // Only set error if we have no stats yet
      if (!stats) {
        setError(err.message || 'Failed to load queue stats')
      }
    } finally {
      setIsLoading(false)
    }
  }, [accessToken, isAuthenticated, stats])

  // Initial fetch and polling
  useEffect(() => {
    if (!accessToken || !isAuthenticated) {
      setIsLoading(false)
      return
    }

    // Initial fetch
    fetchStats()

    // Set up polling interval
    const intervalId = setInterval(() => {
      // Skip if tab is hidden
      if (POLLING.PAUSE_ON_HIDDEN && !isDocumentVisible()) {
        return
      }
      fetchStats()
    }, POLLING.QUEUE_STATS_MS)

    return () => clearInterval(intervalId)
  }, [accessToken, isAuthenticated, fetchStats])

  // Calculate active count
  const activeCount = stats
    ? stats.extraction_queue.pending +
      stats.extraction_queue.submitted +
      stats.extraction_queue.running
    : 0

  const refresh = useCallback(async () => {
    await fetchStats()
  }, [fetchStats])

  const value: QueueState = {
    stats,
    isLoading,
    error,
    lastUpdated,
    refresh,
    activeCount,
  }

  return <QueueContext.Provider value={value}>{children}</QueueContext.Provider>
}

/**
 * Hook to access queue state from any component.
 *
 * @throws Error if used outside of QueueProvider
 */
export function useQueue(): QueueState {
  const context = useContext(QueueContext)
  if (context === undefined) {
    throw new Error('useQueue must be used within a QueueProvider')
  }
  return context
}

/**
 * Hook to check if any extractions are currently active.
 * Useful for showing loading indicators.
 */
export function useHasActiveExtractions(): boolean {
  const { activeCount } = useQueue()
  return activeCount > 0
}

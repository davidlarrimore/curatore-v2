/**
 * WebSocket Client for Real-Time Job Updates
 *
 * Provides a WebSocket client with automatic reconnection, exponential backoff,
 * and fallback to polling when WebSocket is unavailable.
 *
 * Usage:
 *   const client = createWebSocketClient({
 *     token: 'jwt-token',
 *     onMessage: (msg) => console.log('Received:', msg),
 *     onConnectionChange: (status) => console.log('Connection:', status),
 *   });
 *
 *   // Later...
 *   client.disconnect();
 */

import { API_BASE_URL } from './api'

// Connection status types
export type ConnectionStatus =
  | 'connecting'
  | 'connected'
  | 'disconnected'
  | 'reconnecting'
  | 'polling' // Fallback mode

// Message types from the server
export type JobUpdateMessageType =
  | 'run_status'
  | 'run_progress'
  | 'run_log'
  | 'queue_stats'
  | 'initial_state'
  | 'pong'

// Run status from backend
export interface RunStatusData {
  run_id: string
  run_type: string
  status: string
  progress: Record<string, any> | null
  results_summary: Record<string, any> | null
  error_message: string | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
  display_name?: string  // Human-readable job name
}

// Queue stats from backend
export interface QueueStatsData {
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
  recent_5m: {
    completed: number
    failed: number
    timed_out: number
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

// Run log event from backend
export interface RunLogData {
  id: string
  run_id: string
  level: string
  event_type: string
  message: string
  context: Record<string, any> | null
  created_at: string | null
}

// Initial state sent on connection
export interface InitialStateData {
  active_runs: RunStatusData[]
  queue_stats: QueueStatsData | null
}

// Message from server
export interface JobUpdateMessage {
  type: JobUpdateMessageType
  timestamp: string
  data: RunStatusData | QueueStatsData | RunLogData | InitialStateData | Record<string, any>
}

// Client configuration
export interface WebSocketClientConfig {
  /** JWT access token for authentication */
  token: string
  /** Callback for received messages */
  onMessage: (message: JobUpdateMessage) => void
  /** Callback for connection status changes */
  onConnectionChange: (status: ConnectionStatus) => void
  /** Callback when WebSocket fails and needs fallback to polling */
  onFallbackToPolling?: () => void
  /** Callback when WebSocket receives an authentication error (e.g., expired token) */
  onAuthError?: () => void
  /** Whether WebSocket is enabled (can be disabled via env var) */
  enabled?: boolean
}

// Reconnection configuration
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000] // Exponential backoff
const MAX_RECONNECT_ATTEMPTS = 5
const HEARTBEAT_INTERVAL = 30000 // 30 seconds

// WebSocket client instance
export interface WebSocketClient {
  /** Current connection status */
  getStatus: () => ConnectionStatus
  /** Manually disconnect */
  disconnect: () => void
  /** Manually reconnect */
  reconnect: () => void
  /** Check if connected */
  isConnected: () => boolean
}

/**
 * Create a WebSocket client for real-time job updates.
 *
 * The client automatically:
 * - Connects to the WebSocket endpoint
 * - Handles reconnection with exponential backoff
 * - Falls back to polling after max reconnection attempts
 * - Sends heartbeat pings to keep connection alive
 *
 * @param config - Client configuration
 * @returns WebSocket client instance
 */
export function createWebSocketClient(config: WebSocketClientConfig): WebSocketClient {
  const { token, onMessage, onConnectionChange, onFallbackToPolling, onAuthError, enabled = true } = config

  let ws: WebSocket | null = null
  let status: ConnectionStatus = 'disconnected'
  let reconnectAttempts = 0
  let reconnectTimeout: ReturnType<typeof setTimeout> | null = null
  let heartbeatInterval: ReturnType<typeof setInterval> | null = null
  let isManualDisconnect = false
  let disconnectedAt: Date | null = null
  let hasEverConnected = false

  // Build WebSocket URL
  const getWebSocketUrl = (): string => {
    // Convert HTTP(S) to WS(S)
    const wsBase = API_BASE_URL.replace(/^http/, 'ws')
    return `${wsBase}/api/v1/ops/ws/jobs?token=${encodeURIComponent(token)}`
  }

  // Update status and notify
  const setStatus = (newStatus: ConnectionStatus) => {
    if (status !== newStatus) {
      status = newStatus
      onConnectionChange(newStatus)
    }
  }

  // Start heartbeat pings
  const startHeartbeat = () => {
    stopHeartbeat()
    heartbeatInterval = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, HEARTBEAT_INTERVAL)
  }

  // Stop heartbeat pings
  const stopHeartbeat = () => {
    if (heartbeatInterval) {
      clearInterval(heartbeatInterval)
      heartbeatInterval = null
    }
  }

  // Clear reconnect timeout
  const clearReconnectTimeout = () => {
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout)
      reconnectTimeout = null
    }
  }

  // Schedule reconnection with exponential backoff
  const scheduleReconnect = () => {
    if (isManualDisconnect) return

    // If we've never connected, use fewer attempts (WebSocket likely not available)
    const maxAttempts = hasEverConnected ? MAX_RECONNECT_ATTEMPTS : 2

    if (reconnectAttempts >= maxAttempts) {
      if (!hasEverConnected) {
        console.log('WebSocket: Not available, using polling mode')
      } else {
        console.warn('WebSocket: Max reconnection attempts reached, falling back to polling')
      }
      setStatus('polling')
      onFallbackToPolling?.()
      return
    }

    const delay = RECONNECT_DELAYS[Math.min(reconnectAttempts, RECONNECT_DELAYS.length - 1)]
    // Only log reconnection attempts after successful connection
    if (hasEverConnected) {
      console.log(`WebSocket: Reconnecting in ${delay}ms (attempt ${reconnectAttempts + 1}/${maxAttempts})`)
    }

    setStatus('reconnecting')
    reconnectTimeout = setTimeout(() => {
      reconnectAttempts++
      connect()
    }, delay)
  }

  // Connect to WebSocket
  const connect = () => {
    if (!enabled) {
      console.log('WebSocket: Disabled via configuration')
      setStatus('polling')
      onFallbackToPolling?.()
      return
    }

    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
      return
    }

    setStatus('connecting')
    isManualDisconnect = false

    const wsUrl = getWebSocketUrl()

    // Only log on first attempt to reduce noise
    if (reconnectAttempts === 0) {
      console.log('WebSocket: Attempting connection to', wsUrl.replace(/token=[^&]+/, 'token=***'))
    }

    try {
      ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        console.log('WebSocket: Connected')
        hasEverConnected = true
        setStatus('connected')
        reconnectAttempts = 0
        startHeartbeat()
      }

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as JobUpdateMessage
          onMessage(message)
        } catch (e) {
          console.warn('WebSocket: Failed to parse message:', e)
        }
      }

      ws.onerror = (error) => {
        // Only log detailed error on first attempt
        if (reconnectAttempts === 0) {
          console.warn('WebSocket: Connection error (will fall back to polling if retries fail)')
        }
      }

      ws.onclose = (event) => {
        // Common close codes:
        // 1000 = Normal closure
        // 1001 = Going away (server shutdown)
        // 1006 = Abnormal closure (no close frame received)
        // 4001 = Custom: Invalid/expired token
        if (reconnectAttempts === 0 || event.code !== 1006) {
          console.log(`WebSocket: Closed (code: ${event.code}, reason: ${event.reason || 'none'})`)
        }
        stopHeartbeat()
        ws = null

        if (!isManualDisconnect) {
          disconnectedAt = new Date()

          // Don't retry if we got an auth error
          if (event.code === 4001) {
            console.warn('WebSocket: Authentication failed (token expired or invalid)')
            setStatus('disconnected')
            // Notify about auth error so the app can redirect to login
            onAuthError?.()
          } else {
            scheduleReconnect()
          }
        } else {
          setStatus('disconnected')
        }
      }
    } catch (e) {
      // If we can't even create the WebSocket, fall back immediately
      console.warn('WebSocket: Failed to create connection, falling back to polling')
      setStatus('polling')
      onFallbackToPolling?.()
    }
  }

  // Disconnect from WebSocket
  const disconnect = () => {
    isManualDisconnect = true
    clearReconnectTimeout()
    stopHeartbeat()

    if (ws) {
      ws.close(1000, 'Client disconnect')
      ws = null
    }

    setStatus('disconnected')
  }

  // Reconnect (manual)
  const reconnect = () => {
    disconnect()
    isManualDisconnect = false
    reconnectAttempts = 0
    connect()
  }

  // Get current status
  const getStatus = (): ConnectionStatus => status

  // Check if connected
  const isConnected = (): boolean => status === 'connected'

  // Get timestamp when disconnected (for state reconciliation)
  const getDisconnectedAt = (): Date | null => disconnectedAt

  // Initial connection
  connect()

  return {
    getStatus,
    disconnect,
    reconnect,
    isConnected,
  }
}

/**
 * Check if WebSocket is supported in the current environment.
 */
export function isWebSocketSupported(): boolean {
  return typeof WebSocket !== 'undefined'
}

/**
 * Check if WebSocket feature is enabled.
 * Reads from environment variable NEXT_PUBLIC_WEBSOCKET_ENABLED.
 */
export function isWebSocketEnabled(): boolean {
  if (typeof window === 'undefined') return false
  const envValue = process.env.NEXT_PUBLIC_WEBSOCKET_ENABLED
  return envValue !== 'false' && envValue !== '0'
}

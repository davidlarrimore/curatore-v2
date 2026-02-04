'use client'

/**
 * Connection Status Indicator
 *
 * Small indicator showing WebSocket connection state for real-time job updates.
 *
 * States:
 * - Green dot + "Live" when connected via WebSocket
 * - Yellow dot + "Polling" when using fallback polling
 * - Yellow dot + "Reconnecting" when attempting to reconnect
 * - Red dot + "Offline" when disconnected
 */

import { Wifi, WifiOff, RefreshCw } from 'lucide-react'
import { ConnectionStatus } from '@/lib/websocket-client'
import clsx from 'clsx'

interface ConnectionStatusIndicatorProps {
  status: ConnectionStatus
  className?: string
  variant?: 'default' | 'compact' | 'minimal'
  showLabel?: boolean
}

export function ConnectionStatusIndicator({
  status,
  className,
  variant = 'default',
  showLabel = true,
}: ConnectionStatusIndicatorProps) {
  // Get status configuration
  const getStatusConfig = () => {
    switch (status) {
      case 'connected':
        return {
          color: 'emerald',
          label: 'Live',
          icon: Wifi,
          animate: false,
        }
      case 'connecting':
        return {
          color: 'amber',
          label: 'Connecting',
          icon: RefreshCw,
          animate: true,
        }
      case 'reconnecting':
        return {
          color: 'amber',
          label: 'Reconnecting',
          icon: RefreshCw,
          animate: true,
        }
      case 'polling':
        return {
          color: 'amber',
          label: 'Polling',
          icon: RefreshCw,
          animate: false,
        }
      case 'disconnected':
      default:
        return {
          color: 'red',
          label: 'Offline',
          icon: WifiOff,
          animate: false,
        }
    }
  }

  const config = getStatusConfig()
  const Icon = config.icon

  // Color classes based on status
  const colorClasses = {
    emerald: {
      dot: 'bg-emerald-500',
      text: 'text-emerald-600 dark:text-emerald-400',
      bg: 'bg-emerald-50 dark:bg-emerald-900/20',
      border: 'border-emerald-200 dark:border-emerald-800',
    },
    amber: {
      dot: 'bg-amber-500',
      text: 'text-amber-600 dark:text-amber-400',
      bg: 'bg-amber-50 dark:bg-amber-900/20',
      border: 'border-amber-200 dark:border-amber-800',
    },
    red: {
      dot: 'bg-red-500',
      text: 'text-red-600 dark:text-red-400',
      bg: 'bg-red-50 dark:bg-red-900/20',
      border: 'border-red-200 dark:border-red-800',
    },
  }

  const colors = colorClasses[config.color as keyof typeof colorClasses]

  // Minimal variant - just the dot
  if (variant === 'minimal') {
    return (
      <span
        className={clsx(
          'inline-flex h-2 w-2 rounded-full',
          colors.dot,
          className
        )}
        title={config.label}
      />
    )
  }

  // Compact variant - dot + label
  if (variant === 'compact') {
    return (
      <span
        className={clsx(
          'inline-flex items-center gap-1.5 text-xs',
          colors.text,
          className
        )}
      >
        <span
          className={clsx(
            'h-1.5 w-1.5 rounded-full',
            colors.dot,
            config.animate && 'animate-pulse'
          )}
        />
        {showLabel && <span>{config.label}</span>}
      </span>
    )
  }

  // Default variant - pill with icon
  return (
    <div
      className={clsx(
        'inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium border',
        colors.bg,
        colors.border,
        colors.text,
        className
      )}
    >
      <span
        className={clsx(
          'relative flex h-2 w-2',
        )}
      >
        {status === 'connected' && (
          <span
            className={clsx(
              'animate-ping absolute inline-flex h-full w-full rounded-full opacity-75',
              colors.dot
            )}
          />
        )}
        <span
          className={clsx(
            'relative inline-flex rounded-full h-2 w-2',
            colors.dot
          )}
        />
      </span>
      {showLabel && <span>{config.label}</span>}
    </div>
  )
}

export default ConnectionStatusIndicator

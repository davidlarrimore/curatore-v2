'use client'

import { useState } from 'react'
import { Clock, Loader2, CheckCircle, XCircle } from 'lucide-react'
import clsx from 'clsx'

/**
 * Unified status values matching the backend UnifiedStatus enum.
 */
export type UnifiedStatusValue =
  | 'queued'
  | 'submitted'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'timed_out'
  | 'cancelled'

/**
 * Queue information for tooltip display.
 */
export interface QueueInfo {
  /** Position in the queue (1-indexed) */
  position?: number | null
  /** Total items in the queue */
  totalPending?: number | null
  /** Estimated wait time in seconds */
  estimatedWaitSeconds?: number | null
  /** Extractor version being used */
  extractorVersion?: string | null
}

interface ExtractionStatusProps {
  /** The unified status value */
  status: UnifiedStatusValue | string
  /** Queue position (shown if provided and status is queued) */
  queuePosition?: number | null
  /** Total items pending in queue */
  totalPending?: number | null
  /** Estimated wait time in seconds */
  estimatedWaitSeconds?: number | null
  /** Extractor version */
  extractorVersion?: string | null
  /** Whether to show queue position inline */
  showPosition?: boolean
  /** Whether to show tooltip on hover */
  showTooltip?: boolean
  /** Size variant */
  size?: 'sm' | 'md' | 'lg'
  /** Additional CSS classes */
  className?: string
}

/**
 * Status display configuration.
 */
interface StatusConfig {
  label: string
  color: string
  bgColor: string
  textColor: string
  icon: React.ReactNode
  animate?: boolean
  tooltipText?: string
}

/**
 * Get status configuration for display.
 */
function getStatusConfig(status: string, size: 'sm' | 'md' | 'lg'): StatusConfig {
  const iconSize = {
    sm: 'w-3 h-3',
    md: 'w-4 h-4',
    lg: 'w-5 h-5',
  }[size]

  const configs: Record<string, StatusConfig> = {
    queued: {
      label: 'Queued',
      color: 'blue',
      bgColor: 'bg-blue-100 dark:bg-blue-900/30',
      textColor: 'text-blue-700 dark:text-blue-400',
      icon: <Clock className={iconSize} />,
      tooltipText: 'Waiting in extraction queue',
    },
    submitted: {
      label: 'Starting',
      color: 'blue',
      bgColor: 'bg-blue-100 dark:bg-blue-900/30',
      textColor: 'text-blue-700 dark:text-blue-400',
      icon: <Loader2 className={clsx(iconSize, 'animate-pulse')} />,
      animate: true,
      tooltipText: 'Submitted to extraction worker',
    },
    processing: {
      label: 'Processing',
      color: 'indigo',
      bgColor: 'bg-indigo-100 dark:bg-indigo-900/30',
      textColor: 'text-indigo-700 dark:text-indigo-400',
      icon: <Loader2 className={clsx(iconSize, 'animate-spin')} />,
      animate: true,
      tooltipText: 'Extracting content from document',
    },
    completed: {
      label: 'Ready',
      color: 'emerald',
      bgColor: 'bg-emerald-100 dark:bg-emerald-900/30',
      textColor: 'text-emerald-700 dark:text-emerald-400',
      icon: <CheckCircle className={iconSize} />,
      tooltipText: 'Extraction complete',
    },
    ready: {
      label: 'Ready',
      color: 'emerald',
      bgColor: 'bg-emerald-100 dark:bg-emerald-900/30',
      textColor: 'text-emerald-700 dark:text-emerald-400',
      icon: <CheckCircle className={iconSize} />,
      tooltipText: 'Extraction complete',
    },
    failed: {
      label: 'Failed',
      color: 'red',
      bgColor: 'bg-red-100 dark:bg-red-900/30',
      textColor: 'text-red-700 dark:text-red-400',
      icon: <XCircle className={iconSize} />,
      tooltipText: 'Extraction failed',
    },
    timed_out: {
      label: 'Timed Out',
      color: 'amber',
      bgColor: 'bg-amber-100 dark:bg-amber-900/30',
      textColor: 'text-amber-700 dark:text-amber-400',
      icon: <Clock className={iconSize} />,
      tooltipText: 'Extraction timed out',
    },
    cancelled: {
      label: 'Cancelled',
      color: 'gray',
      bgColor: 'bg-gray-100 dark:bg-gray-800',
      textColor: 'text-gray-700 dark:text-gray-400',
      icon: <XCircle className={iconSize} />,
      tooltipText: 'Extraction was cancelled',
    },
    pending: {
      label: 'Queued',
      color: 'blue',
      bgColor: 'bg-blue-100 dark:bg-blue-900/30',
      textColor: 'text-blue-700 dark:text-blue-400',
      icon: <Clock className={iconSize} />,
      tooltipText: 'Waiting in extraction queue',
    },
    running: {
      label: 'Processing',
      color: 'indigo',
      bgColor: 'bg-indigo-100 dark:bg-indigo-900/30',
      textColor: 'text-indigo-700 dark:text-indigo-400',
      icon: <Loader2 className={clsx(iconSize, 'animate-spin')} />,
      animate: true,
      tooltipText: 'Extracting content from document',
    },
  }

  return (
    configs[status] || {
      label: status.charAt(0).toUpperCase() + status.slice(1).replace('_', ' '),
      color: 'gray',
      bgColor: 'bg-gray-100 dark:bg-gray-800',
      textColor: 'text-gray-700 dark:text-gray-400',
      icon: <Clock className={iconSize} />,
      tooltipText: status,
    }
  )
}

/**
 * Format wait time for display.
 */
function formatWaitTime(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${Math.round(seconds / 3600)}h`
}

/**
 * Build tooltip content based on status and queue info.
 */
function buildTooltipContent(
  config: StatusConfig,
  status: string,
  queuePosition?: number | null,
  totalPending?: number | null,
  estimatedWaitSeconds?: number | null,
  extractorVersion?: string | null
): string {
  const lines: string[] = [config.tooltipText || config.label]

  if (status === 'queued' || status === 'pending') {
    if (queuePosition && totalPending) {
      lines.push(`Position ${queuePosition} of ${totalPending}`)
    } else if (queuePosition) {
      lines.push(`Position ${queuePosition} in queue`)
    }
    if (estimatedWaitSeconds && estimatedWaitSeconds > 0) {
      lines.push(`Est. wait: ~${formatWaitTime(estimatedWaitSeconds)}`)
    }
  }

  if (extractorVersion) {
    lines.push(`Extractor: ${extractorVersion}`)
  }

  return lines.join('\n')
}

/**
 * ExtractionStatus displays a unified status badge for extraction/processing state.
 *
 * This component provides consistent status display across all pages:
 * - Assets list
 * - Asset detail page
 * - Queue admin page
 * - Status bar
 *
 * @example
 * ```tsx
 * <ExtractionStatus status="queued" queuePosition={3} totalPending={10} showTooltip />
 * <ExtractionStatus status="processing" showTooltip />
 * <ExtractionStatus status="completed" size="lg" />
 * ```
 */
export function ExtractionStatus({
  status,
  queuePosition,
  totalPending,
  estimatedWaitSeconds,
  extractorVersion,
  showPosition = false,
  showTooltip = true,
  size = 'md',
  className,
}: ExtractionStatusProps) {
  const [isHovered, setIsHovered] = useState(false)
  const config = getStatusConfig(status, size)

  const sizeClasses = {
    sm: 'px-1.5 py-0.5 text-xs gap-1',
    md: 'px-2 py-0.5 text-xs gap-1.5',
    lg: 'px-2.5 py-1 text-sm gap-2',
  }[size]

  const showQueuePosition =
    showPosition && queuePosition !== undefined && queuePosition !== null &&
    (status === 'queued' || status === 'pending')

  const tooltipContent = buildTooltipContent(
    config,
    status,
    queuePosition,
    totalPending,
    estimatedWaitSeconds,
    extractorVersion
  )

  // Only show tooltip if there's meaningful content beyond the basic label
  const hasTooltipContent = showTooltip && (
    (queuePosition && (status === 'queued' || status === 'pending')) ||
    estimatedWaitSeconds ||
    extractorVersion ||
    config.tooltipText !== config.label
  )

  return (
    <span
      className={clsx('relative inline-flex', hasTooltipContent && 'cursor-help')}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <span
        className={clsx(
          'inline-flex items-center rounded-full font-medium',
          sizeClasses,
          config.bgColor,
          config.textColor,
          className
        )}
      >
        {config.icon}
        <span>
          {config.label}
          {showQueuePosition && ` #${queuePosition}`}
        </span>
      </span>

      {/* Tooltip */}
      {hasTooltipContent && isHovered && (
        <span
          className={clsx(
            'absolute z-50 px-2 py-1.5 text-xs font-normal text-white bg-gray-900 dark:bg-gray-700',
            'rounded-lg shadow-lg whitespace-pre-line',
            'left-1/2 -translate-x-1/2 bottom-full mb-2',
            'pointer-events-none',
            // Arrow
            'after:content-[""] after:absolute after:left-1/2 after:-translate-x-1/2',
            'after:top-full after:border-4 after:border-transparent',
            'after:border-t-gray-900 dark:after:border-t-gray-700'
          )}
        >
          {tooltipContent}
        </span>
      )}
    </span>
  )
}

/**
 * Get the display label for a status without the badge styling.
 */
export function getStatusLabel(status: string): string {
  return getStatusConfig(status, 'md').label
}

/**
 * Check if a status represents an active/in-progress state.
 */
export function isActiveStatus(status: string): boolean {
  return ['queued', 'submitted', 'processing', 'pending', 'running'].includes(status)
}

/**
 * Check if a status represents a terminal/completed state.
 */
export function isTerminalStatus(status: string): boolean {
  return ['completed', 'ready', 'failed', 'timed_out', 'cancelled'].includes(status)
}

/**
 * Helper to create QueueInfo object from various sources.
 */
export function createQueueInfo(data: {
  queue_position?: number | null
  total_pending?: number | null
  estimated_wait_seconds?: number | null
  extractor_version?: string | null
}): QueueInfo {
  return {
    position: data.queue_position,
    totalPending: data.total_pending,
    estimatedWaitSeconds: data.estimated_wait_seconds,
    extractorVersion: data.extractor_version,
  }
}

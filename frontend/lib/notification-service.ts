/**
 * Notification Service for Standardized Toast Notifications
 *
 * Provides centralized, consistent toast notifications across all job types
 * and events. Ensures uniform message formats, durations, and positions.
 *
 * Usage:
 *   import { notificationService } from '@/lib/notification-service'
 *
 *   notificationService.jobStarted('sam_pull', 'My SAM Search')
 *   notificationService.jobCompleted('sharepoint_sync', 'My SharePoint Sync')
 *   notificationService.jobFailed('scrape', 'My Web Scrape', 'Network error')
 */

import toast, { ToastOptions } from 'react-hot-toast'
import { JobType, JOB_TYPE_CONFIG } from './job-type-config'

// Standard durations in milliseconds
const DURATIONS = {
  info: 3000,
  success: 5000,
  error: 8000,
  warning: 5000,
} as const

// Standard position for all toasts
const POSITION = 'top-right' as const

// Base toast options
const baseOptions: ToastOptions = {
  position: POSITION,
}

/**
 * Get the display label for a job type.
 * Handles both standard job types and special cases like 'deletion'.
 */
function getJobTypeLabel(jobType: JobType | 'deletion'): string {
  if (jobType === 'deletion') {
    return 'Deletion'
  }
  const config = JOB_TYPE_CONFIG[jobType]
  return config?.label || jobType
}

/**
 * Notification service for consistent toast messages across the application.
 */
export const notificationService = {
  /**
   * Show a toast when a job starts.
   * Format: "{Type} started: {Name}"
   */
  jobStarted(jobType: JobType | 'deletion', displayName: string, id?: string): void {
    const label = getJobTypeLabel(jobType)
    toast.success(`${label} started: ${displayName}`, {
      ...baseOptions,
      duration: DURATIONS.info,
      ...(id && { id }),
    })
  },

  /**
   * Show a toast when a job completes successfully.
   * Format: "{Type} completed: {Name}"
   */
  jobCompleted(jobType: JobType | 'deletion', displayName: string, id?: string): void {
    if (jobType === 'deletion') {
      // Special format for deletions
      toast.success(`"${displayName}" deleted`, {
        ...baseOptions,
        duration: DURATIONS.success,
        ...(id && { id }),
      })
    } else {
      const label = getJobTypeLabel(jobType)
      toast.success(`${label} completed: ${displayName}`, {
        ...baseOptions,
        duration: DURATIONS.success,
        ...(id && { id }),
      })
    }
  },

  /**
   * Show a toast when a job fails.
   * Format: "{Type} failed: {Name}" or "{Type} failed: {Name} - {Error}"
   */
  jobFailed(jobType: JobType | 'deletion', displayName: string, error?: string, id?: string): void {
    const label = getJobTypeLabel(jobType)
    const message = error
      ? `${label} failed: ${displayName} - ${error}`
      : `${label} failed: ${displayName}`

    toast.error(message, {
      ...baseOptions,
      duration: DURATIONS.error,
      ...(id && { id }),
    })
  },

  /**
   * Show a toast when a job is cancelled.
   * Format: "{Type} cancelled: {Name}"
   */
  jobCancelled(jobType: JobType | 'deletion', displayName: string, id?: string): void {
    const label = getJobTypeLabel(jobType)
    toast.error(`${label} cancelled: ${displayName}`, {
      ...baseOptions,
      duration: DURATIONS.warning,
      ...(id && { id }),
    })
  },

  /**
   * Show a toast when WebSocket connection is lost.
   */
  connectionLost(): void {
    toast.error('Connection lost. Attempting to reconnect...', {
      ...baseOptions,
      duration: DURATIONS.warning,
      id: 'connection-lost', // Prevent duplicate toasts
    })
  },

  /**
   * Show a toast when WebSocket connection is restored.
   */
  connectionRestored(): void {
    toast.success('Connection restored', {
      ...baseOptions,
      duration: DURATIONS.info,
      id: 'connection-restored', // Prevent duplicate toasts
    })
  },

  /**
   * Show a toast when falling back to polling mode.
   */
  fallbackToPolling(): void {
    toast('Using polling mode for updates', {
      ...baseOptions,
      duration: DURATIONS.info,
      icon: 'info',
      id: 'fallback-polling',
    })
  },

  /**
   * Show a generic info toast.
   */
  info(message: string): void {
    toast(message, {
      ...baseOptions,
      duration: DURATIONS.info,
    })
  },

  /**
   * Show a generic success toast.
   */
  success(message: string): void {
    toast.success(message, {
      ...baseOptions,
      duration: DURATIONS.success,
    })
  },

  /**
   * Show a generic error toast.
   */
  error(message: string): void {
    toast.error(message, {
      ...baseOptions,
      duration: DURATIONS.error,
    })
  },

  /**
   * Show a generic warning toast.
   */
  warning(message: string): void {
    toast(message, {
      ...baseOptions,
      duration: DURATIONS.warning,
      icon: 'warning',
    })
  },
}

export default notificationService

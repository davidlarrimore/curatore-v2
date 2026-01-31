/**
 * Centralized polling configuration for Curatore v2.
 *
 * This file provides standardized polling intervals and behaviors
 * to reduce duplicate API calls and ensure consistent UX.
 */

/**
 * Standard polling intervals in milliseconds.
 */
export const POLLING = {
  /** Global queue stats polling (shared across components) */
  QUEUE_STATS_MS: 5000,

  /** Individual asset detail page polling when asset is pending */
  ASSET_DETAIL_MS: 3000,

  /** Status bar stats update interval */
  STATUS_BAR_MS: 10000,

  /** Whether to pause polling when the tab is not visible */
  PAUSE_ON_HIDDEN: true,
} as const

/**
 * Check if the document is currently visible (tab is active).
 * Returns true if document.hidden is not available (SSR).
 */
export function isDocumentVisible(): boolean {
  if (typeof document === 'undefined') return true
  return !document.hidden
}

/**
 * Create a visibility-aware polling interval.
 * The callback won't be called when the tab is hidden (if PAUSE_ON_HIDDEN is true).
 *
 * @param callback - Function to call on each interval
 * @param intervalMs - Interval in milliseconds
 * @param options - Optional configuration
 * @returns Cleanup function to stop polling
 */
export function createPollingInterval(
  callback: () => void | Promise<void>,
  intervalMs: number,
  options: { pauseOnHidden?: boolean } = {}
): () => void {
  const { pauseOnHidden = POLLING.PAUSE_ON_HIDDEN } = options

  let intervalId: ReturnType<typeof setInterval> | null = null
  let isRunning = false

  const tick = async () => {
    if (pauseOnHidden && !isDocumentVisible()) {
      return
    }
    if (isRunning) return
    isRunning = true
    try {
      await callback()
    } finally {
      isRunning = false
    }
  }

  // Start the interval
  intervalId = setInterval(tick, intervalMs)

  // Cleanup function
  return () => {
    if (intervalId) {
      clearInterval(intervalId)
      intervalId = null
    }
  }
}

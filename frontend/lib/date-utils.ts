/**
 * Date/time utilities for Curatore frontend.
 *
 * All dates are displayed in EST (America/New_York) timezone.
 * Timestamps from the API are in UTC and converted for display.
 */

// Timezone configuration - EST (America/New_York handles DST automatically)
export const DISPLAY_TIMEZONE = 'America/New_York'
export const DISPLAY_TIMEZONE_ABBR = 'EST'

/**
 * Format a date string or Date object to a localized date/time string in EST.
 */
export function formatDateTime(
  date: string | Date | null | undefined,
  options?: Intl.DateTimeFormatOptions
): string {
  if (!date) return '-'

  const d = typeof date === 'string' ? new Date(date) : date
  if (isNaN(d.getTime())) return '-'

  const defaultOptions: Intl.DateTimeFormatOptions = {
    timeZone: DISPLAY_TIMEZONE,
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  }

  return d.toLocaleString('en-US', { ...defaultOptions, ...options })
}

/**
 * Format a date to show just the date portion in EST.
 */
export function formatDate(date: string | Date | null | undefined): string {
  if (!date) return '-'

  const d = typeof date === 'string' ? new Date(date) : date
  if (isNaN(d.getTime())) return '-'

  return d.toLocaleString('en-US', {
    timeZone: DISPLAY_TIMEZONE,
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

/**
 * Format a date to show just the time portion in EST.
 */
export function formatTime(date: string | Date | null | undefined): string {
  if (!date) return '-'

  const d = typeof date === 'string' ? new Date(date) : date
  if (isNaN(d.getTime())) return '-'

  return d.toLocaleString('en-US', {
    timeZone: DISPLAY_TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })
}

/**
 * Format a date as a relative time string (e.g., "5m ago", "2h ago").
 */
export function formatTimeAgo(date: string | Date | null | undefined): string {
  if (!date) return '-'

  const d = typeof date === 'string' ? new Date(date) : date
  if (isNaN(d.getTime())) return '-'

  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const seconds = Math.floor(diff / 1000)

  if (seconds < 0) return 'just now' // Future date
  if (seconds < 60) return 'just now'

  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`

  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`

  const weeks = Math.floor(days / 7)
  if (weeks < 4) return `${weeks}w ago`

  // For older dates, show the actual date
  return formatDate(d)
}

/**
 * Format a duration between two dates.
 */
export function formatDuration(
  startDate: string | Date | null | undefined,
  endDate: string | Date | null | undefined
): string {
  if (!startDate) return '-'

  const start = typeof startDate === 'string' ? new Date(startDate) : startDate
  if (isNaN(start.getTime())) return '-'

  const end = endDate
    ? (typeof endDate === 'string' ? new Date(endDate) : endDate)
    : new Date()

  if (isNaN(end.getTime())) return '-'

  const diff = end.getTime() - start.getTime()
  if (diff < 0) return '-'

  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return `${seconds}s`

  const minutes = Math.floor(seconds / 60)
  const secs = seconds % 60
  if (minutes < 60) return `${minutes}m ${secs}s`

  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  if (hours < 24) return `${hours}h ${mins}m`

  const days = Math.floor(hours / 24)
  const hrs = hours % 24
  return `${days}d ${hrs}h`
}

/**
 * Get the current time formatted for display (e.g., for status bar clock).
 */
export function formatCurrentTime(): string {
  return new Date().toLocaleString('en-US', {
    timeZone: DISPLAY_TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })
}

/**
 * Format a date for display in a compact format (e.g., "Jan 29, 5:30 PM").
 */
export function formatCompact(date: string | Date | null | undefined): string {
  if (!date) return '-'

  const d = typeof date === 'string' ? new Date(date) : date
  if (isNaN(d.getTime())) return '-'

  return d.toLocaleString('en-US', {
    timeZone: DISPLAY_TIMEZONE,
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

/**
 * Format a date for ISO-like display but in EST (e.g., "2026-01-29 17:30:00 EST").
 */
export function formatISO(date: string | Date | null | undefined): string {
  if (!date) return '-'

  const d = typeof date === 'string' ? new Date(date) : date
  if (isNaN(d.getTime())) return '-'

  const formatted = d.toLocaleString('en-CA', {
    timeZone: DISPLAY_TIMEZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).replace(',', '')

  return `${formatted} ${DISPLAY_TIMEZONE_ABBR}`
}

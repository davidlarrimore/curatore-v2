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
 * Parse a date string from the API, treating it as UTC.
 * API timestamps are stored in UTC but may not have the Z suffix.
 */
function parseDate(date: string | Date | null | undefined): Date | null {
  if (!date) return null
  if (date instanceof Date) return isNaN(date.getTime()) ? null : date

  // If the string doesn't have a timezone indicator, treat it as UTC
  let dateStr = date
  if (!dateStr.endsWith('Z') && !dateStr.includes('+') && !dateStr.includes('-', 10)) {
    dateStr = dateStr + 'Z'
  }

  const d = new Date(dateStr)
  return isNaN(d.getTime()) ? null : d
}

/**
 * Format a date string or Date object to a localized date/time string in EST.
 */
export function formatDateTime(
  date: string | Date | null | undefined,
  options?: Intl.DateTimeFormatOptions
): string {
  const d = parseDate(date)
  if (!d) return '-'

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
  const d = parseDate(date)
  if (!d) return '-'

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
  const d = parseDate(date)
  if (!d) return '-'

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
  const d = parseDate(date)
  if (!d) return '-'

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
  const start = parseDate(startDate)
  if (!start) return '-'

  const end = endDate ? parseDate(endDate) : new Date()
  if (!end) return '-'

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
  const d = parseDate(date)
  if (!d) return '-'

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
  const d = parseDate(date)
  if (!d) return '-'

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

/**
 * Format a future date as a relative time string (e.g., "in 5m", "in 2h", "Tomorrow @ 8 AM").
 */
export function formatTimeUntil(date: string | Date | null | undefined): string {
  const d = parseDate(date)
  if (!d) return '-'

  const now = new Date()
  const diff = d.getTime() - now.getTime()

  // Past date
  if (diff < 0) return formatTimeAgo(date)

  const seconds = Math.floor(diff / 1000)

  if (seconds < 60) return 'in < 1m'

  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `in ${minutes}m`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `in ${hours}h`

  const days = Math.floor(hours / 24)
  if (days === 1) {
    // Show "Tomorrow @ time"
    const timeStr = d.toLocaleString('en-US', {
      timeZone: DISPLAY_TIMEZONE,
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    })
    return `Tomorrow @ ${timeStr}`
  }

  if (days < 7) {
    // Show day of week @ time
    const dayStr = d.toLocaleString('en-US', {
      timeZone: DISPLAY_TIMEZONE,
      weekday: 'short',
    })
    const timeStr = d.toLocaleString('en-US', {
      timeZone: DISPLAY_TIMEZONE,
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    })
    return `${dayStr} @ ${timeStr}`
  }

  // For dates further out, show the full date
  return formatCompact(d)
}

/**
 * Format a date as a short datetime with relative day reference in EST.
 * - Today: "Today @ 5:30 PM EST"
 * - Yesterday: "Yesterday @ 5:30 PM EST"
 * - This week: "Mon @ 5:30 PM EST"
 * - Older: "Jan 29 @ 5:30 PM EST"
 */
export function formatShortDateTime(date: string | Date | null | undefined): string {
  const d = parseDate(date)
  if (!d) return '-'

  const now = new Date()

  // Get the date components in the display timezone
  const dateFormatter = new Intl.DateTimeFormat('en-US', {
    timeZone: DISPLAY_TIMEZONE,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  })

  const dateParts = dateFormatter.formatToParts(d)
  const nowParts = dateFormatter.formatToParts(now)

  const getPartValue = (parts: Intl.DateTimeFormatPart[], type: string) =>
    parts.find(p => p.type === type)?.value || ''

  const dateYear = getPartValue(dateParts, 'year')
  const dateMonth = getPartValue(dateParts, 'month')
  const dateDay = getPartValue(dateParts, 'day')

  const nowYear = getPartValue(nowParts, 'year')
  const nowMonth = getPartValue(nowParts, 'month')
  const nowDay = getPartValue(nowParts, 'day')

  const isToday = dateYear === nowYear && dateMonth === nowMonth && dateDay === nowDay

  // Check yesterday
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  const yesterdayParts = dateFormatter.formatToParts(yesterday)
  const yesterdayYear = getPartValue(yesterdayParts, 'year')
  const yesterdayMonth = getPartValue(yesterdayParts, 'month')
  const yesterdayDay = getPartValue(yesterdayParts, 'day')
  const isYesterday = dateYear === yesterdayYear && dateMonth === yesterdayMonth && dateDay === yesterdayDay

  // Format time portion with timezone
  const timeStr = d.toLocaleString('en-US', {
    timeZone: DISPLAY_TIMEZONE,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })

  if (isToday) {
    return `Today @ ${timeStr} ${DISPLAY_TIMEZONE_ABBR}`
  }

  if (isYesterday) {
    return `Yesterday @ ${timeStr} ${DISPLAY_TIMEZONE_ABBR}`
  }

  // Check if within last 7 days
  const sevenDaysAgo = new Date(now)
  sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7)
  if (d > sevenDaysAgo) {
    // Within the last week, show day name
    const dayName = d.toLocaleString('en-US', {
      timeZone: DISPLAY_TIMEZONE,
      weekday: 'short',
    })
    return `${dayName} @ ${timeStr} ${DISPLAY_TIMEZONE_ABBR}`
  }

  // Older dates - show month and day
  const dateStr = d.toLocaleString('en-US', {
    timeZone: DISPLAY_TIMEZONE,
    month: 'short',
    day: 'numeric',
  })
  return `${dateStr} @ ${timeStr} ${DISPLAY_TIMEZONE_ABBR}`
}

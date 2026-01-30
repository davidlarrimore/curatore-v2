'use client'

import {
  Loader2,
  CheckCircle,
  XCircle,
  AlertCircle,
  Sparkles,
  Clock,
} from 'lucide-react'

type SummaryStatus = 'pending' | 'generating' | 'ready' | 'failed' | 'no_llm' | null | undefined

interface SamStatusBadgeProps {
  status: SummaryStatus
  className?: string
}

const statusConfig: Record<string, {
  label: string
  icon: React.ElementType
  className: string
}> = {
  pending: {
    label: 'Pending',
    icon: Clock,
    className: 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400',
  },
  generating: {
    label: 'Generating',
    icon: Loader2,
    className: 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400',
  },
  ready: {
    label: 'AI Summary',
    icon: Sparkles,
    className: 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400',
  },
  failed: {
    label: 'Failed',
    icon: XCircle,
    className: 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400',
  },
  no_llm: {
    label: 'No LLM',
    icon: AlertCircle,
    className: 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400',
  },
}

export function SamSummaryStatusBadge({ status, className }: SamStatusBadgeProps) {
  if (!status) return null

  const config = statusConfig[status]
  if (!config) return null

  const Icon = config.icon
  const isSpinning = status === 'generating'

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${config.className} ${className || ''}`}
    >
      <Icon className={`w-3 h-3 ${isSpinning ? 'animate-spin' : ''}`} />
      <span>{config.label}</span>
    </span>
  )
}

// Badge for NEW/UPDATED solicitations
interface SolicitationBadgeProps {
  isNew?: boolean
  isUpdated?: boolean
  className?: string
}

export function SolicitationBadge({ isNew, isUpdated, className }: SolicitationBadgeProps) {
  if (isNew) {
    return (
      <span
        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 ${className || ''}`}
      >
        NEW
      </span>
    )
  }

  if (isUpdated) {
    return (
      <span
        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 ${className || ''}`}
      >
        UPDATED
      </span>
    )
  }

  return null
}

// Notice type badge
interface NoticeTypeBadgeProps {
  type: string
  className?: string
}

const noticeTypeLabels: Record<string, string> = {
  o: 'Combined',
  p: 'Presolicitation',
  k: 'Sources Sought',
  r: 'Special Notice',
  s: 'Award',
  a: 'Amendment',
}

const noticeTypeColors: Record<string, string> = {
  o: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300',
  p: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300',
  k: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300',
  r: 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400',
  s: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300',
  a: 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300',
}

export function NoticeTypeBadge({ type, className }: NoticeTypeBadgeProps) {
  const label = noticeTypeLabels[type] || type.toUpperCase()
  const colorClass = noticeTypeColors[type] || noticeTypeColors.r

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${colorClass} ${className || ''}`}
    >
      {label}
    </span>
  )
}

export default SamSummaryStatusBadge

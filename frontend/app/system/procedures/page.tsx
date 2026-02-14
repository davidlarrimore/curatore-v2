'use client'

/**
 * System Procedures list page.
 *
 * Manage system-level procedures (no Run button). Uses systemCwrApi for the
 * system org context. Supports create, edit, delete, and toggle active state.
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import YAML from 'yaml'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { systemCwrApi, type ProcedureListItem, type Procedure } from '@/lib/api'
import { formatTimeAgo, formatTimeUntil, formatCompact } from '@/lib/date-utils'
import { Button } from '@/components/ui/Button'
import {
  RefreshCw,
  Workflow,
  Search,
  CheckCircle,
  AlertTriangle,
  Loader2,
  Clock,
  Calendar,
  Zap,
  Webhook,
  Tag,
  ChevronDown,
  ChevronRight,
  Settings,
  Eye,
  Trash2,
  Plus,
  Pencil,
} from 'lucide-react'

// Trigger type icons
function getTriggerIcon(triggerType: string): React.ComponentType<{ className?: string }> {
  switch (triggerType) {
    case 'cron': return Calendar
    case 'event': return Zap
    case 'webhook': return Webhook
    default: return Clock
  }
}

function getTriggerColor(triggerType: string): string {
  switch (triggerType) {
    case 'cron': return 'blue'
    case 'event': return 'amber'
    case 'webhook': return 'purple'
    default: return 'gray'
  }
}

// Convert cron expression to human-readable format
function formatCronExpression(cron: string): string {
  try {
    const parts = cron.split(' ')
    if (parts.length < 5) return cron

    const [minute, hour, dayOfMonth, , dayOfWeek] = parts

    const hourNum = parseInt(hour)
    const minuteNum = parseInt(minute)
    const ampm = hourNum >= 12 ? 'PM' : 'AM'
    const hour12 = hourNum === 0 ? 12 : hourNum > 12 ? hourNum - 12 : hourNum
    const timeStr = `${hour12}:${minuteNum.toString().padStart(2, '0')} ${ampm}`

    const dayNames: Record<string, string> = {
      '0': 'Sunday', '1': 'Monday', '2': 'Tuesday', '3': 'Wednesday',
      '4': 'Thursday', '5': 'Friday', '6': 'Saturday', '7': 'Sunday',
      'SUN': 'Sunday', 'MON': 'Monday', 'TUE': 'Tuesday', 'WED': 'Wednesday',
      'THU': 'Thursday', 'FRI': 'Friday', 'SAT': 'Saturday',
    }

    let dayStr = ''
    if (dayOfWeek === '*' && dayOfMonth === '*') {
      dayStr = 'every day'
    } else if (dayOfWeek === '1-5') {
      dayStr = 'weekdays'
    } else if (dayOfWeek === '0,6' || dayOfWeek === '6,0') {
      dayStr = 'weekends'
    } else if (dayOfWeek !== '*') {
      const days = dayOfWeek.split(',').map(d => dayNames[d.toUpperCase()] || d)
      dayStr = days.join(', ')
    } else if (dayOfMonth !== '*') {
      dayStr = `day ${dayOfMonth} of month`
    }

    return `${timeStr}${dayStr ? `, ${dayStr}` : ''}`
  } catch {
    return cron
  }
}

export default function SystemProceduresPage() {
  const { token } = useAuth()

  const [procedures, setProcedures] = useState<ProcedureListItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  // Filters
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTag, setSelectedTag] = useState<string>('all')

  // Expanded procedure details
  const [expandedProcedure, setExpandedProcedure] = useState<string | null>(null)
  const [procedureDetails, setProcedureDetails] = useState<Procedure | null>(null)
  const [loadingDetails, setLoadingDetails] = useState(false)

  // Action states
  const [deletingProcedure, setDeletingProcedure] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<ProcedureListItem | null>(null)

  // Load procedures
  const loadData = useCallback(async (silent = false) => {
    if (!token) return

    if (!silent) {
      setIsLoading(true)
    }
    setError('')

    try {
      const data = await systemCwrApi.listProcedures({
        tag: selectedTag !== 'all' ? selectedTag : undefined,
      })
      setProcedures(data.procedures)
    } catch (err: unknown) {
      if (!silent) {
        const message = err instanceof Error ? err.message : 'Failed to load procedures'
        setError(message)
      }
    } finally {
      if (!silent) {
        setIsLoading(false)
      }
      setIsRefreshing(false)
    }
  }, [token, selectedTag])

  // Initial load
  useEffect(() => {
    if (token) {
      loadData()
    }
  }, [token, loadData])

  // Manual refresh
  const handleRefresh = async () => {
    setIsRefreshing(true)
    await loadData()
  }

  // Load procedure details when expanded
  const handleExpand = async (slug: string) => {
    if (expandedProcedure === slug) {
      setExpandedProcedure(null)
      setProcedureDetails(null)
      return
    }

    setExpandedProcedure(slug)
    setLoadingDetails(true)

    try {
      const details = await systemCwrApi.getProcedure(slug)
      setProcedureDetails(details)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load procedure details'
      setError(message)
      setTimeout(() => setError(''), 5000)
    } finally {
      setLoadingDetails(false)
    }
  }

  // Delete procedure
  const handleDelete = async (procedure: ProcedureListItem) => {
    if (!token) return

    setDeletingProcedure(procedure.slug)
    try {
      await systemCwrApi.deleteProcedure(procedure.slug)
      setSuccessMessage(`Procedure "${procedure.name}" has been deleted`)
      setConfirmDelete(null)
      await loadData(true)
      setTimeout(() => setSuccessMessage(''), 5000)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to delete procedure'
      setError(message)
      setTimeout(() => setError(''), 5000)
    } finally {
      setDeletingProcedure(null)
    }
  }

  // Get unique tags from all procedures
  const allTags = useMemo(() => {
    const tags = new Set<string>()
    procedures.forEach(p => p.tags.forEach(t => tags.add(t)))
    return Array.from(tags).sort()
  }, [procedures])

  // Filter procedures
  const filteredProcedures = useMemo(() => {
    let result = [...procedures]

    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase()
      result = result.filter(p =>
        p.name.toLowerCase().includes(query) ||
        p.slug.toLowerCase().includes(query) ||
        (p.description && p.description.toLowerCase().includes(query))
      )
    }

    result.sort((a, b) => a.name.localeCompare(b.name))

    return result
  }, [procedures, searchQuery])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-600"></div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Procedures
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Manage system-level automated workflows and scheduled tasks
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Link href="/system/procedures/new">
            <Button variant="primary" className="gap-2">
              <Plus className="w-4 h-4" />
              New Procedure
            </Button>
          </Link>
        </div>
      </div>

      {/* Success Message */}
      {successMessage && (
        <div className="rounded-xl bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-100 dark:border-emerald-900/50 p-4">
          <div className="flex items-center gap-3">
            <CheckCircle className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
            <p className="text-sm font-medium text-emerald-800 dark:text-emerald-200">{successMessage}</p>
          </div>
        </div>
      )}

      {/* Error Message */}
      {error && (
        <div className="rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
          <div className="flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
            <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        <div className="flex flex-wrap gap-2">
          <select
            value={selectedTag}
            onChange={(e) => setSelectedTag(e.target.value)}
            className="px-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-2 focus:ring-amber-500"
          >
            <option value="all">All Tags</option>
            {allTags.map(tag => (
              <option key={tag} value={tag}>{tag}</option>
            ))}
          </select>
        </div>

        <div className="relative w-full sm:w-auto">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search procedures..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full sm:w-64 pl-9 pr-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-500"
          />
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center">
              <Workflow className="w-5 h-5 text-amber-600 dark:text-amber-400" />
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400">Total</p>
              <p className="text-xl font-bold text-gray-900 dark:text-white">{procedures.length}</p>
            </div>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-green-50 dark:bg-green-900/20 flex items-center justify-center">
              <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-400" />
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400">Scheduled</p>
              <p className="text-xl font-bold text-gray-900 dark:text-white">
                {procedures.filter(p => p.is_active && p.trigger_count > 0).length}
              </p>
            </div>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
              <Clock className="w-5 h-5 text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400">With Triggers</p>
              <p className="text-xl font-bold text-gray-900 dark:text-white">
                {procedures.filter(p => p.trigger_count > 0).length}
              </p>
            </div>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-purple-50 dark:bg-purple-900/20 flex items-center justify-center">
              <Settings className="w-5 h-5 text-purple-600 dark:text-purple-400" />
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400">System</p>
              <p className="text-xl font-bold text-gray-900 dark:text-white">
                {procedures.filter(p => p.is_system).length}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Procedures List */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Procedures
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            {filteredProcedures.length} procedure{filteredProcedures.length !== 1 ? 's' : ''}
          </p>
        </div>

        {filteredProcedures.length === 0 ? (
          <div className="p-12 text-center">
            <Workflow className="w-12 h-12 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
            <p className="text-gray-500 dark:text-gray-400">No procedures found</p>
            <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">
              {searchQuery ? 'Try adjusting your search' : 'No procedures are configured'}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-gray-200 dark:divide-gray-700">
            {filteredProcedures.map((procedure) => (
              <div key={procedure.id} className="px-6 py-4">
                {/* Main row */}
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => handleExpand(procedure.slug)}
                        className="flex items-center gap-2 text-left group"
                      >
                        {expandedProcedure === procedure.slug ? (
                          <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0" />
                        ) : (
                          <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />
                        )}
                        <span className="text-sm font-medium text-gray-900 dark:text-white group-hover:text-amber-600 dark:group-hover:text-amber-400">
                          {procedure.name}
                        </span>
                      </button>

                      {/* Status badges */}
                      {procedure.is_system && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                          <Settings className="w-3 h-3" />
                          System
                        </span>
                      )}

                      {procedure.trigger_count > 0 && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
                          <Clock className="w-3 h-3" />
                          {procedure.trigger_count} trigger{procedure.trigger_count !== 1 ? 's' : ''}
                        </span>
                      )}

                      {procedure.next_trigger_at && (
                        <span
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
                          title={`Next run: ${formatCompact(procedure.next_trigger_at)}`}
                        >
                          <Calendar className="w-3 h-3" />
                          {formatTimeUntil(procedure.next_trigger_at)}
                        </span>
                      )}
                    </div>

                    {procedure.description && (
                      <p className="mt-1 ml-6 text-sm text-gray-500 dark:text-gray-400">
                        {procedure.description}
                      </p>
                    )}

                    <div className="mt-2 ml-6 flex items-center gap-4">
                      <span className="text-xs text-gray-400 dark:text-gray-500 font-mono">
                        {procedure.slug}
                      </span>
                      <span className="text-xs text-gray-400 dark:text-gray-500">
                        v{procedure.version}
                      </span>
                      {procedure.tags.length > 0 && (
                        <div className="flex items-center gap-1">
                          {procedure.tags.map(tag => (
                            <span
                              key={tag}
                              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                            >
                              <Tag className="w-3 h-3" />
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2">
                    <Link href={`/system/procedures/${procedure.slug}/edit`}>
                      <button className="inline-flex items-center gap-2 px-3.5 py-2 text-sm font-medium rounded-lg bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 hover:bg-amber-100 dark:hover:bg-amber-900/30 transition-colors">
                        <Pencil className="w-4 h-4" />
                        Edit
                      </button>
                    </Link>

                    <div className="relative group/delete">
                      <button
                        onClick={() => setConfirmDelete(procedure)}
                        disabled={deletingProcedure === procedure.slug || procedure.is_system}
                        title={procedure.is_system ? '' : 'Delete procedure'}
                        className="inline-flex items-center justify-center w-9 h-9 rounded-lg text-red-500 dark:text-red-400 border border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/40 hover:border-red-300 dark:hover:border-red-700 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {deletingProcedure === procedure.slug ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Trash2 className="w-4 h-4" />
                        )}
                      </button>
                      {procedure.is_system && (
                        <div className="absolute bottom-full right-0 mb-2 w-56 px-3 py-2 text-xs text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg opacity-0 pointer-events-none group-hover/delete:opacity-100 transition-opacity z-50">
                          System procedures are managed by administrators and cannot be deleted from the UI.
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Expanded details */}
                {expandedProcedure === procedure.slug && (
                  <div className="mt-4 ml-6 space-y-4">
                    {loadingDetails ? (
                      <div className="flex items-center gap-2 text-sm text-gray-500">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Loading details...
                      </div>
                    ) : procedureDetails ? (
                      <>
                        {/* Triggers */}
                        <div>
                          <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                            Triggers
                          </h4>
                          {procedureDetails.triggers.length === 0 ? (
                            <p className="text-sm text-gray-400 dark:text-gray-500">No triggers configured</p>
                          ) : (
                            <div className="space-y-2">
                              {procedureDetails.triggers.map((trigger, idx) => {
                                const Icon = getTriggerIcon(trigger.trigger_type)
                                const color = getTriggerColor(trigger.trigger_type)
                                return (
                                  <div
                                    key={trigger.id || idx}
                                    className="flex items-center justify-between p-3 rounded-lg bg-gray-50 dark:bg-gray-900/50"
                                  >
                                    <div className="flex items-center gap-3">
                                      <div className={`w-8 h-8 rounded-lg bg-${color}-50 dark:bg-${color}-900/20 flex items-center justify-center`}>
                                        <Icon className={`w-4 h-4 text-${color}-600 dark:text-${color}-400`} />
                                      </div>
                                      <div>
                                        <span className="text-sm font-medium text-gray-900 dark:text-white capitalize">
                                          {trigger.trigger_type}
                                        </span>
                                        {trigger.cron_expression && (
                                          <span
                                            className="ml-2 text-xs text-gray-500 dark:text-gray-400"
                                            title={trigger.cron_expression}
                                          >
                                            {formatCronExpression(trigger.cron_expression)}
                                          </span>
                                        )}
                                        {trigger.event_name && (
                                          <span className="ml-2 text-xs font-mono text-gray-500 dark:text-gray-400">
                                            {trigger.event_name}
                                          </span>
                                        )}
                                      </div>
                                    </div>
                                    <div className="flex items-center gap-4">
                                      {trigger.next_trigger_at && trigger.trigger_type === 'cron' && (
                                        <span className="text-xs text-blue-600 dark:text-blue-400" title={formatCompact(trigger.next_trigger_at)}>
                                          Next: {formatTimeUntil(trigger.next_trigger_at)}
                                        </span>
                                      )}
                                      {trigger.last_triggered_at && (
                                        <span className="text-xs text-gray-400 dark:text-gray-500">
                                          Last: {formatTimeAgo(trigger.last_triggered_at)}
                                        </span>
                                      )}
                                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${trigger.is_active ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400' : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400'}`}>
                                        {trigger.is_active ? 'Active' : 'Inactive'}
                                      </span>
                                    </div>
                                  </div>
                                )
                              })}
                            </div>
                          )}
                        </div>

                        {/* Definition preview */}
                        <div>
                          <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                            Definition (YAML)
                          </h4>
                          <div className="p-3 rounded-lg bg-gray-50 dark:bg-gray-900/50">
                            <pre className="text-xs font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                              {YAML.stringify(procedureDetails.definition)}
                            </pre>
                          </div>
                        </div>
                      </>
                    ) : null}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-md w-full mx-4 overflow-hidden">
            <div className="p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center flex-shrink-0">
                  <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Delete Procedure
                </h3>
              </div>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                Are you sure you want to delete <span className="font-semibold text-gray-900 dark:text-white">{confirmDelete.name}</span>?
              </p>
              <p className="text-sm text-red-600 dark:text-red-400">
                This action is permanent and cannot be undone. All triggers and run history associated with this procedure will be lost.
              </p>
            </div>
            <div className="flex items-center justify-end gap-3 px-6 py-4 bg-gray-50 dark:bg-gray-900/50 border-t border-gray-200 dark:border-gray-700">
              <Button
                variant="secondary"
                onClick={() => setConfirmDelete(null)}
                disabled={deletingProcedure === confirmDelete.slug}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={() => handleDelete(confirmDelete)}
                disabled={deletingProcedure === confirmDelete.slug}
                className="bg-red-600 hover:bg-red-700 text-white gap-2"
              >
                {deletingProcedure === confirmDelete.slug ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Trash2 className="w-4 h-4" />
                )}
                Delete Procedure
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

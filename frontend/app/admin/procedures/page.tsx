'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { proceduresApi, type ProcedureListItem, type Procedure, type ProcedureTrigger } from '@/lib/api'
import { formatDateTime, formatTimeAgo } from '@/lib/date-utils'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  RefreshCw,
  Workflow,
  Search,
  Play,
  Pause,
  CheckCircle,
  XCircle,
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
} from 'lucide-react'

export default function ProceduresPage() {
  return (
    <ProtectedRoute>
      <ProceduresContent />
    </ProtectedRoute>
  )
}

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

function ProceduresContent() {
  const router = useRouter()
  const { token } = useAuth()

  const [procedures, setProcedures] = useState<ProcedureListItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  // Filters
  const [showInactive, setShowInactive] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTag, setSelectedTag] = useState<string>('all')

  // Expanded procedure details
  const [expandedProcedure, setExpandedProcedure] = useState<string | null>(null)
  const [procedureDetails, setProcedureDetails] = useState<Procedure | null>(null)
  const [loadingDetails, setLoadingDetails] = useState(false)

  // Action states
  const [runningProcedure, setRunningProcedure] = useState<string | null>(null)
  const [togglingProcedure, setTogglingProcedure] = useState<string | null>(null)

  // Load procedures
  const loadData = useCallback(async (silent = false) => {
    if (!token) return

    if (!silent) {
      setIsLoading(true)
    }
    setError('')

    try {
      const data = await proceduresApi.listProcedures(token, {
        is_active: showInactive ? undefined : true,
        tag: selectedTag !== 'all' ? selectedTag : undefined,
      })
      setProcedures(data.procedures)
    } catch (err: any) {
      if (!silent) {
        setError(err.message || 'Failed to load procedures')
      }
    } finally {
      if (!silent) {
        setIsLoading(false)
      }
      setIsRefreshing(false)
    }
  }, [token, showInactive, selectedTag])

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
      const details = await proceduresApi.getProcedure(token!, slug)
      setProcedureDetails(details)
    } catch (err: any) {
      setError(err.message || 'Failed to load procedure details')
      setTimeout(() => setError(''), 5000)
    } finally {
      setLoadingDetails(false)
    }
  }

  // Run procedure
  const handleRun = async (slug: string) => {
    if (!token) return

    setRunningProcedure(slug)
    try {
      const result = await proceduresApi.runProcedure(token, slug, {}, false, true)
      setSuccessMessage(`Procedure ${slug} started (Run ID: ${result.run_id})`)
      setTimeout(() => setSuccessMessage(''), 5000)
    } catch (err: any) {
      setError(err.message || `Failed to run procedure ${slug}`)
      setTimeout(() => setError(''), 5000)
    } finally {
      setRunningProcedure(null)
    }
  }

  // Toggle procedure active state
  const handleToggleActive = async (procedure: ProcedureListItem) => {
    if (!token) return

    setTogglingProcedure(procedure.slug)
    try {
      if (procedure.is_active) {
        await proceduresApi.disableProcedure(token, procedure.slug)
        setSuccessMessage(`Procedure ${procedure.slug} disabled`)
      } else {
        await proceduresApi.enableProcedure(token, procedure.slug)
        setSuccessMessage(`Procedure ${procedure.slug} enabled`)
      }
      await loadData(true)
      setTimeout(() => setSuccessMessage(''), 3000)
    } catch (err: any) {
      setError(err.message || 'Failed to toggle procedure')
      setTimeout(() => setError(''), 5000)
    } finally {
      setTogglingProcedure(null)
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

    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase()
      result = result.filter(p =>
        p.name.toLowerCase().includes(query) ||
        p.slug.toLowerCase().includes(query) ||
        (p.description && p.description.toLowerCase().includes(query))
      )
    }

    return result
  }, [procedures, searchQuery])

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin"></div>
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading procedures...</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-start gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-lg shadow-emerald-500/25 flex-shrink-0">
                <Workflow className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  Procedures
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  Manage automated workflows and scheduled tasks
                </p>
              </div>
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
            </div>
          </div>

          {/* Success Message */}
          {successMessage && (
            <div className="mt-6 rounded-xl bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-100 dark:border-emerald-900/50 p-4">
              <div className="flex items-center gap-3">
                <CheckCircle className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                <p className="text-sm font-medium text-emerald-800 dark:text-emerald-200">{successMessage}</p>
              </div>
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div className="mt-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
              <div className="flex items-center gap-3">
                <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
                <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
              </div>
            </div>
          )}
        </div>

        {/* Filters */}
        <div className="mb-6 flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
          <div className="flex flex-wrap gap-2">
            {/* Tag filter */}
            <select
              value={selectedTag}
              onChange={(e) => setSelectedTag(e.target.value)}
              className="px-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="all">All Tags</option>
              {allTags.map(tag => (
                <option key={tag} value={tag}>{tag}</option>
              ))}
            </select>

            {/* Show inactive toggle */}
            <button
              onClick={() => setShowInactive(!showInactive)}
              className={`
                flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors
                ${showInactive
                  ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400'
                  : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 border border-gray-200 dark:border-gray-700'
                }
              `}
            >
              <Eye className="w-4 h-4" />
              Show Inactive
            </button>
          </div>

          {/* Search */}
          <div className="relative w-full sm:w-auto">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search procedures..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full sm:w-64 pl-9 pr-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center">
                <Workflow className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
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
                <p className="text-xs text-gray-500 dark:text-gray-400">Active</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">
                  {procedures.filter(p => p.is_active).length}
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
                          <span className="text-sm font-medium text-gray-900 dark:text-white group-hover:text-indigo-600 dark:group-hover:text-indigo-400">
                            {procedure.name}
                          </span>
                        </button>

                        {/* Status badges */}
                        {procedure.is_active ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
                            <CheckCircle className="w-3 h-3" />
                            Active
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400">
                            <Pause className="w-3 h-3" />
                            Inactive
                          </span>
                        )}

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
                      <Button
                        variant="secondary"
                        onClick={() => handleRun(procedure.slug)}
                        disabled={runningProcedure === procedure.slug || !procedure.is_active}
                        className="gap-2"
                      >
                        {runningProcedure === procedure.slug ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Play className="w-4 h-4" />
                        )}
                        Run
                      </Button>

                      <Button
                        variant="secondary"
                        onClick={() => handleToggleActive(procedure)}
                        disabled={togglingProcedure === procedure.slug}
                        className={procedure.is_active ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}
                      >
                        {togglingProcedure === procedure.slug ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : procedure.is_active ? (
                          <Pause className="w-4 h-4" />
                        ) : (
                          <Play className="w-4 h-4" />
                        )}
                      </Button>
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
                                            <span className="ml-2 text-xs font-mono text-gray-500 dark:text-gray-400">
                                              {trigger.cron_expression}
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
                              Definition
                            </h4>
                            <div className="p-3 rounded-lg bg-gray-50 dark:bg-gray-900/50">
                              <pre className="text-xs font-mono text-gray-700 dark:text-gray-300 overflow-auto max-h-48">
                                {JSON.stringify(procedureDetails.definition, null, 2)}
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
      </div>
    </div>
  )
}

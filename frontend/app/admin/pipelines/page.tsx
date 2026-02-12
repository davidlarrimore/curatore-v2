'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import {
  pipelinesApi,
  type PipelineListItem,
  type Pipeline,
  type PipelineStage,
  type PipelineTrigger,
  type PipelineRun,
} from '@/lib/api'
import { formatDateTime, formatTimeAgo } from '@/lib/date-utils'
import { Button } from '@/components/ui/Button'
import { JobProgressPanelByType } from '@/components/ui/JobProgressPanel'
import { useJobProgressByType } from '@/lib/useJobProgress'
import { useActiveJobs } from '@/lib/context-shims'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  RefreshCw,
  GitBranch,
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
  Layers,
  ArrowRight,
  Hash,
  RotateCcw,
} from 'lucide-react'

export default function PipelinesPage() {
  return (
    <ProtectedRoute>
      <PipelinesContent />
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

// Stage type colors
function getStageTypeColor(stageType: string): string {
  switch (stageType) {
    case 'gather': return 'blue'
    case 'transform': return 'purple'
    case 'filter': return 'amber'
    case 'output': return 'emerald'
    default: return 'gray'
  }
}

// Run status colors
function getRunStatusColor(status: string): string {
  switch (status) {
    case 'pending': return 'blue'
    case 'running': return 'purple'
    case 'completed': return 'emerald'
    case 'failed': return 'red'
    case 'paused': return 'amber'
    default: return 'gray'
  }
}

function PipelinesContent() {
  const router = useRouter()
  const { token } = useAuth()
  const { addJob } = useActiveJobs()
  const { isActive: hasRunningPipelines } = useJobProgressByType('pipeline', {
    onComplete: () => loadData(true),
  })

  const [pipelines, setPipelines] = useState<PipelineListItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  // Filters
  const [showInactive, setShowInactive] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTag, setSelectedTag] = useState<string>('all')

  // Expanded pipeline details
  const [expandedPipeline, setExpandedPipeline] = useState<string | null>(null)
  const [pipelineDetails, setPipelineDetails] = useState<Pipeline | null>(null)
  const [pipelineRuns, setPipelineRuns] = useState<PipelineRun[]>([])
  const [loadingDetails, setLoadingDetails] = useState(false)

  // Action states
  const [runningPipeline, setRunningPipeline] = useState<string | null>(null)
  const [togglingPipeline, setTogglingPipeline] = useState<string | null>(null)

  // Load pipelines
  const loadData = useCallback(async (silent = false) => {
    if (!token) return

    if (!silent) {
      setIsLoading(true)
    }
    setError('')

    try {
      const data = await pipelinesApi.listPipelines(token, {
        is_active: showInactive ? undefined : true,
        tag: selectedTag !== 'all' ? selectedTag : undefined,
      })
      setPipelines(data.pipelines)
    } catch (err: any) {
      if (!silent) {
        setError(err.message || 'Failed to load pipelines')
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

  // Load pipeline details when expanded
  const handleExpand = async (slug: string) => {
    if (expandedPipeline === slug) {
      setExpandedPipeline(null)
      setPipelineDetails(null)
      setPipelineRuns([])
      return
    }

    setExpandedPipeline(slug)
    setLoadingDetails(true)

    try {
      const [details, runs] = await Promise.all([
        pipelinesApi.getPipeline(token!, slug),
        pipelinesApi.listRuns(token!, slug, { limit: 5 }),
      ])
      setPipelineDetails(details)
      setPipelineRuns(runs.runs)
    } catch (err: any) {
      setError(err.message || 'Failed to load pipeline details')
      setTimeout(() => setError(''), 5000)
    } finally {
      setLoadingDetails(false)
    }
  }

  // Run pipeline
  const handleRun = async (slug: string) => {
    if (!token) return

    setRunningPipeline(slug)
    try {
      const result = await pipelinesApi.runPipeline(token, slug, {}, false)
      setSuccessMessage(`Pipeline ${slug} started (Run ID: ${result.pipeline_run_id || result.run_id})`)
      setTimeout(() => setSuccessMessage(''), 5000)
      const runId = result.pipeline_run_id || result.run_id
      if (runId) {
        const pipeline = pipelines.find(p => p.slug === slug)
        addJob({
          runId,
          jobType: 'pipeline',
          displayName: pipeline?.name || slug,
          resourceId: slug,
          resourceType: 'pipeline',
        })
      }
      // Refresh to show new run
      if (expandedPipeline === slug) {
        const runsData = await pipelinesApi.listRuns(token, slug, { limit: 5 })
        setPipelineRuns(runsData.runs)
      }
    } catch (err: any) {
      setError(err.message || `Failed to run pipeline ${slug}`)
      setTimeout(() => setError(''), 5000)
    } finally {
      setRunningPipeline(null)
    }
  }

  // Toggle pipeline active state
  const handleToggleActive = async (pipeline: PipelineListItem) => {
    if (!token) return

    setTogglingPipeline(pipeline.slug)
    try {
      if (pipeline.is_active) {
        await pipelinesApi.disablePipeline(token, pipeline.slug)
        setSuccessMessage(`Pipeline ${pipeline.slug} disabled`)
      } else {
        await pipelinesApi.enablePipeline(token, pipeline.slug)
        setSuccessMessage(`Pipeline ${pipeline.slug} enabled`)
      }
      await loadData(true)
      setTimeout(() => setSuccessMessage(''), 3000)
    } catch (err: any) {
      setError(err.message || 'Failed to toggle pipeline')
      setTimeout(() => setError(''), 5000)
    } finally {
      setTogglingPipeline(null)
    }
  }

  // Get unique tags from all pipelines
  const allTags = useMemo(() => {
    const tags = new Set<string>()
    pipelines.forEach(p => p.tags.forEach(t => tags.add(t)))
    return Array.from(tags).sort()
  }, [pipelines])

  // Filter pipelines
  const filteredPipelines = useMemo(() => {
    let result = [...pipelines]

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
  }, [pipelines, searchQuery])

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin"></div>
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading pipelines...</p>
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
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 text-white shadow-lg shadow-blue-500/25 flex-shrink-0">
                <GitBranch className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  Pipelines
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  Manage multi-stage data processing pipelines
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
              placeholder="Search pipelines..."
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
              <div className="w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
                <GitBranch className="w-5 h-5 text-blue-600 dark:text-blue-400" />
              </div>
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400">Total</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{pipelines.length}</p>
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
                  {pipelines.filter(p => p.is_active).length}
                </p>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-purple-50 dark:bg-purple-900/20 flex items-center justify-center">
                <Layers className="w-5 h-5 text-purple-600 dark:text-purple-400" />
              </div>
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400">Total Stages</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">
                  {pipelines.reduce((sum, p) => sum + p.stage_count, 0)}
                </p>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center">
                <Clock className="w-5 h-5 text-amber-600 dark:text-amber-400" />
              </div>
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400">With Triggers</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">
                  {pipelines.filter(p => p.trigger_count > 0).length}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Pipelines List */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
              Pipelines
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              {filteredPipelines.length} pipeline{filteredPipelines.length !== 1 ? 's' : ''}
            </p>
          </div>

          {/* Active pipeline jobs */}
          <JobProgressPanelByType
            jobType="pipeline"
            variant="compact"
            className="px-6 py-3 space-y-2 border-b border-gray-200 dark:border-gray-700"
          />

          {filteredPipelines.length === 0 ? (
            <div className="p-12 text-center">
              <GitBranch className="w-12 h-12 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
              <p className="text-gray-500 dark:text-gray-400">No pipelines found</p>
              <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">
                {searchQuery ? 'Try adjusting your search' : 'No pipelines are configured'}
              </p>
            </div>
          ) : (
            <div className="divide-y divide-gray-200 dark:divide-gray-700">
              {filteredPipelines.map((pipeline) => (
                <div key={pipeline.id} className="px-6 py-4">
                  {/* Main row */}
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => handleExpand(pipeline.slug)}
                          className="flex items-center gap-2 text-left group"
                        >
                          {expandedPipeline === pipeline.slug ? (
                            <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0" />
                          ) : (
                            <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />
                          )}
                          <span className="text-sm font-medium text-gray-900 dark:text-white group-hover:text-indigo-600 dark:group-hover:text-indigo-400">
                            {pipeline.name}
                          </span>
                        </button>

                        {/* Status badges */}
                        {pipeline.is_active ? (
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

                        {pipeline.is_system && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                            <Settings className="w-3 h-3" />
                            System
                          </span>
                        )}

                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
                          <Layers className="w-3 h-3" />
                          {pipeline.stage_count} stage{pipeline.stage_count !== 1 ? 's' : ''}
                        </span>

                        {pipeline.trigger_count > 0 && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                            <Clock className="w-3 h-3" />
                            {pipeline.trigger_count} trigger{pipeline.trigger_count !== 1 ? 's' : ''}
                          </span>
                        )}
                      </div>

                      {pipeline.description && (
                        <p className="mt-1 ml-6 text-sm text-gray-500 dark:text-gray-400">
                          {pipeline.description}
                        </p>
                      )}

                      <div className="mt-2 ml-6 flex items-center gap-4">
                        <span className="text-xs text-gray-400 dark:text-gray-500 font-mono">
                          {pipeline.slug}
                        </span>
                        <span className="text-xs text-gray-400 dark:text-gray-500">
                          v{pipeline.version}
                        </span>
                        {pipeline.tags.length > 0 && (
                          <div className="flex items-center gap-1">
                            {pipeline.tags.map(tag => (
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
                        onClick={() => handleRun(pipeline.slug)}
                        disabled={runningPipeline === pipeline.slug || !pipeline.is_active}
                        className="gap-2"
                      >
                        {runningPipeline === pipeline.slug ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Play className="w-4 h-4" />
                        )}
                        Run
                      </Button>

                      <Button
                        variant="secondary"
                        onClick={() => handleToggleActive(pipeline)}
                        disabled={togglingPipeline === pipeline.slug}
                        className={pipeline.is_active ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}
                      >
                        {togglingPipeline === pipeline.slug ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : pipeline.is_active ? (
                          <Pause className="w-4 h-4" />
                        ) : (
                          <Play className="w-4 h-4" />
                        )}
                      </Button>
                    </div>
                  </div>

                  {/* Expanded details */}
                  {expandedPipeline === pipeline.slug && (
                    <div className="mt-4 ml-6 space-y-6">
                      {loadingDetails ? (
                        <div className="flex items-center gap-2 text-sm text-gray-500">
                          <Loader2 className="w-4 h-4 animate-spin" />
                          Loading details...
                        </div>
                      ) : pipelineDetails ? (
                        <>
                          {/* Stages Visualization */}
                          <div>
                            <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
                              Pipeline Stages
                            </h4>
                            <div className="flex items-center gap-2 overflow-x-auto pb-2">
                              {pipelineDetails.stages.map((stage, idx) => {
                                const color = getStageTypeColor(stage.type)
                                return (
                                  <div key={stage.name} className="flex items-center gap-2 flex-shrink-0">
                                    <div className={`p-3 rounded-lg bg-${color}-50 dark:bg-${color}-900/20 border border-${color}-200 dark:border-${color}-800`}>
                                      <div className="flex items-center gap-2 mb-1">
                                        <Hash className={`w-3 h-3 text-${color}-600 dark:text-${color}-400`} />
                                        <span className={`text-xs font-medium text-${color}-700 dark:text-${color}-300`}>
                                          Stage {idx + 1}
                                        </span>
                                      </div>
                                      <p className="text-sm font-medium text-gray-900 dark:text-white">
                                        {stage.name}
                                      </p>
                                      <div className="mt-1 flex items-center gap-2">
                                        <span className={`text-xs px-1.5 py-0.5 rounded bg-${color}-100 dark:bg-${color}-900/40 text-${color}-700 dark:text-${color}-300`}>
                                          {stage.type}
                                        </span>
                                        <span className="text-xs text-gray-500 dark:text-gray-400 font-mono">
                                          {stage.function}
                                        </span>
                                      </div>
                                      {stage.batch_size > 1 && (
                                        <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
                                          Batch: {stage.batch_size}
                                        </p>
                                      )}
                                    </div>
                                    {idx < pipelineDetails.stages.length - 1 && (
                                      <ArrowRight className="w-4 h-4 text-gray-400 flex-shrink-0" />
                                    )}
                                  </div>
                                )
                              })}
                            </div>
                          </div>

                          {/* Triggers */}
                          <div>
                            <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                              Triggers
                            </h4>
                            {pipelineDetails.triggers.length === 0 ? (
                              <p className="text-sm text-gray-400 dark:text-gray-500">No triggers configured</p>
                            ) : (
                              <div className="space-y-2">
                                {pipelineDetails.triggers.map((trigger, idx) => {
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

                          {/* Recent Runs */}
                          <div>
                            <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                              Recent Runs
                            </h4>
                            {pipelineRuns.length === 0 ? (
                              <p className="text-sm text-gray-400 dark:text-gray-500">No recent runs</p>
                            ) : (
                              <div className="space-y-2">
                                {pipelineRuns.map((run) => {
                                  const statusColor = getRunStatusColor(run.status)
                                  return (
                                    <div
                                      key={run.id}
                                      className="flex items-center justify-between p-3 rounded-lg bg-gray-50 dark:bg-gray-900/50"
                                    >
                                      <div className="flex items-center gap-3">
                                        <span className={`px-2 py-0.5 rounded-full text-xs font-medium bg-${statusColor}-100 text-${statusColor}-700 dark:bg-${statusColor}-900/30 dark:text-${statusColor}-400`}>
                                          {run.status === 'running' && <Loader2 className="w-3 h-3 animate-spin inline mr-1" />}
                                          {run.status}
                                        </span>
                                        <span className="text-xs text-gray-500 dark:text-gray-400">
                                          Stage {run.current_stage + 1} / {pipelineDetails.stages.length}
                                        </span>
                                        <span className="text-xs text-gray-400 dark:text-gray-500">
                                          {run.items_processed} items processed
                                        </span>
                                      </div>
                                      <div className="flex items-center gap-4">
                                        <span className="text-xs text-gray-400 dark:text-gray-500">
                                          {formatTimeAgo(run.created_at)}
                                        </span>
                                        {run.status === 'failed' && run.run_id && (
                                          <Button
                                            variant="secondary"
                                            onClick={async () => {
                                              try {
                                                await pipelinesApi.resumeRun(token!, pipeline.slug, run.id)
                                                setSuccessMessage('Pipeline run resumed')
                                                const runsData = await pipelinesApi.listRuns(token!, pipeline.slug, { limit: 5 })
                                                setPipelineRuns(runsData.runs)
                                              } catch (err: any) {
                                                setError(err.message || 'Failed to resume run')
                                              }
                                            }}
                                            className="gap-1 text-xs py-1 px-2"
                                          >
                                            <RotateCcw className="w-3 h-3" />
                                            Resume
                                          </Button>
                                        )}
                                      </div>
                                    </div>
                                  )
                                })}
                              </div>
                            )}
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

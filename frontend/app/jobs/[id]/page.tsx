'use client'

import { useEffect, useState, useRef, useCallback } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { jobsApi, utils } from '@/lib/api'
import toast from 'react-hot-toast'
import { JobReviewPanel } from '@/components/jobs/JobReviewPanel'
import { JobExportPanel } from '@/components/jobs/JobExportPanel'
import {
  ArrowLeft,
  Loader2,
  X,
  FileText,
  ClipboardList,
  Edit3,
  Download,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Clock,
  Activity
} from 'lucide-react'

interface JobDocument {
  id: string
  document_id: string
  filename: string
  status: string
  conversion_score?: number
  quality_scores?: Record<string, any>
  is_rag_ready?: boolean
  error_message?: string
  processing_time_seconds?: number
}

interface JobLog {
  id: string
  timestamp: string
  level: string
  message: string
  metadata?: Record<string, any>
}

interface JobDetail {
  id: string
  name: string
  description?: string
  status: string
  total_documents: number
  completed_documents: number
  failed_documents: number
  created_at: string
  started_at?: string
  completed_at?: string
  cancelled_at?: string
  documents: JobDocument[]
  recent_logs: JobLog[]
  processing_options: Record<string, any>
  results_summary?: Record<string, any>
}

export default function JobDetailPage() {
  const router = useRouter()
  const params = useParams()
  const jobId = params.id as string
  const { accessToken, isAuthenticated, isLoading } = useAuth()

  const [job, setJob] = useState<JobDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const [activeTab, setActiveTab] = useState<'documents' | 'logs' | 'review' | 'export'>('documents')
  const [currentTime, setCurrentTime] = useState<number>(Date.now()) // Updates every second for live timers
  const [extractionConnection, setExtractionConnection] = useState<{ name: string; engine_type: string } | null>(null)
  const [jobLogs, setJobLogs] = useState<JobLog[]>([])
  const [logsLoading, setLogsLoading] = useState(false)

  // Track when documents started processing (client-side tracking)
  const documentStartTimes = useRef<Map<string, number>>(new Map())

  // Redirect if not authenticated
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login')
    }
  }, [isLoading, isAuthenticated, router])

  const loadJobLogs = useCallback(async (pageSize: number) => {
    if (!accessToken || !isAuthenticated || !jobId) return
    try {
      setLogsLoading(true)
      const logs = await jobsApi.getJobLogs(accessToken, jobId, { page_size: pageSize })
      setJobLogs(logs as JobLog[])
    } catch (err) {
      console.error('Failed to load job logs:', err)
    } finally {
      setLogsLoading(false)
    }
  }, [accessToken, isAuthenticated, jobId])

  // Load job details initially
  useEffect(() => {
    if (!accessToken || !isAuthenticated || !jobId) return

    const loadJob = async () => {
      try {
        setLoading(true)
        setError(null)
        const jobData = await jobsApi.getJob(accessToken, jobId)
        setJob(jobData as JobDetail)

        // If extraction_engine looks like a UUID, fetch the connection to get name and engine type
        const extractionEngine = jobData.processing_options?.extraction_engine
        if (extractionEngine && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(extractionEngine)) {
          try {
            const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/connections/${extractionEngine}`, {
              headers: {
                'Authorization': `Bearer ${accessToken}`,
              },
            })
            if (response.ok) {
              const connection = await response.json()
              setExtractionConnection({
                name: connection.name || 'Unknown',
                engine_type: connection.config?.engine_type || 'unknown'
              })
            }
          } catch (err) {
            console.error('Failed to fetch extraction connection:', err)
          }
        } else if (extractionEngine) {
          // Not a UUID, use it directly (legacy format)
          setExtractionConnection({
            name: extractionEngine,
            engine_type: extractionEngine
          })
        }
        loadJobLogs(200).catch(() => undefined)
      } catch (err: any) {
        console.error('Failed to load job:', err)
        setError(err.message || 'Failed to load job details')
      } finally {
        setLoading(false)
      }
    }

    loadJob()
  }, [accessToken, isAuthenticated, jobId, loadJobLogs])

  // Track document processing start times (client-side)
  useEffect(() => {
    if (!job?.documents) return

    const now = Date.now()
    job.documents.forEach((doc) => {
      // When a document transitions to RUNNING, record its start time
      if (doc.status === 'RUNNING' && !documentStartTimes.current.has(doc.document_id)) {
        documentStartTimes.current.set(doc.document_id, now)
      }
      // Clean up completed/failed documents from tracking
      if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(doc.status)) {
        documentStartTimes.current.delete(doc.document_id)
      }
    })
  }, [job?.documents])

  // Polling effect - separate from initial load
  useEffect(() => {
    if (!accessToken || !isAuthenticated || !jobId || !job) return

    // Only poll if job is active
    const isActive = ['PENDING', 'QUEUED', 'RUNNING'].includes(job.status)
    if (!isActive) return

    const interval = setInterval(async () => {
      try {
        const jobData = await jobsApi.getJob(accessToken, jobId)
        setJob(jobData as JobDetail)
        if (activeTab === 'logs') {
          loadJobLogs(200).catch(() => undefined)
        }
      } catch (err: any) {
        console.error('Failed to poll job:', err)
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [accessToken, isAuthenticated, jobId, job?.status, activeTab, loadJobLogs])

  // Timer effect - updates currentTime every second for live elapsed time display
  useEffect(() => {
    const isActive = job && ['PENDING', 'QUEUED', 'RUNNING'].includes(job.status)
    if (!isActive) {
      return
    }

    // Update immediately when job becomes active
    setCurrentTime(Date.now())

    const timer = setInterval(() => {
      setCurrentTime(Date.now())
    }, 1000)

    return () => clearInterval(timer)
  }, [job?.status])

  const handleCancelJob = async () => {
    if (!accessToken || !jobId || !job) return

    const confirmed = window.confirm(
      'Are you sure you want to cancel this job? This will terminate all running tasks.'
    )
    if (!confirmed) return

    try {
      setCancelling(true)
      const result = await jobsApi.cancelJob(accessToken, jobId)

      // Refresh job data
      const updatedJob = await jobsApi.getJob(accessToken, jobId)
      setJob(updatedJob as JobDetail)

      alert(`Job cancelled successfully. ${result.tasks_revoked} tasks revoked.`)
    } catch (err: any) {
      console.error('Failed to cancel job:', err)
      alert(`Failed to cancel job: ${err.message}`)
    } finally {
      setCancelling(false)
    }
  }

  const handleDocumentUpdate = async (documentId: string) => {
    if (!accessToken || !jobId) return

    try {
      // Refresh job data to get updated scores
      const refreshed = await jobsApi.getJob(accessToken, jobId)
      setJob(refreshed as JobDetail)
      toast.success('Document updated successfully')
    } catch (err: any) {
      console.error('Failed to refresh job data:', err)
      toast.error('Failed to refresh job data')
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'COMPLETED':
        return 'text-emerald-700 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/30'
      case 'RUNNING':
        return 'text-indigo-700 dark:text-indigo-400 bg-indigo-100 dark:bg-indigo-900/30'
      case 'QUEUED':
        return 'text-amber-700 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/30'
      case 'FAILED':
        return 'text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-900/30'
      case 'CANCELLED':
        return 'text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800'
      case 'PENDING':
        return 'text-violet-700 dark:text-violet-400 bg-violet-100 dark:bg-violet-900/30'
      default:
        return 'text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800'
    }
  }

  const displayedLogs = jobLogs.length > 0 ? jobLogs : (job?.recent_logs || [])
  const logCount = displayedLogs.length

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString()
  }

  // Format duration - calculates live elapsed time when job is running
  // Shows seconds until 99s, then switches to minutes format
  const formatDuration = (start?: string, end?: string): string => {
    if (!start) return 'N/A'
    const startDate = new Date(start)

    // Validate the start date is valid
    if (isNaN(startDate.getTime())) {
      return 'N/A'
    }

    let seconds: number

    if (end) {
      // Job is complete, calculate from start to end
      const endDate = new Date(end)
      if (isNaN(endDate.getTime())) {
        return 'N/A'
      }
      const diff = endDate.getTime() - startDate.getTime()
      if (diff < 0) {
        return '0s'
      }
      seconds = Math.floor(diff / 1000)
    } else {
      // Job is still running, use currentTime state (updates every second)
      seconds = Math.max(0, Math.floor((currentTime - startDate.getTime()) / 1000))
    }

    // Show seconds only until 99s, then switch to minutes format
    if (seconds <= 99) {
      return `${seconds}s`
    }

    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)

    if (hours > 0) return `${hours}h ${minutes % 60}m`
    return `${minutes}m ${seconds % 60}s`
  }

  // Get elapsed time for a document (client-side tracking for RUNNING documents)
  const getDocumentElapsedTime = (doc: JobDocument): string => {
    // If document has completed processing, show the final time
    if (doc.processing_time_seconds !== undefined && doc.processing_time_seconds !== null) {
      return `${doc.processing_time_seconds.toFixed(1)}s`
    }

    // If document is RUNNING, show live elapsed time
    if (doc.status === 'RUNNING') {
      const startTime = documentStartTimes.current.get(doc.document_id)
      if (startTime) {
        const elapsed = Math.max(0, Math.floor((currentTime - startTime) / 1000))
        const minutes = Math.floor(elapsed / 60)
        if (minutes > 0) return `${minutes}m ${elapsed % 60}s`
        return `${elapsed}s`
      }
      // RUNNING but no start time tracked yet - just started
      return '0s'
    }

    // PENDING or other status - no time to show
    return '—'
  }

  const calculateProgress = () => {
    if (!job || job.total_documents === 0) return 0
    return Math.round((job.completed_documents / job.total_documents) * 100)
  }

  const getDocumentDisplayName = (doc: JobDocument): string => {
    const displayName = utils.getDisplayFilename(doc.filename)

    // If filename is just a hash (32 hex chars with no extension), use document_id as fallback
    if (/^[0-9a-f]{32}$/i.test(displayName)) {
      return `Document ${doc.document_id.substring(0, 8)}...`
    }

    return displayName
  }

  const getExtractionEngineDisplay = (connection: { name: string; engine_type: string } | null): { displayName: string; description: string; color: string } => {
    if (!connection) {
      return {
        displayName: 'Default',
        description: 'Internal',
        color: 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300'
      }
    }

    // Use the connection name as the display name
    const displayName = connection.name

    // Get description and color based on engine type
    let description = 'Custom'
    let color = 'bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300'

    switch (connection.engine_type.toLowerCase()) {
      case 'extraction-service':
        description = 'Curatore Extraction (MarkItDown + Tesseract)'
        color = 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300'
        break
      case 'docling':
        description = 'External Docling (Advanced PDF/Office)'
        color = 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
        break
      case 'tika':
        description = 'Apache Tika (Legacy)'
        color = 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300'
        break
    }

    return { displayName, description, color }
  }

  if (isLoading || !isAuthenticated) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="text-center">
          <Loader2 className="h-12 w-12 text-indigo-600 dark:text-indigo-400 animate-spin mx-auto" />
          <p className="mt-4 text-gray-600 dark:text-gray-400">Loading...</p>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="text-center">
          <Loader2 className="h-12 w-12 text-indigo-600 dark:text-indigo-400 animate-spin mx-auto" />
          <p className="mt-4 text-gray-600 dark:text-gray-400">Loading job details...</p>
        </div>
      </div>
    )
  }

  if (error || !job) {
    return (
      <div className="h-full flex flex-col bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl px-8 py-6 max-w-2xl w-full">
            <div className="flex items-center mb-4">
              <AlertCircle className="w-6 h-6 text-red-500 dark:text-red-400 mr-3" />
              <h2 className="text-lg font-semibold text-red-800 dark:text-red-200">Error Loading Job</h2>
            </div>
            <p className="text-sm text-red-700 dark:text-red-300 mb-6">{error || 'Job not found'}</p>
            <button
              onClick={() => router.push('/jobs')}
              className="inline-flex items-center px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-sm font-medium rounded-lg transition-colors"
            >
              <ArrowLeft className="w-5 h-5 mr-2" />
              Back to Jobs
            </button>
          </div>
        </div>
      </div>
    )
  }

  const progress = calculateProgress()
  const isActive = ['PENDING', 'QUEUED', 'RUNNING'].includes(job.status)

  return (
    <div className="h-full flex flex-col bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      {/* Header - Enterprise Style */}
      <div className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800">
        <div className="px-6 lg:px-8 py-5">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center space-x-4 min-w-0 flex-1">
              <button
                onClick={() => router.push('/jobs')}
                className="inline-flex items-center text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors"
              >
                <ArrowLeft className="w-5 h-5 mr-1" />
                Back
              </button>
              <div className="min-w-0 flex-1">
                <h1 className="text-2xl font-bold text-gray-900 dark:text-white truncate">{job.name}</h1>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400 font-mono">{job.id}</p>
              </div>
            </div>
            <div className="flex items-center space-x-3">
              <span className={`inline-flex items-center px-3 py-1.5 text-sm font-semibold rounded-full ${getStatusColor(job.status)}`}>
                {isActive && job.status === 'RUNNING' && (
                  <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                )}
                {job.status}
              </span>
              {isActive && (
                <button
                  onClick={handleCancelJob}
                  disabled={cancelling}
                  className="inline-flex items-center px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
                >
                  <X className="w-4 h-4 mr-2" />
                  {cancelling ? 'Cancelling...' : 'Cancel Job'}
                </button>
              )}
            </div>
          </div>

          {/* Progress Overview - Enterprise Cards */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-gradient-to-br from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 px-4 py-4 rounded-xl border border-indigo-200/50 dark:border-indigo-800/50">
              <div className="flex items-center gap-2 mb-2">
                <Activity className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                <div className="text-xs font-medium text-indigo-700 dark:text-indigo-400 uppercase tracking-wide">Progress</div>
              </div>
              <div className="flex items-center">
                <div className="flex-1 bg-indigo-200 dark:bg-indigo-800/50 rounded-full h-2.5 mr-3">
                  <div
                    className={`h-2.5 rounded-full transition-all duration-300 ${
                      job.status === 'COMPLETED' ? 'bg-emerald-500' :
                      job.status === 'FAILED' ? 'bg-red-500' :
                      'bg-indigo-600'
                    }`}
                    style={{ width: `${progress}%` }}
                  ></div>
                </div>
                <span className="text-xl font-bold text-indigo-900 dark:text-indigo-100 tabular-nums">{progress}%</span>
              </div>
            </div>
            <div className="bg-gray-50 dark:bg-gray-800/50 px-4 py-4 rounded-xl border border-gray-200/50 dark:border-gray-700/50">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                <div className="text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide">Documents</div>
              </div>
              <div className="text-2xl font-bold text-gray-900 dark:text-white mt-1 tabular-nums">
                {job.completed_documents} / {job.total_documents}
              </div>
            </div>
            <div className="bg-gray-50 dark:bg-gray-800/50 px-4 py-4 rounded-xl border border-gray-200/50 dark:border-gray-700/50">
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                <div className="text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide">Duration</div>
              </div>
              <div className="text-2xl font-bold text-gray-900 dark:text-white mt-1 tabular-nums">
                {formatDuration(job.started_at, job.completed_at || job.cancelled_at)}
              </div>
            </div>
            <div className={`px-4 py-4 rounded-xl border ${
              job.failed_documents > 0
                ? 'bg-gradient-to-br from-red-50 to-rose-50 dark:from-red-900/20 dark:to-rose-900/20 border-red-200/50 dark:border-red-800/50'
                : 'bg-gray-50 dark:bg-gray-800/50 border-gray-200/50 dark:border-gray-700/50'
            }`}>
              <div className="flex items-center gap-2">
                <XCircle className={`w-4 h-4 ${job.failed_documents > 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-500 dark:text-gray-400'}`} />
                <div className={`text-xs font-medium uppercase tracking-wide ${
                  job.failed_documents > 0 ? 'text-red-700 dark:text-red-400' : 'text-gray-600 dark:text-gray-400'
                }`}>Failed</div>
              </div>
              <div className={`text-2xl font-bold mt-1 tabular-nums ${
                job.failed_documents > 0 ? 'text-red-700 dark:text-red-300' : 'text-gray-900 dark:text-white'
              }`}>
                {job.failed_documents}
              </div>
            </div>
          </div>

          {/* Timestamps */}
          <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <div className="flex items-center">
              <span className="text-gray-500 dark:text-gray-400 mr-2">Created:</span>
              <span className="text-gray-900 dark:text-gray-100 font-medium">{formatDate(job.created_at)}</span>
            </div>
            {job.started_at && (
              <div className="flex items-center">
                <span className="text-gray-500 dark:text-gray-400 mr-2">Started:</span>
                <span className="text-gray-900 dark:text-gray-100 font-medium">{formatDate(job.started_at)}</span>
              </div>
            )}
            {job.completed_at && (
              <div className="flex items-center">
                <span className="text-gray-500 dark:text-gray-400 mr-2">Completed:</span>
                <span className="text-gray-900 dark:text-gray-100 font-medium">{formatDate(job.completed_at)}</span>
              </div>
            )}
            {job.cancelled_at && (
              <div className="flex items-center">
                <span className="text-gray-500 dark:text-gray-400 mr-2">Cancelled:</span>
                <span className="text-gray-900 dark:text-gray-100 font-medium">{formatDate(job.cancelled_at)}</span>
              </div>
            )}
            {extractionConnection && (
              <div className="flex items-center">
                <span className="text-gray-500 dark:text-gray-400 mr-2">Extraction Engine:</span>
                <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${getExtractionEngineDisplay(extractionConnection).color}`}>
                  <span className="font-semibold">{getExtractionEngineDisplay(extractionConnection).displayName}</span>
                  <span className="opacity-75">•</span>
                  <span className="opacity-90">{getExtractionEngineDisplay(extractionConnection).description}</span>
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Main Content - Full Width */}
      <div className="flex-1 overflow-auto">
        <div className="px-6 lg:px-8 py-6">
          {/* Tabs */}
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm overflow-hidden">
            <div className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
              <nav className="flex -mb-px">
                <button
                  onClick={() => setActiveTab('documents')}
                  className={`px-6 py-3.5 text-sm font-medium transition-colors ${
                    activeTab === 'documents'
                      ? 'border-b-2 border-indigo-500 text-indigo-600 dark:text-indigo-400 bg-white dark:bg-gray-900'
                      : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800'
                  }`}
                >
                  <span className="flex items-center">
                    <FileText className="w-4 h-4 mr-2" />
                    Documents
                    <span className="ml-2 px-2 py-0.5 text-xs font-semibold rounded-full bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300">
                      {job.documents.length}
                    </span>
                  </span>
                </button>
                <button
                  onClick={() => setActiveTab('logs')}
                  className={`px-6 py-3.5 text-sm font-medium transition-colors ${
                    activeTab === 'logs'
                      ? 'border-b-2 border-indigo-500 text-indigo-600 dark:text-indigo-400 bg-white dark:bg-gray-900'
                      : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800'
                  }`}
                >
                  <span className="flex items-center">
                    <ClipboardList className="w-4 h-4 mr-2" />
                    Logs
                    <span className="ml-2 px-2 py-0.5 text-xs font-semibold rounded-full bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300">
                      {logCount}
                    </span>
                  </span>
                </button>
                <button
                  onClick={() => setActiveTab('review')}
                  className={`px-6 py-3.5 text-sm font-medium transition-colors ${
                    activeTab === 'review'
                      ? 'border-b-2 border-indigo-500 text-indigo-600 dark:text-indigo-400 bg-white dark:bg-gray-900'
                      : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800'
                  }`}
                >
                  <span className="flex items-center">
                    <Edit3 className="w-4 h-4 mr-2" />
                    Review & Edit
                  </span>
                </button>
                <button
                  onClick={() => setActiveTab('export')}
                  className={`px-6 py-3.5 text-sm font-medium transition-colors ${
                    activeTab === 'export'
                      ? 'border-b-2 border-indigo-500 text-indigo-600 dark:text-indigo-400 bg-white dark:bg-gray-900'
                      : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800'
                  }`}
                >
                  <span className="flex items-center">
                    <Download className="w-4 h-4 mr-2" />
                    Export
                  </span>
                </button>
              </nav>
            </div>

            {/* Tab Content */}
            <div className="bg-white dark:bg-gray-900">
              {activeTab === 'documents' ? (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                    <thead className="bg-gray-50 dark:bg-gray-800/50">
                      <tr>
                        <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                          Filename
                        </th>
                        <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                          Status
                        </th>
                        <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                          Score
                        </th>
                        <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                          RAG Ready
                        </th>
                        <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                          Processing Time
                        </th>
                      </tr>
                    </thead>
                    <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                      {job.documents.map((doc) => (
                        <tr key={doc.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                          <td className="px-6 py-4">
                            <div className="text-sm font-medium text-gray-900 dark:text-white truncate max-w-md">{getDocumentDisplayName(doc)}</div>
                            <div className="text-xs text-gray-500 dark:text-gray-400 font-mono mt-0.5">{doc.document_id}</div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={`inline-flex items-center px-2.5 py-1 text-xs font-semibold rounded-full ${getStatusColor(doc.status)}`}>
                              {doc.status}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            {doc.conversion_score !== undefined ? (
                              <span className={`text-sm font-semibold tabular-nums ${
                                doc.conversion_score >= 70 ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'
                              }`}>
                                {doc.conversion_score}
                              </span>
                            ) : (
                              <span className="text-sm text-gray-400 dark:text-gray-500">—</span>
                            )}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            {doc.is_rag_ready === true ? (
                              <span className="inline-flex items-center text-sm font-medium text-emerald-600 dark:text-emerald-400">
                                <CheckCircle2 className="w-4 h-4 mr-1" />
                                Yes
                              </span>
                            ) : doc.is_rag_ready === false ? (
                              <span className="inline-flex items-center text-sm font-medium text-red-600 dark:text-red-400">
                                <XCircle className="w-4 h-4 mr-1" />
                                No
                              </span>
                            ) : (
                              <span className="text-sm text-gray-400 dark:text-gray-500">—</span>
                            )}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600 dark:text-gray-400 font-medium tabular-nums">
                            <span className={doc.status === 'RUNNING' ? 'text-indigo-600 dark:text-indigo-400' : ''}>
                              {getDocumentElapsedTime(doc)}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {job.documents.length === 0 && (
                    <div className="text-center py-12">
                      <FileText className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
                      <p className="text-sm font-medium text-gray-900 dark:text-white mb-1">No documents</p>
                      <p className="text-sm text-gray-500 dark:text-gray-400">This job doesn't contain any documents yet.</p>
                    </div>
                  )}
                </div>
              ) : activeTab === 'logs' ? (
                <div className="p-6">
                  <div className="space-y-2 max-h-[600px] overflow-y-auto">
                    {displayedLogs.map((log) => (
                      <div
                        key={log.id}
                        className={`p-3 rounded-lg font-mono text-xs border ${
                          log.level === 'ERROR'
                            ? 'bg-red-50 dark:bg-red-900/20 text-red-900 dark:text-red-200 border-red-200 dark:border-red-800/50'
                            : log.level === 'WARNING'
                            ? 'bg-amber-50 dark:bg-amber-900/20 text-amber-900 dark:text-amber-200 border-amber-200 dark:border-amber-800/50'
                            : log.level === 'SUCCESS'
                            ? 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-900 dark:text-emerald-200 border-emerald-200 dark:border-emerald-800/50'
                            : 'bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-200 border-gray-200 dark:border-gray-700'
                        }`}
                      >
                        <div className="flex items-start">
                          <span className="text-gray-500 dark:text-gray-400 mr-3 tabular-nums">{formatDate(log.timestamp)}</span>
                          <span className="font-semibold mr-3">[{log.level}]</span>
                          <span className="flex-1">{log.message}</span>
                        </div>
                        {log.metadata && (
                          <div className="mt-2 text-[11px] text-gray-500 dark:text-gray-400">
                            {JSON.stringify(log.metadata)}
                          </div>
                        )}
                      </div>
                    ))}
                    {logsLoading && (
                      <div className="text-center py-6 text-xs text-gray-500 dark:text-gray-400">
                        Loading logs...
                      </div>
                    )}
                    {displayedLogs.length === 0 && !logsLoading && (
                      <div className="text-center py-12">
                        <ClipboardList className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
                        <p className="text-sm font-medium text-gray-900 dark:text-white mb-1">No logs available</p>
                        <p className="text-sm text-gray-500 dark:text-gray-400">Logs will appear here as the job progresses.</p>
                      </div>
                    )}
                  </div>
                </div>
              ) : activeTab === 'review' ? (
                <div className="p-6">
                  <JobReviewPanel
                    jobId={jobId}
                    documents={job.documents}
                    onDocumentUpdate={handleDocumentUpdate}
                    accessToken={accessToken || ''}
                  />
                </div>
              ) : activeTab === 'export' ? (
                <div className="p-6">
                  <JobExportPanel
                    jobId={jobId}
                    documents={job.documents}
                    accessToken={accessToken || ''}
                  />
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

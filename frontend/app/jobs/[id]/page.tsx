'use client'

import { useEffect, useState } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { jobsApi, utils } from '@/lib/api'
import toast from 'react-hot-toast'
import { JobReviewPanel } from '@/components/jobs/JobReviewPanel'
import { JobExportPanel } from '@/components/jobs/JobExportPanel'

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
  const [currentTime, setCurrentTime] = useState(Date.now()) // For duration updates

  // Redirect if not authenticated
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login')
    }
  }, [isLoading, isAuthenticated, router])

  // Load job details initially
  useEffect(() => {
    if (!accessToken || !isAuthenticated || !jobId) return

    const loadJob = async () => {
      try {
        setLoading(true)
        setError(null)
        const jobData = await jobsApi.getJob(accessToken, jobId)
        setJob(jobData as JobDetail)
      } catch (err: any) {
        console.error('Failed to load job:', err)
        setError(err.message || 'Failed to load job details')
      } finally {
        setLoading(false)
      }
    }

    loadJob()
  }, [accessToken, isAuthenticated, jobId])

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
      } catch (err: any) {
        console.error('Failed to poll job:', err)
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [accessToken, isAuthenticated, jobId, job?.status])

  // Update current time every second for duration calculation
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(Date.now())
    }, 1000)

    return () => clearInterval(timer)
  }, [])

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
        return 'text-green-600 bg-green-100'
      case 'RUNNING':
        return 'text-blue-600 bg-blue-100'
      case 'QUEUED':
        return 'text-yellow-600 bg-yellow-100'
      case 'FAILED':
        return 'text-red-600 bg-red-100'
      case 'CANCELLED':
        return 'text-gray-600 bg-gray-100'
      case 'PENDING':
        return 'text-purple-600 bg-purple-100'
      default:
        return 'text-gray-600 bg-gray-100'
    }
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString()
  }

  const formatDuration = (start?: string, end?: string) => {
    if (!start) return 'N/A'
    const startDate = new Date(start)

    // Validate the start date is valid
    if (isNaN(startDate.getTime())) {
      return 'N/A'
    }

    // Use currentTime for live updates, or end date if job is complete
    const endDate = end ? new Date(end) : new Date(currentTime)

    // Validate end date
    if (isNaN(endDate.getTime())) {
      return 'N/A'
    }

    const diff = endDate.getTime() - startDate.getTime()

    // If difference is negative, job hasn't started yet or dates are invalid
    if (diff < 0) {
      return '0s'
    }

    const seconds = Math.floor(diff / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)

    if (hours > 0) return `${hours}h ${minutes % 60}m`
    if (minutes > 0) return `${minutes}m ${seconds % 60}s`
    return `${seconds}s`
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

  if (isLoading || !isAuthenticated) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading...</p>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading job details...</p>
        </div>
      </div>
    )
  }

  if (error || !job) {
    return (
      <div className="h-full flex flex-col bg-gray-50">
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="bg-red-50 border border-red-200 rounded-lg px-8 py-6 max-w-2xl w-full">
            <div className="flex items-center mb-4">
              <svg className="w-6 h-6 text-red-400 mr-3" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
              <h2 className="text-lg font-semibold text-red-800">Error Loading Job</h2>
            </div>
            <p className="text-sm text-red-700 mb-6">{error || 'Job not found'}</p>
            <button
              onClick={() => router.push('/jobs')}
              className="inline-flex items-center px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 transition-colors"
            >
              <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
              </svg>
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
    <div className="h-full flex flex-col bg-gray-50">
      {/* Header - Full Width */}
      <div className="bg-white border-b border-gray-200">
        <div className="px-6 lg:px-8 py-5">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center space-x-4 min-w-0 flex-1">
              <button
                onClick={() => router.push('/jobs')}
                className="inline-flex items-center text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors"
              >
                <svg className="w-5 h-5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
                Back
              </button>
              <div className="min-w-0 flex-1">
                <h1 className="text-2xl font-semibold text-gray-900 truncate">{job.name}</h1>
                <p className="mt-1 text-sm text-gray-500 font-mono">{job.id}</p>
              </div>
            </div>
            <div className="flex items-center space-x-3">
              <span className={`inline-flex items-center px-3 py-1.5 text-sm font-semibold rounded-full ${getStatusColor(job.status)}`}>
                {isActive && job.status === 'RUNNING' && (
                  <svg className="w-3.5 h-3.5 mr-1.5 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                )}
                {job.status}
              </span>
              {isActive && (
                <button
                  onClick={handleCancelJob}
                  disabled={cancelling}
                  className="inline-flex items-center px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
                >
                  <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                  {cancelling ? 'Cancelling...' : 'Cancel Job'}
                </button>
              )}
            </div>
          </div>

          {/* Progress Overview */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-gradient-to-br from-blue-50 to-blue-100/50 px-4 py-4 rounded-lg border border-blue-200/50">
              <div className="text-xs font-medium text-blue-700 uppercase tracking-wide mb-2">Progress</div>
              <div className="flex items-center">
                <div className="flex-1 bg-blue-200 rounded-full h-2.5 mr-3">
                  <div
                    className={`h-2.5 rounded-full transition-all duration-300 ${
                      job.status === 'COMPLETED' ? 'bg-green-500' :
                      job.status === 'FAILED' ? 'bg-red-500' :
                      'bg-blue-600'
                    }`}
                    style={{ width: `${progress}%` }}
                  ></div>
                </div>
                <span className="text-xl font-semibold text-blue-900 tabular-nums">{progress}%</span>
              </div>
            </div>
            <div className="bg-gradient-to-br from-gray-50 to-gray-100/50 px-4 py-4 rounded-lg border border-gray-200/50">
              <div className="text-xs font-medium text-gray-600 uppercase tracking-wide">Documents</div>
              <div className="text-2xl font-semibold text-gray-900 mt-1 tabular-nums">
                {job.completed_documents} / {job.total_documents}
              </div>
            </div>
            <div className="bg-gradient-to-br from-gray-50 to-gray-100/50 px-4 py-4 rounded-lg border border-gray-200/50">
              <div className="text-xs font-medium text-gray-600 uppercase tracking-wide">Duration</div>
              <div className="text-2xl font-semibold text-gray-900 mt-1 tabular-nums">
                {formatDuration(job.started_at, job.completed_at || job.cancelled_at)}
              </div>
            </div>
            <div className={`bg-gradient-to-br px-4 py-4 rounded-lg border ${
              job.failed_documents > 0
                ? 'from-red-50 to-red-100/50 border-red-200/50'
                : 'from-gray-50 to-gray-100/50 border-gray-200/50'
            }`}>
              <div className={`text-xs font-medium uppercase tracking-wide ${
                job.failed_documents > 0 ? 'text-red-700' : 'text-gray-600'
              }`}>Failed</div>
              <div className={`text-2xl font-semibold mt-1 tabular-nums ${
                job.failed_documents > 0 ? 'text-red-700' : 'text-gray-900'
              }`}>
                {job.failed_documents}
              </div>
            </div>
          </div>

          {/* Timestamps */}
          <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <div className="flex items-center">
              <span className="text-gray-500 mr-2">Created:</span>
              <span className="text-gray-900 font-medium">{formatDate(job.created_at)}</span>
            </div>
            {job.started_at && (
              <div className="flex items-center">
                <span className="text-gray-500 mr-2">Started:</span>
                <span className="text-gray-900 font-medium">{formatDate(job.started_at)}</span>
              </div>
            )}
            {job.completed_at && (
              <div className="flex items-center">
                <span className="text-gray-500 mr-2">Completed:</span>
                <span className="text-gray-900 font-medium">{formatDate(job.completed_at)}</span>
              </div>
            )}
            {job.cancelled_at && (
              <div className="flex items-center">
                <span className="text-gray-500 mr-2">Cancelled:</span>
                <span className="text-gray-900 font-medium">{formatDate(job.cancelled_at)}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Main Content - Full Width */}
      <div className="flex-1 overflow-auto">
        <div className="px-6 lg:px-8 py-6">
          {/* Tabs */}
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <div className="border-b border-gray-200 bg-gray-50">
              <nav className="flex -mb-px">
                <button
                  onClick={() => setActiveTab('documents')}
                  className={`px-6 py-3.5 text-sm font-medium transition-colors ${
                    activeTab === 'documents'
                      ? 'border-b-2 border-blue-500 text-blue-600 bg-white'
                      : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                  }`}
                >
                  <span className="flex items-center">
                    <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    Documents
                    <span className="ml-2 px-2 py-0.5 text-xs font-semibold rounded-full bg-gray-200 text-gray-700">
                      {job.documents.length}
                    </span>
                  </span>
                </button>
                <button
                  onClick={() => setActiveTab('logs')}
                  className={`px-6 py-3.5 text-sm font-medium transition-colors ${
                    activeTab === 'logs'
                      ? 'border-b-2 border-blue-500 text-blue-600 bg-white'
                      : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                  }`}
                >
                  <span className="flex items-center">
                    <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                    </svg>
                    Logs
                    <span className="ml-2 px-2 py-0.5 text-xs font-semibold rounded-full bg-gray-200 text-gray-700">
                      {job.recent_logs.length}
                    </span>
                  </span>
                </button>
                <button
                  onClick={() => setActiveTab('review')}
                  className={`px-6 py-3.5 text-sm font-medium transition-colors ${
                    activeTab === 'review'
                      ? 'border-b-2 border-blue-500 text-blue-600 bg-white'
                      : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                  }`}
                >
                  <span className="flex items-center">
                    <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                    Review & Edit
                  </span>
                </button>
                <button
                  onClick={() => setActiveTab('export')}
                  className={`px-6 py-3.5 text-sm font-medium transition-colors ${
                    activeTab === 'export'
                      ? 'border-b-2 border-blue-500 text-blue-600 bg-white'
                      : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                  }`}
                >
                  <span className="flex items-center">
                    <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    Export
                  </span>
                </button>
              </nav>
            </div>

            {/* Tab Content */}
            <div className="bg-white">
              {activeTab === 'documents' ? (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">
                          Filename
                        </th>
                        <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">
                          Status
                        </th>
                        <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">
                          Score
                        </th>
                        <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">
                          RAG Ready
                        </th>
                        <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">
                          Processing Time
                        </th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {job.documents.map((doc) => (
                        <tr key={doc.id} className="hover:bg-gray-50 transition-colors">
                          <td className="px-6 py-4">
                            <div className="text-sm font-medium text-gray-900 truncate max-w-md">{getDocumentDisplayName(doc)}</div>
                            <div className="text-xs text-gray-500 font-mono mt-0.5">{doc.document_id}</div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={`inline-flex items-center px-2.5 py-1 text-xs font-semibold rounded-full ${getStatusColor(doc.status)}`}>
                              {doc.status}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            {doc.conversion_score !== undefined ? (
                              <span className={`text-sm font-semibold tabular-nums ${
                                doc.conversion_score >= 70 ? 'text-green-600' : 'text-yellow-600'
                              }`}>
                                {doc.conversion_score}
                              </span>
                            ) : (
                              <span className="text-sm text-gray-400">—</span>
                            )}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            {doc.is_rag_ready === true ? (
                              <span className="inline-flex items-center text-sm font-medium text-green-600">
                                <svg className="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">
                                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                                </svg>
                                Yes
                              </span>
                            ) : doc.is_rag_ready === false ? (
                              <span className="inline-flex items-center text-sm font-medium text-red-600">
                                <svg className="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">
                                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                                </svg>
                                No
                              </span>
                            ) : (
                              <span className="text-sm text-gray-400">—</span>
                            )}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600 font-medium tabular-nums">
                            {doc.processing_time_seconds
                              ? `${doc.processing_time_seconds.toFixed(1)}s`
                              : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {job.documents.length === 0 && (
                    <div className="text-center py-12">
                      <svg className="w-12 h-12 text-gray-300 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      <p className="text-sm font-medium text-gray-900 mb-1">No documents</p>
                      <p className="text-sm text-gray-500">This job doesn't contain any documents yet.</p>
                    </div>
                  )}
                </div>
              ) : activeTab === 'logs' ? (
                <div className="p-6">
                  <div className="space-y-2 max-h-[600px] overflow-y-auto">
                    {job.recent_logs.map((log) => (
                      <div
                        key={log.id}
                        className={`p-3 rounded-lg font-mono text-xs border ${
                          log.level === 'ERROR'
                            ? 'bg-red-50 text-red-900 border-red-200'
                            : log.level === 'WARNING'
                            ? 'bg-yellow-50 text-yellow-900 border-yellow-200'
                            : log.level === 'SUCCESS'
                            ? 'bg-green-50 text-green-900 border-green-200'
                            : 'bg-gray-50 text-gray-900 border-gray-200'
                        }`}
                      >
                        <div className="flex items-start">
                          <span className="text-gray-500 mr-3 tabular-nums">{formatDate(log.timestamp)}</span>
                          <span className="font-semibold mr-3">[{log.level}]</span>
                          <span className="flex-1">{log.message}</span>
                        </div>
                      </div>
                    ))}
                    {job.recent_logs.length === 0 && (
                      <div className="text-center py-12">
                        <svg className="w-12 h-12 text-gray-300 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                        </svg>
                        <p className="text-sm font-medium text-gray-900 mb-1">No logs available</p>
                        <p className="text-sm text-gray-500">Logs will appear here as the job progresses.</p>
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

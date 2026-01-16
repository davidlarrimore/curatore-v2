'use client'

import { useEffect, useState } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { jobsApi } from '@/lib/api'

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
  const [activeTab, setActiveTab] = useState<'documents' | 'logs'>('documents')

  // Redirect if not authenticated
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login')
    }
  }, [isLoading, isAuthenticated, router])

  // Load job details
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

    // Poll for updates every 2 seconds if job is active
    const interval = setInterval(() => {
      if (job && ['PENDING', 'QUEUED', 'RUNNING'].includes(job.status)) {
        loadJob()
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [accessToken, isAuthenticated, jobId])

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
    const endDate = end ? new Date(end) : new Date()
    const diff = endDate.getTime() - startDate.getTime()
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
      <div className="min-h-screen bg-gray-50 p-8">
        <div className="max-w-7xl mx-auto">
          <div className="bg-red-50 border border-red-200 rounded-lg p-6">
            <h2 className="text-lg font-semibold text-red-800 mb-2">Error</h2>
            <p className="text-red-700">{error || 'Job not found'}</p>
            <button
              onClick={() => router.push('/jobs')}
              className="mt-4 px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700"
            >
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
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <button
                onClick={() => router.push('/jobs')}
                className="text-gray-600 hover:text-gray-900"
              >
                ← Back to Jobs
              </button>
              <div>
                <h1 className="text-2xl font-bold text-gray-900">{job.name}</h1>
                <p className="mt-1 text-sm text-gray-600">Job ID: {job.id}</p>
              </div>
            </div>
            <div className="flex items-center space-x-4">
              <span className={`px-3 py-1 text-sm font-semibold rounded-full ${getStatusColor(job.status)}`}>
                {job.status}
              </span>
              {isActive && (
                <button
                  onClick={handleCancelJob}
                  disabled={cancelling}
                  className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {cancelling ? 'Cancelling...' : 'Cancel Job'}
                </button>
              )}
            </div>
          </div>

          {/* Progress Overview */}
          <div className="mt-6 grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-gray-50 p-4 rounded-lg">
              <div className="text-sm text-gray-600">Progress</div>
              <div className="mt-2 flex items-center">
                <div className="flex-1 bg-gray-200 rounded-full h-2 mr-2">
                  <div
                    className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${progress}%` }}
                  ></div>
                </div>
                <span className="text-lg font-bold text-gray-900">{progress}%</span>
              </div>
            </div>
            <div className="bg-gray-50 p-4 rounded-lg">
              <div className="text-sm text-gray-600">Documents</div>
              <div className="text-2xl font-bold text-gray-900 mt-1">
                {job.completed_documents}/{job.total_documents}
              </div>
            </div>
            <div className="bg-gray-50 p-4 rounded-lg">
              <div className="text-sm text-gray-600">Duration</div>
              <div className="text-2xl font-bold text-gray-900 mt-1">
                {formatDuration(job.started_at, job.completed_at || job.cancelled_at)}
              </div>
            </div>
            <div className="bg-gray-50 p-4 rounded-lg">
              <div className="text-sm text-gray-600">Failed</div>
              <div className={`text-2xl font-bold mt-1 ${job.failed_documents > 0 ? 'text-red-600' : 'text-gray-900'}`}>
                {job.failed_documents}
              </div>
            </div>
          </div>

          {/* Timestamps */}
          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
            <div>
              <span className="text-gray-600">Created:</span>
              <span className="ml-2 text-gray-900">{formatDate(job.created_at)}</span>
            </div>
            {job.started_at && (
              <div>
                <span className="text-gray-600">Started:</span>
                <span className="ml-2 text-gray-900">{formatDate(job.started_at)}</span>
              </div>
            )}
            {job.completed_at && (
              <div>
                <span className="text-gray-600">Completed:</span>
                <span className="ml-2 text-gray-900">{formatDate(job.completed_at)}</span>
              </div>
            )}
            {job.cancelled_at && (
              <div>
                <span className="text-gray-600">Cancelled:</span>
                <span className="ml-2 text-gray-900">{formatDate(job.cancelled_at)}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Tabs */}
        <div className="bg-white rounded-lg shadow">
          <div className="border-b border-gray-200">
            <nav className="flex -mb-px">
              <button
                onClick={() => setActiveTab('documents')}
                className={`px-6 py-3 text-sm font-medium ${
                  activeTab === 'documents'
                    ? 'border-b-2 border-blue-500 text-blue-600'
                    : 'text-gray-600 hover:text-gray-900 hover:border-gray-300'
                }`}
              >
                Documents ({job.documents.length})
              </button>
              <button
                onClick={() => setActiveTab('logs')}
                className={`px-6 py-3 text-sm font-medium ${
                  activeTab === 'logs'
                    ? 'border-b-2 border-blue-500 text-blue-600'
                    : 'text-gray-600 hover:text-gray-900 hover:border-gray-300'
                }`}
              >
                Logs ({job.recent_logs.length})
              </button>
            </nav>
          </div>

          {/* Tab Content */}
          <div className="p-6">
            {activeTab === 'documents' ? (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead>
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Filename
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Status
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Score
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        RAG Ready
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Processing Time
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {job.documents.map((doc) => (
                      <tr key={doc.id} className="hover:bg-gray-50">
                        <td className="px-6 py-4">
                          <div className="text-sm font-medium text-gray-900">{doc.filename}</div>
                          <div className="text-sm text-gray-500">{doc.document_id}</div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span className={`px-2 py-1 text-xs font-semibold rounded-full ${getStatusColor(doc.status)}`}>
                            {doc.status}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm">
                          {doc.conversion_score !== undefined ? (
                            <span className={doc.conversion_score >= 70 ? 'text-green-600' : 'text-yellow-600'}>
                              {doc.conversion_score}
                            </span>
                          ) : (
                            <span className="text-gray-400">-</span>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm">
                          {doc.is_rag_ready === true ? (
                            <span className="text-green-600">✓ Yes</span>
                          ) : doc.is_rag_ready === false ? (
                            <span className="text-red-600">✗ No</span>
                          ) : (
                            <span className="text-gray-400">-</span>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                          {doc.processing_time_seconds
                            ? `${doc.processing_time_seconds.toFixed(1)}s`
                            : '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {job.documents.length === 0 && (
                  <div className="text-center py-8 text-gray-500">
                    No documents in this job
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {job.recent_logs.map((log) => (
                  <div
                    key={log.id}
                    className={`p-3 rounded font-mono text-xs ${
                      log.level === 'ERROR'
                        ? 'bg-red-50 text-red-800'
                        : log.level === 'WARNING'
                        ? 'bg-yellow-50 text-yellow-800'
                        : log.level === 'SUCCESS'
                        ? 'bg-green-50 text-green-800'
                        : 'bg-gray-50 text-gray-800'
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <span className="text-gray-500">{formatDate(log.timestamp)}</span>
                        <span className="ml-3 font-semibold">[{log.level}]</span>
                        <span className="ml-3">{log.message}</span>
                      </div>
                    </div>
                  </div>
                ))}
                {job.recent_logs.length === 0 && (
                  <div className="text-center py-8 text-gray-500">
                    No logs available
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

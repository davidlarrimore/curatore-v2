'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { jobsApi } from '@/lib/api'
import { CreateJobPanel } from '@/components/jobs/CreateJobPanel'

interface Job {
  id: string
  name: string
  status: string
  total_documents: number
  completed_documents: number
  failed_documents: number
  created_at: string
  started_at?: string
  completed_at?: string
}

interface JobStats {
  active_jobs: number
  total_jobs_24h: number
  total_jobs_7d: number
  completed_jobs_24h: number
  failed_jobs_24h: number
}

export default function JobsPage() {
  const router = useRouter()
  const { user, accessToken, isAuthenticated, isLoading } = useAuth()

  const [jobs, setJobs] = useState<Job[]>([])
  const [stats, setStats] = useState<JobStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const pageSize = 20
  const [showCreateJobPanel, setShowCreateJobPanel] = useState(false)

  // Redirect if not authenticated
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login')
    }
  }, [isLoading, isAuthenticated, router])

  // Load jobs and stats
  useEffect(() => {
    if (!accessToken || !isAuthenticated) return

    const loadData = async () => {
      try {
        setLoading(true)
        setError(null)

        // Load jobs
        const jobsResponse = await jobsApi.listJobs(accessToken, {
          status: statusFilter === 'all' ? undefined : statusFilter,
          page,
          page_size: pageSize,
        })
        setJobs(jobsResponse.jobs)
        setTotalPages(jobsResponse.total_pages)

        // Load user stats
        const statsResponse = await jobsApi.getUserStats(accessToken)
        setStats(statsResponse)
      } catch (err: any) {
        console.error('Failed to load jobs:', err)
        setError(err.message || 'Failed to load jobs')
      } finally {
        setLoading(false)
      }
    }

    loadData()

    // Poll for updates every 5 seconds when there are active jobs
    const interval = setInterval(() => {
      if (stats && stats.active_jobs > 0) {
        loadData()
      }
    }, 5000)

    return () => clearInterval(interval)
  }, [accessToken, isAuthenticated, statusFilter, page])

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
      default:
        return 'text-gray-600 bg-gray-100'
    }
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const seconds = Math.floor(diff / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)
    const days = Math.floor(hours / 24)

    if (days > 0) return `${days}d ago`
    if (hours > 0) return `${hours}h ago`
    if (minutes > 0) return `${minutes}m ago`
    return 'Just now'
  }

  const calculateProgress = (job: Job) => {
    if (job.total_documents === 0) return 0
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

  return (
    <div className="h-full flex flex-col bg-gray-50">
      {/* Header - Full Width */}
      <div className="bg-white border-b border-gray-200">
        <div className="px-6 lg:px-8 py-5">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">Jobs</h1>
              <p className="mt-1 text-sm text-gray-500">
                Manage and monitor your document processing jobs
              </p>
            </div>
            <button
              onClick={() => setShowCreateJobPanel(true)}
              className="inline-flex items-center px-4 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-all shadow-sm"
            >
              <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Create New Job
            </button>
          </div>

          {/* Stats Bar */}
          {stats && (
            <div className="mt-6 grid grid-cols-2 md:grid-cols-5 gap-4">
              <div className="bg-gradient-to-br from-blue-50 to-blue-100/50 px-4 py-3.5 rounded-lg border border-blue-200/50">
                <div className="text-2xl font-semibold text-blue-900">{stats.active_jobs}</div>
                <div className="text-xs font-medium text-blue-700 uppercase tracking-wide">Active Jobs</div>
              </div>
              <div className="bg-gradient-to-br from-gray-50 to-gray-100/50 px-4 py-3.5 rounded-lg border border-gray-200/50">
                <div className="text-2xl font-semibold text-gray-900">{stats.total_jobs_24h}</div>
                <div className="text-xs font-medium text-gray-600 uppercase tracking-wide">Last 24 Hours</div>
              </div>
              <div className="bg-gradient-to-br from-gray-50 to-gray-100/50 px-4 py-3.5 rounded-lg border border-gray-200/50">
                <div className="text-2xl font-semibold text-gray-900">{stats.total_jobs_7d}</div>
                <div className="text-xs font-medium text-gray-600 uppercase tracking-wide">Last 7 Days</div>
              </div>
              <div className="bg-gradient-to-br from-green-50 to-green-100/50 px-4 py-3.5 rounded-lg border border-green-200/50">
                <div className="text-2xl font-semibold text-green-700">{stats.completed_jobs_24h}</div>
                <div className="text-xs font-medium text-green-700 uppercase tracking-wide">Completed (24h)</div>
              </div>
              <div className="bg-gradient-to-br from-red-50 to-red-100/50 px-4 py-3.5 rounded-lg border border-red-200/50">
                <div className="text-2xl font-semibold text-red-700">{stats.failed_jobs_24h}</div>
                <div className="text-xs font-medium text-red-700 uppercase tracking-wide">Failed (24h)</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Main Content - Full Width */}
      <div className="flex-1 overflow-auto">
        <div className="px-6 lg:px-8 py-6">
          {/* Filters Bar */}
          <div className="bg-white rounded-lg border border-gray-200 px-5 py-3.5 mb-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <label className="text-sm font-medium text-gray-700">Status:</label>
                <select
                  value={statusFilter}
                  onChange={(e) => {
                    setStatusFilter(e.target.value)
                    setPage(1)
                  }}
                  className="block pl-3 pr-10 py-1.5 text-sm border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="all">All Statuses</option>
                  <option value="PENDING">Pending</option>
                  <option value="QUEUED">Queued</option>
                  <option value="RUNNING">Running</option>
                  <option value="COMPLETED">Completed</option>
                  <option value="FAILED">Failed</option>
                  <option value="CANCELLED">Cancelled</option>
                </select>
              </div>
              <div className="text-sm text-gray-500">
                {jobs.length} {jobs.length === 1 ? 'job' : 'jobs'}
              </div>
            </div>
          </div>

          {/* Error Message */}
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-5 py-4 mb-5">
              <div className="flex items-center">
                <svg className="w-5 h-5 text-red-400 mr-3" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
                <p className="text-sm font-medium text-red-800">{error}</p>
              </div>
            </div>
          )}

          {/* Jobs Table */}
          {loading ? (
            <div className="bg-white rounded-lg border border-gray-200 p-12 text-center">
              <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600 mx-auto"></div>
              <p className="mt-4 text-sm text-gray-500">Loading jobs...</p>
            </div>
          ) : jobs.length === 0 ? (
            <div className="bg-white rounded-lg border border-gray-200 p-12 text-center">
              <svg className="w-12 h-12 text-gray-300 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <p className="text-sm font-medium text-gray-900 mb-1">
                {statusFilter === 'all' ? 'No jobs yet' : `No ${statusFilter.toLowerCase()} jobs`}
              </p>
              <p className="text-sm text-gray-500">
                {statusFilter === 'all'
                  ? 'Create your first job to get started with batch processing.'
                  : 'Try changing the filter to see other jobs.'}
              </p>
            </div>
          ) : (
            <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">
                        Job Name
                      </th>
                      <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">
                        Status
                      </th>
                      <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">
                        Progress
                      </th>
                      <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">
                        Documents
                      </th>
                      <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">
                        Created
                      </th>
                      <th scope="col" className="px-6 py-3.5 text-right text-xs font-semibold text-gray-700 uppercase tracking-wider">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {jobs.map((job) => {
                      const progress = calculateProgress(job)
                      return (
                        <tr
                          key={job.id}
                          className="hover:bg-gray-50 cursor-pointer transition-colors"
                          onClick={() => router.push(`/jobs/${job.id}`)}
                        >
                          <td className="px-6 py-4">
                            <div className="flex items-center">
                              <div className="min-w-0 flex-1">
                                <div className="text-sm font-medium text-gray-900 truncate">{job.name}</div>
                                <div className="text-xs text-gray-500 font-mono mt-0.5">{job.id.slice(0, 8)}</div>
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={`inline-flex items-center px-2.5 py-1 text-xs font-semibold rounded-full ${getStatusColor(job.status)}`}>
                              {job.status === 'RUNNING' && (
                                <svg className="w-3 h-3 mr-1.5 animate-spin" fill="none" viewBox="0 0 24 24">
                                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                </svg>
                              )}
                              {job.status}
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex items-center min-w-[180px]">
                              <div className="flex-1 bg-gray-200 rounded-full h-2 mr-3">
                                <div
                                  className={`h-2 rounded-full transition-all ${
                                    job.status === 'COMPLETED' ? 'bg-green-500' :
                                    job.status === 'FAILED' ? 'bg-red-500' :
                                    job.status === 'RUNNING' ? 'bg-blue-500' :
                                    'bg-gray-400'
                                  }`}
                                  style={{ width: `${progress}%` }}
                                ></div>
                              </div>
                              <span className="text-sm font-medium text-gray-700 tabular-nums">{progress}%</span>
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div className="text-sm text-gray-900 font-medium">
                              {job.completed_documents} / {job.total_documents}
                            </div>
                            {job.failed_documents > 0 && (
                              <div className="text-xs text-red-600 font-medium mt-0.5">
                                {job.failed_documents} failed
                              </div>
                            )}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                            {formatDate(job.created_at)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                router.push(`/jobs/${job.id}`)
                              }}
                              className="text-blue-600 hover:text-blue-800 font-medium transition-colors"
                            >
                              View Details →
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="bg-gray-50 px-6 py-4 flex items-center justify-between border-t border-gray-200">
                  <div className="flex-1 flex justify-between sm:hidden">
                    <button
                      onClick={() => setPage(p => Math.max(1, p - 1))}
                      disabled={page === 1}
                      className="relative inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      Previous
                    </button>
                    <button
                      onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                      disabled={page === totalPages}
                      className="ml-3 relative inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      Next
                    </button>
                  </div>
                  <div className="hidden sm:flex sm:flex-1 sm:items-center sm:justify-between">
                    <div>
                      <p className="text-sm text-gray-700">
                        Page <span className="font-semibold">{page}</span> of{' '}
                        <span className="font-semibold">{totalPages}</span>
                      </p>
                    </div>
                    <div>
                      <nav className="relative z-0 inline-flex rounded-md shadow-sm -space-x-px">
                        <button
                          onClick={() => setPage(p => Math.max(1, p - 1))}
                          disabled={page === 1}
                          className="relative inline-flex items-center px-3 py-2 rounded-l-md border border-gray-300 bg-white text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                          </svg>
                          <span className="ml-1">Previous</span>
                        </button>
                        <button
                          onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                          disabled={page === totalPages}
                          className="relative inline-flex items-center px-3 py-2 rounded-r-md border border-gray-300 bg-white text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                          <span className="mr-1">Next</span>
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                          </svg>
                        </button>
                      </nav>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Create Job Panel */}
      <CreateJobPanel
        isOpen={showCreateJobPanel}
        onClose={() => setShowCreateJobPanel(false)}
        onJobCreated={(jobId) => {
          setShowCreateJobPanel(false)
          router.push(`/jobs/${jobId}`)
        }}
      />
    </div>
  )
}

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
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Jobs</h1>
              <p className="mt-1 text-sm text-gray-600">
                Manage and monitor your document processing jobs
              </p>
            </div>
            <button
              onClick={() => setShowCreateJobPanel(true)}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
            >
              Create New Job
            </button>
          </div>

          {/* Stats Bar */}
          {stats && (
            <div className="mt-6 grid grid-cols-2 md:grid-cols-5 gap-4">
              <div className="bg-gray-50 p-4 rounded-lg">
                <div className="text-2xl font-bold text-gray-900">{stats.active_jobs}</div>
                <div className="text-sm text-gray-600">Active</div>
              </div>
              <div className="bg-gray-50 p-4 rounded-lg">
                <div className="text-2xl font-bold text-gray-900">{stats.total_jobs_24h}</div>
                <div className="text-sm text-gray-600">Last 24h</div>
              </div>
              <div className="bg-gray-50 p-4 rounded-lg">
                <div className="text-2xl font-bold text-gray-900">{stats.total_jobs_7d}</div>
                <div className="text-sm text-gray-600">Last 7d</div>
              </div>
              <div className="bg-gray-50 p-4 rounded-lg">
                <div className="text-2xl font-bold text-green-600">{stats.completed_jobs_24h}</div>
                <div className="text-sm text-gray-600">Completed (24h)</div>
              </div>
              <div className="bg-gray-50 p-4 rounded-lg">
                <div className="text-2xl font-bold text-red-600">{stats.failed_jobs_24h}</div>
                <div className="text-sm text-gray-600">Failed (24h)</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Filters */}
        <div className="bg-white rounded-lg shadow p-4 mb-6">
          <div className="flex items-center space-x-4">
            <label className="text-sm font-medium text-gray-700">Filter by status:</label>
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value)
                setPage(1) // Reset to first page
              }}
              className="block rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
            >
              <option value="all">All</option>
              <option value="PENDING">Pending</option>
              <option value="QUEUED">Queued</option>
              <option value="RUNNING">Running</option>
              <option value="COMPLETED">Completed</option>
              <option value="FAILED">Failed</option>
              <option value="CANCELLED">Cancelled</option>
            </select>
          </div>
        </div>

        {/* Error Message */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
            <p className="text-red-800">{error}</p>
          </div>
        )}

        {/* Jobs List */}
        {loading ? (
          <div className="bg-white rounded-lg shadow p-8 text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
            <p className="mt-4 text-gray-600">Loading jobs...</p>
          </div>
        ) : jobs.length === 0 ? (
          <div className="bg-white rounded-lg shadow p-8 text-center">
            <p className="text-gray-600">
              {statusFilter === 'all'
                ? 'No jobs found. Create your first job to get started.'
                : `No ${statusFilter.toLowerCase()} jobs found.`}
            </p>
          </div>
        ) : (
          <div className="bg-white rounded-lg shadow overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Job Name
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Progress
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Documents
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Created
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {jobs.map((job) => {
                  const progress = calculateProgress(job)
                  return (
                    <tr key={job.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => setSelectedJobId(job.id)}>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="text-sm font-medium text-gray-900">{job.name}</div>
                        <div className="text-sm text-gray-500">{job.id.slice(0, 8)}</div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`px-2 py-1 text-xs font-semibold rounded-full ${getStatusColor(job.status)}`}>
                          {job.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center">
                          <div className="w-full bg-gray-200 rounded-full h-2 mr-2">
                            <div
                              className="bg-blue-600 h-2 rounded-full"
                              style={{ width: `${progress}%` }}
                            ></div>
                          </div>
                          <span className="text-sm text-gray-600">{progress}%</span>
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                        {job.completed_documents}/{job.total_documents}
                        {job.failed_documents > 0 && (
                          <span className="text-red-600 ml-2">({job.failed_documents} failed)</span>
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
                          className="text-blue-600 hover:text-blue-900"
                        >
                          View Details
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="bg-gray-50 px-4 py-3 flex items-center justify-between border-t border-gray-200">
                <div className="flex-1 flex justify-between sm:hidden">
                  <button
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="relative inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
                  >
                    Previous
                  </button>
                  <button
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    className="ml-3 relative inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
                  >
                    Next
                  </button>
                </div>
                <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
                  <div>
                    <p className="text-sm text-gray-700">
                      Page <span className="font-medium">{page}</span> of{' '}
                      <span className="font-medium">{totalPages}</span>
                    </p>
                  </div>
                  <div>
                    <nav className="relative z-0 inline-flex rounded-md shadow-sm -space-x-px">
                      <button
                        onClick={() => setPage(p => Math.max(1, p - 1))}
                        disabled={page === 1}
                        className="relative inline-flex items-center px-2 py-2 rounded-l-md border border-gray-300 bg-white text-sm font-medium text-gray-500 hover:bg-gray-50 disabled:opacity-50"
                      >
                        Previous
                      </button>
                      <button
                        onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                        disabled={page === totalPages}
                        className="relative inline-flex items-center px-2 py-2 rounded-r-md border border-gray-300 bg-white text-sm font-medium text-gray-500 hover:bg-gray-50 disabled:opacity-50"
                      >
                        Next
                      </button>
                    </nav>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
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

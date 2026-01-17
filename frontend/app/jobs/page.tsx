'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { jobsApi } from '@/lib/api'
import { CreateJobPanel } from '@/components/jobs/CreateJobPanel'
import {
  Briefcase,
  Plus,
  Clock,
  CheckCircle2,
  XCircle,
  Activity,
  ChevronLeft,
  ChevronRight,
  Loader2,
  FileText,
  AlertCircle
} from 'lucide-react'

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
        return 'text-emerald-700 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/30'
      case 'RUNNING':
        return 'text-indigo-700 dark:text-indigo-400 bg-indigo-100 dark:bg-indigo-900/30'
      case 'QUEUED':
        return 'text-amber-700 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/30'
      case 'FAILED':
        return 'text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-900/30'
      case 'CANCELLED':
        return 'text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800'
      default:
        return 'text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800'
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
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="text-center">
          <Loader2 className="h-12 w-12 text-indigo-600 dark:text-indigo-400 animate-spin mx-auto" />
          <p className="mt-4 text-gray-600 dark:text-gray-400">Loading...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      {/* Header - Enterprise Style */}
      <div className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800">
        <div className="px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="p-3 bg-gradient-to-br from-violet-500 to-purple-600 rounded-xl shadow-lg shadow-violet-500/25">
                <Briefcase className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Jobs</h1>
                <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">
                  Manage and monitor your document processing jobs
                </p>
              </div>
            </div>
            <button
              onClick={() => setShowCreateJobPanel(true)}
              className="inline-flex items-center px-4 py-2.5 bg-gradient-to-r from-indigo-600 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-indigo-700 hover:to-purple-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition-all shadow-lg shadow-indigo-500/25"
            >
              <Plus className="w-5 h-5 mr-2" />
              Create New Job
            </button>
          </div>

          {/* Stats Bar - Enterprise Cards */}
          {stats && (
            <div className="mt-6 grid grid-cols-2 md:grid-cols-5 gap-4">
              <div className="bg-gradient-to-br from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 px-4 py-3.5 rounded-xl border border-indigo-200/50 dark:border-indigo-800/50">
                <div className="flex items-center gap-2">
                  <Activity className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                  <div className="text-2xl font-bold text-indigo-900 dark:text-indigo-100">{stats.active_jobs}</div>
                </div>
                <div className="text-xs font-medium text-indigo-700 dark:text-indigo-400 uppercase tracking-wide mt-1">Active Jobs</div>
              </div>
              <div className="bg-gray-50 dark:bg-gray-800/50 px-4 py-3.5 rounded-xl border border-gray-200/50 dark:border-gray-700/50">
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">{stats.total_jobs_24h}</div>
                </div>
                <div className="text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mt-1">Last 24 Hours</div>
              </div>
              <div className="bg-gray-50 dark:bg-gray-800/50 px-4 py-3.5 rounded-xl border border-gray-200/50 dark:border-gray-700/50">
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">{stats.total_jobs_7d}</div>
                </div>
                <div className="text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mt-1">Last 7 Days</div>
              </div>
              <div className="bg-gradient-to-br from-emerald-50 to-teal-50 dark:from-emerald-900/20 dark:to-teal-900/20 px-4 py-3.5 rounded-xl border border-emerald-200/50 dark:border-emerald-800/50">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                  <div className="text-2xl font-bold text-emerald-700 dark:text-emerald-300">{stats.completed_jobs_24h}</div>
                </div>
                <div className="text-xs font-medium text-emerald-700 dark:text-emerald-400 uppercase tracking-wide mt-1">Completed (24h)</div>
              </div>
              <div className="bg-gradient-to-br from-red-50 to-rose-50 dark:from-red-900/20 dark:to-rose-900/20 px-4 py-3.5 rounded-xl border border-red-200/50 dark:border-red-800/50">
                <div className="flex items-center gap-2">
                  <XCircle className="w-4 h-4 text-red-600 dark:text-red-400" />
                  <div className="text-2xl font-bold text-red-700 dark:text-red-300">{stats.failed_jobs_24h}</div>
                </div>
                <div className="text-xs font-medium text-red-700 dark:text-red-400 uppercase tracking-wide mt-1">Failed (24h)</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Main Content - Full Width */}
      <div className="flex-1 overflow-auto">
        <div className="px-6 lg:px-8 py-6">
          {/* Filters Bar */}
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm px-5 py-3.5 mb-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Status:</label>
                <select
                  value={statusFilter}
                  onChange={(e) => {
                    setStatusFilter(e.target.value)
                    setPage(1)
                  }}
                  className="block pl-3 pr-10 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
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
              <div className="text-sm text-gray-500 dark:text-gray-400">
                {jobs.length} {jobs.length === 1 ? 'job' : 'jobs'}
              </div>
            </div>
          </div>

          {/* Error Message */}
          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl px-5 py-4 mb-5">
              <div className="flex items-center">
                <AlertCircle className="w-5 h-5 text-red-500 dark:text-red-400 mr-3" />
                <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
              </div>
            </div>
          )}

          {/* Jobs Table */}
          {loading ? (
            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm p-12 text-center">
              <Loader2 className="h-10 w-10 text-indigo-600 dark:text-indigo-400 animate-spin mx-auto" />
              <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading jobs...</p>
            </div>
          ) : jobs.length === 0 ? (
            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm p-12 text-center">
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center">
                <Briefcase className="w-8 h-8 text-gray-400 dark:text-gray-500" />
              </div>
              <p className="text-base font-medium text-gray-900 dark:text-white mb-1">
                {statusFilter === 'all' ? 'No jobs yet' : `No ${statusFilter.toLowerCase()} jobs`}
              </p>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
                {statusFilter === 'all'
                  ? 'Create your first job to get started with batch processing.'
                  : 'Try changing the filter to see other jobs.'}
              </p>
              {statusFilter === 'all' && (
                <button
                  onClick={() => setShowCreateJobPanel(true)}
                  className="inline-flex items-center px-4 py-2 bg-gradient-to-r from-indigo-600 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-indigo-700 hover:to-purple-700 transition-all shadow-lg shadow-indigo-500/25"
                >
                  <Plus className="w-4 h-4 mr-2" />
                  Create Your First Job
                </button>
              )}
            </div>
          ) : (
            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-800">
                  <thead className="bg-gray-50 dark:bg-gray-800/50">
                    <tr>
                      <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider">
                        Job Name
                      </th>
                      <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider">
                        Status
                      </th>
                      <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider">
                        Progress
                      </th>
                      <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider">
                        Documents
                      </th>
                      <th scope="col" className="px-6 py-3.5 text-left text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider">
                        Created
                      </th>
                      <th scope="col" className="px-6 py-3.5 text-right text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-800">
                    {jobs.map((job) => {
                      const progress = calculateProgress(job)
                      return (
                        <tr
                          key={job.id}
                          className="hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer transition-colors"
                          onClick={() => router.push(`/jobs/${job.id}`)}
                        >
                          <td className="px-6 py-4">
                            <div className="flex items-center">
                              <div className="min-w-0 flex-1">
                                <div className="text-sm font-medium text-gray-900 dark:text-white truncate">{job.name}</div>
                                <div className="text-xs text-gray-500 dark:text-gray-500 font-mono mt-0.5">{job.id.slice(0, 8)}</div>
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={`inline-flex items-center px-2.5 py-1 text-xs font-semibold rounded-full ${getStatusColor(job.status)}`}>
                              {job.status === 'RUNNING' && (
                                <Loader2 className="w-3 h-3 mr-1.5 animate-spin" />
                              )}
                              {job.status}
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex items-center min-w-[180px]">
                              <div className="flex-1 bg-gray-200 dark:bg-gray-700 rounded-full h-2 mr-3">
                                <div
                                  className={`h-2 rounded-full transition-all ${
                                    job.status === 'COMPLETED' ? 'bg-emerald-500' :
                                    job.status === 'FAILED' ? 'bg-red-500' :
                                    job.status === 'RUNNING' ? 'bg-indigo-500' :
                                    'bg-gray-400 dark:bg-gray-500'
                                  }`}
                                  style={{ width: `${progress}%` }}
                                ></div>
                              </div>
                              <span className="text-sm font-medium text-gray-700 dark:text-gray-300 tabular-nums">{progress}%</span>
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div className="text-sm text-gray-900 dark:text-white font-medium">
                              {job.completed_documents} / {job.total_documents}
                            </div>
                            {job.failed_documents > 0 && (
                              <div className="text-xs text-red-600 dark:text-red-400 font-medium mt-0.5">
                                {job.failed_documents} failed
                              </div>
                            )}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600 dark:text-gray-400">
                            {formatDate(job.created_at)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                router.push(`/jobs/${job.id}`)
                              }}
                              className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 font-medium transition-colors"
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
                <div className="bg-gray-50 dark:bg-gray-800/50 px-6 py-4 flex items-center justify-between border-t border-gray-200 dark:border-gray-800">
                  <div className="flex-1 flex justify-between sm:hidden">
                    <button
                      onClick={() => setPage(p => Math.max(1, p - 1))}
                      disabled={page === 1}
                      className="relative inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-lg text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      Previous
                    </button>
                    <button
                      onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                      disabled={page === totalPages}
                      className="ml-3 relative inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-lg text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      Next
                    </button>
                  </div>
                  <div className="hidden sm:flex sm:flex-1 sm:items-center sm:justify-between">
                    <div>
                      <p className="text-sm text-gray-700 dark:text-gray-300">
                        Page <span className="font-semibold">{page}</span> of{' '}
                        <span className="font-semibold">{totalPages}</span>
                      </p>
                    </div>
                    <div>
                      <nav className="relative z-0 inline-flex rounded-lg shadow-sm -space-x-px">
                        <button
                          onClick={() => setPage(p => Math.max(1, p - 1))}
                          disabled={page === 1}
                          className="relative inline-flex items-center px-3 py-2 rounded-l-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                          <ChevronLeft className="w-5 h-5" />
                          <span className="ml-1">Previous</span>
                        </button>
                        <button
                          onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                          disabled={page === totalPages}
                          className="relative inline-flex items-center px-3 py-2 rounded-r-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                          <span className="mr-1">Next</span>
                          <ChevronRight className="w-5 h-5" />
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

'use client'

import { useRouter } from 'next/navigation'
import {
  Clock,
  CheckCircle,
  XCircle,
  Loader2,
  AlertCircle,
  ArrowRight,
  FileText,
  Briefcase
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

interface RecentActivityCardProps {
  recentJobs: Job[]
  isLoading: boolean
}

export function RecentActivityCard({ recentJobs, isLoading }: RecentActivityCardProps) {
  const router = useRouter()

  const getStatusIcon = (status: string) => {
    switch (status.toLowerCase()) {
      case 'completed':
        return <CheckCircle className="w-4 h-4 text-emerald-500" />
      case 'failed':
        return <XCircle className="w-4 h-4 text-red-500" />
      case 'running':
      case 'processing':
        return <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
      case 'queued':
      case 'pending':
        return <Clock className="w-4 h-4 text-amber-500" />
      case 'cancelled':
        return <AlertCircle className="w-4 h-4 text-gray-500" />
      default:
        return <AlertCircle className="w-4 h-4 text-gray-400" />
    }
  }

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'completed':
        return 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400'
      case 'failed':
        return 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400'
      case 'running':
      case 'processing':
        return 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400'
      case 'queued':
      case 'pending':
        return 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400'
      default:
        return 'bg-gray-50 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
    }
  }

  const formatTime = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString()
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden hover:shadow-lg hover:shadow-gray-200/50 dark:hover:shadow-gray-900/50 transition-all duration-200">
      {/* Status bar at top */}
      <div className="h-1 bg-gradient-to-r from-amber-500 to-orange-500" />

      <div className="p-5">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500 to-orange-500 flex items-center justify-center text-white shadow-lg shadow-amber-500/25">
              <Clock className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-gray-900 dark:text-white">Recent Activity</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">Latest processing jobs</p>
            </div>
          </div>
          <button
            onClick={() => router.push('/jobs')}
            className="flex items-center gap-1 text-sm text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium transition-colors"
          >
            <span>View All</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 text-gray-400 animate-spin" />
          </div>
        ) : recentJobs.length === 0 ? (
          /* Empty State */
          <div className="text-center py-8">
            <div className="w-12 h-12 rounded-xl bg-gray-100 dark:bg-gray-700 flex items-center justify-center mx-auto mb-3">
              <Briefcase className="w-6 h-6 text-gray-400" />
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">No recent jobs</p>
            <p className="text-xs text-gray-400 dark:text-gray-500">
              Create a job to start processing documents
            </p>
          </div>
        ) : (
          /* Job List */
          <div className="space-y-2">
            {recentJobs.slice(0, 5).map((job) => (
              <button
                key={job.id}
                onClick={() => router.push(`/jobs/${job.id}`)}
                className="w-full flex items-center gap-3 p-3 bg-gray-50 dark:bg-gray-900/50 rounded-xl hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors text-left group"
              >
                {/* Status Icon */}
                <div className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${getStatusColor(job.status)}`}>
                  {getStatusIcon(job.status)}
                </div>

                {/* Job Info */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 dark:text-white truncate group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors">
                    {job.name}
                  </p>
                  <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                    <span className="flex items-center gap-1">
                      <FileText className="w-3 h-3" />
                      {job.completed_documents}/{job.total_documents}
                    </span>
                    <span>•</span>
                    <span>{formatTime(job.created_at)}</span>
                  </div>
                </div>

                {/* Arrow */}
                <ArrowRight className="w-4 h-4 text-gray-400 group-hover:text-indigo-500 group-hover:translate-x-1 transition-all" />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

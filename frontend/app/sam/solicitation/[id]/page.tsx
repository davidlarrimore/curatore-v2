'use client'

import { useState, useEffect, use, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { samApi, SamSolicitation, SamNotice, SamAttachment, SamSummary } from '@/lib/api'
import { formatDate as formatDateUtil, formatDateTime as formatDateTimeUtil } from '@/lib/date-utils'
import { Button } from '@/components/ui/Button'
import Link from 'next/link'
import {
  ArrowLeft,
  RefreshCw,
  Loader2,
  AlertTriangle,
  Building2,
  FileText,
  Clock,
  Zap,
  Calendar,
  ExternalLink,
  Download,
  CheckCircle,
  XCircle,
  AlertCircle,
  Tag,
  User,
  Globe,
  Paperclip,
  ChevronDown,
  ChevronUp,
  Sparkles,
  Star,
  MessageSquare,
  Eye,
} from 'lucide-react'
import { assetsApi } from '@/lib/api'
import ProtectedRoute from '@/components/auth/ProtectedRoute'

interface PageProps {
  params: Promise<{ id: string }>
}

export default function SolicitationDetailPage({ params }: PageProps) {
  return (
    <ProtectedRoute>
      <SolicitationDetailContent params={params} />
    </ProtectedRoute>
  )
}

function SolicitationDetailContent({ params }: PageProps) {
  const resolvedParams = use(params)
  const solicitationId = resolvedParams.id
  const router = useRouter()
  const { token } = useAuth()

  // State
  const [solicitation, setSolicitation] = useState<SamSolicitation | null>(null)
  const [notices, setNotices] = useState<SamNotice[]>([])
  const [attachments, setAttachments] = useState<SamAttachment[]>([])
  const [summaries, setSummaries] = useState<SamSummary[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState<'notices' | 'attachments' | 'summaries'>('notices')
  const [expandedNotice, setExpandedNotice] = useState<string | null>(null)

  // Load all data
  const loadData = useCallback(async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const [solData, noticesData, attachmentsData, summariesData] = await Promise.all([
        samApi.getSolicitation(token, solicitationId),
        samApi.getSolicitationNotices(token, solicitationId),
        samApi.getSolicitationAttachments(token, solicitationId),
        samApi.getSolicitationSummaries(token, solicitationId),
      ])
      setSolicitation(solData)
      setNotices(noticesData)
      setAttachments(attachmentsData)
      setSummaries(summariesData)
    } catch (err: any) {
      setError(err.message || 'Failed to load solicitation')
    } finally {
      setIsLoading(false)
    }
  }, [token, solicitationId])

  useEffect(() => {
    if (token) loadData()
  }, [token, loadData])

  // Use date utilities for consistent EST display
  const formatDate = (dateStr: string | null) => dateStr ? formatDateUtil(dateStr) : 'N/A'
  const formatDateTime = (dateStr: string | null) => dateStr ? formatDateTimeUtil(dateStr) : 'N/A'

  const getNoticeTypeBadge = (noticeType: string) => {
    const colors: Record<string, string> = {
      o: 'bg-blue-100 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400',
      p: 'bg-purple-100 dark:bg-purple-900/20 text-purple-700 dark:text-purple-400',
      k: 'bg-indigo-100 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-400',
      r: 'bg-amber-100 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400',
      s: 'bg-emerald-100 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400',
      a: 'bg-cyan-100 dark:bg-cyan-900/20 text-cyan-700 dark:text-cyan-400',
    }
    return colors[noticeType] || 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
  }

  // SAM.gov ptype values - see: https://open.gsa.gov/api/opportunities-api/
  const getNoticeTypeLabel = (noticeType: string) => {
    const labels: Record<string, string> = {
      k: 'Combined Synopsis',  // Combined Synopsis/Solicitation
      o: 'Solicitation',
      p: 'Presolicitation',
      r: 'Sources Sought',
      s: 'Special Notice',
      a: 'Award',
      u: 'J&A',                // Justification (J&A)
      i: 'Intent to Bundle',
      g: 'Sale of Surplus',
    }
    return labels[noticeType] || noticeType.toUpperCase()
  }

  const getDownloadStatusBadge = (status: string) => {
    switch (status) {
      case 'downloaded':
        return 'bg-emerald-100 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400'
      case 'pending':
        return 'bg-amber-100 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400'
      case 'failed':
        return 'bg-red-100 dark:bg-red-900/20 text-red-700 dark:text-red-400'
      default:
        return 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
    }
  }

  const formatFileSize = (bytes: number | null) => {
    if (!bytes) return 'Unknown'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const handleViewAsset = (assetId: string) => {
    router.push(`/assets/${assetId}`)
  }

  const handleDownloadAttachment = async (attachment: SamAttachment) => {
    if (!token || !attachment.asset_id) return

    try {
      const blob = await assetsApi.downloadOriginal(token, attachment.asset_id)
      const downloadUrl = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = downloadUrl
      a.download = attachment.filename || 'download'
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(downloadUrl)
      document.body.removeChild(a)
    } catch (err: any) {
      setError(err.message || 'Failed to download attachment')
    }
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-blue-500 animate-spin" />
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading solicitation...</p>
          </div>
        </div>
      </div>
    )
  }

  if (!solicitation) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="text-center py-16">
            <AlertTriangle className="w-12 h-12 mx-auto text-red-500 mb-4" />
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Solicitation Not Found</h2>
            <p className="text-gray-500 dark:text-gray-400 mb-6">{error || 'The requested solicitation could not be found.'}</p>
            <Link href="/sam">
              <Button variant="secondary" className="gap-2">
                <ArrowLeft className="w-4 h-4" />
                Back to SAM Searches
              </Button>
            </Link>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Back Link */}
        <button
          onClick={() => router.back()}
          className="inline-flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Search
        </button>

        {/* Header */}
        <div className="mb-8">
          <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-3 mb-2">
                <span className={`inline-flex px-2.5 py-1 text-xs font-medium rounded-full ${getNoticeTypeBadge(solicitation.notice_type)}`}>
                  {getNoticeTypeLabel(solicitation.notice_type)}
                </span>
                <span className={`inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-full ${
                  solicitation.status === 'active'
                    ? 'bg-emerald-100 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400'
                    : solicitation.status === 'awarded'
                    ? 'bg-blue-100 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400'
                    : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
                }`}>
                  {solicitation.status === 'active' && <CheckCircle className="w-3 h-3" />}
                  {solicitation.status === 'cancelled' && <XCircle className="w-3 h-3" />}
                  {solicitation.status}
                </span>
              </div>
              <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white mb-2">
                {solicitation.title}
              </h1>
              <p className="text-sm font-mono text-gray-500 dark:text-gray-400">
                {solicitation.solicitation_number || solicitation.notice_id}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                onClick={loadData}
                className="gap-2"
              >
                <RefreshCw className="w-4 h-4" />
                Refresh
              </Button>
              {solicitation.ui_link && (
                <a
                  href={solicitation.ui_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-gradient-to-r from-blue-500 to-indigo-600 rounded-lg hover:from-blue-600 hover:to-indigo-700 shadow-lg shadow-blue-500/25 transition-all"
                >
                  <ExternalLink className="w-4 h-4" />
                  View on SAM.gov
                </a>
              )}
            </div>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
            <div className="flex items-center gap-3">
              <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
              <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
            </div>
          </div>
        )}

        {/* Details Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
          {/* Main Details */}
          <div className="lg:col-span-2 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Description</h2>
            {solicitation.description ? (
              <div
                className="text-sm text-gray-600 dark:text-gray-300 prose prose-sm dark:prose-invert max-w-none prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-headings:text-gray-900 dark:prose-headings:text-white prose-a:text-blue-600 dark:prose-a:text-blue-400"
                dangerouslySetInnerHTML={{ __html: solicitation.description }}
              />
            ) : (
              <p className="text-sm text-gray-400 dark:text-gray-500 italic">No description available</p>
            )}
          </div>

          {/* Sidebar */}
          <div className="space-y-4">
            {/* Dates */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Key Dates</h3>
              <div className="space-y-3">
                <div className="flex items-center gap-3">
                  <Calendar className="w-4 h-4 text-gray-400" />
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Posted</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">
                      {formatDate(solicitation.posted_date)}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Clock className="w-4 h-4 text-gray-400" />
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Response Deadline</p>
                    <p className={`text-sm font-medium ${
                      solicitation.response_deadline && new Date(solicitation.response_deadline) < new Date()
                        ? 'text-red-600 dark:text-red-400'
                        : 'text-gray-900 dark:text-white'
                    }`}>
                      {formatDateTime(solicitation.response_deadline)}
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Classification */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Classification</h3>
              <div className="space-y-3">
                {solicitation.naics_code && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">NAICS Code</p>
                    <span className="inline-flex px-2 py-0.5 text-xs font-mono bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400 rounded">
                      {solicitation.naics_code}
                    </span>
                  </div>
                )}
                {solicitation.psc_code && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">PSC Code</p>
                    <span className="inline-flex px-2 py-0.5 text-xs font-mono bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-400 rounded">
                      {solicitation.psc_code}
                    </span>
                  </div>
                )}
                {solicitation.set_aside_code && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Set-Aside</p>
                    <span className="inline-flex px-2 py-0.5 text-xs font-mono bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 rounded">
                      {solicitation.set_aside_code}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Stats */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Items</h3>
              <div className="grid grid-cols-2 gap-4">
                <div className="text-center p-3 bg-gray-50 dark:bg-gray-900/50 rounded-lg">
                  <Zap className="w-5 h-5 text-purple-500 mx-auto mb-1" />
                  <p className="text-xl font-bold text-gray-900 dark:text-white">{notices.length}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Notices</p>
                </div>
                <div className="text-center p-3 bg-gray-50 dark:bg-gray-900/50 rounded-lg">
                  <Paperclip className="w-5 h-5 text-blue-500 mx-auto mb-1" />
                  <p className="text-xl font-bold text-gray-900 dark:text-white">{attachments.length}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Attachments</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          {/* Tab Headers */}
          <div className="flex border-b border-gray-200 dark:border-gray-700">
            <button
              onClick={() => setActiveTab('notices')}
              className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
                activeTab === 'notices'
                  ? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-500 bg-blue-50/50 dark:bg-blue-900/10'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              <div className="flex items-center justify-center gap-2">
                <Zap className="w-4 h-4" />
                Notices ({notices.length})
              </div>
            </button>
            <button
              onClick={() => setActiveTab('attachments')}
              className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
                activeTab === 'attachments'
                  ? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-500 bg-blue-50/50 dark:bg-blue-900/10'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              <div className="flex items-center justify-center gap-2">
                <Paperclip className="w-4 h-4" />
                Attachments ({attachments.length})
              </div>
            </button>
            <button
              onClick={() => setActiveTab('summaries')}
              className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
                activeTab === 'summaries'
                  ? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-500 bg-blue-50/50 dark:bg-blue-900/10'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              <div className="flex items-center justify-center gap-2">
                <Sparkles className="w-4 h-4" />
                Summaries ({summaries.length})
              </div>
            </button>
          </div>

          {/* Tab Content */}
          <div className="p-6">
            {/* Notices Tab */}
            {activeTab === 'notices' && (
              <div>
                {notices.length === 0 ? (
                  <div className="text-center py-8">
                    <Zap className="w-10 h-10 mx-auto text-gray-300 dark:text-gray-600 mb-3" />
                    <p className="text-gray-500 dark:text-gray-400">No notices found</p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {notices.map((notice) => (
                      <div
                        key={notice.id}
                        className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden"
                      >
                        <button
                          onClick={() => setExpandedNotice(expandedNotice === notice.id ? null : notice.id)}
                          className="w-full flex items-center justify-between p-4 text-left hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors"
                        >
                          <div className="flex items-center gap-4">
                            <div className="flex items-center justify-center w-10 h-10 rounded-full bg-purple-100 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400 font-bold text-sm">
                              v{notice.version_number}
                            </div>
                            <div>
                              <p className="font-medium text-gray-900 dark:text-white">
                                {notice.title || `Version ${notice.version_number}`}
                              </p>
                              <p className="text-xs text-gray-500 dark:text-gray-400">
                                Posted {formatDate(notice.posted_date)}
                                {notice.notice_type === 'a' && ' (Amendment)'}
                              </p>
                            </div>
                          </div>
                          {expandedNotice === notice.id ? (
                            <ChevronUp className="w-5 h-5 text-gray-400" />
                          ) : (
                            <ChevronDown className="w-5 h-5 text-gray-400" />
                          )}
                        </button>
                        {expandedNotice === notice.id && (
                          <div className="px-4 pb-4 border-t border-gray-100 dark:border-gray-700">
                            <div className="pt-4 space-y-3">
                              {notice.description && (
                                <div>
                                  <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Description</p>
                                  <p className="text-sm text-gray-600 dark:text-gray-300 whitespace-pre-wrap">
                                    {notice.description}
                                  </p>
                                </div>
                              )}
                              {notice.changes_summary && (
                                <div>
                                  <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Changes Summary</p>
                                  <p className="text-sm text-gray-600 dark:text-gray-300 whitespace-pre-wrap">
                                    {notice.changes_summary}
                                  </p>
                                </div>
                              )}
                              {notice.response_deadline && (
                                <div className="flex items-center gap-2 text-sm">
                                  <Clock className="w-4 h-4 text-gray-400" />
                                  <span className="text-gray-500 dark:text-gray-400">Response Deadline:</span>
                                  <span className="text-gray-900 dark:text-white">{formatDateTime(notice.response_deadline)}</span>
                                </div>
                              )}
                              <p className="text-xs text-gray-400 font-mono">
                                ID: {notice.sam_notice_id}
                              </p>
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Attachments Tab */}
            {activeTab === 'attachments' && (
              <div>
                {attachments.length === 0 ? (
                  <div className="text-center py-8">
                    <Paperclip className="w-10 h-10 mx-auto text-gray-300 dark:text-gray-600 mb-3" />
                    <p className="text-gray-500 dark:text-gray-400">No attachments found</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr className="bg-gray-50 dark:bg-gray-900/50">
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                            Filename
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                            Type
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                            Size
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                            Status
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                            Downloaded
                          </th>
                          <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                            Actions
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                        {attachments.map((attachment) => {
                          // Check if filename is pending (hasn't been downloaded yet)
                          const isPendingFilename = attachment.filename?.startsWith('pending_')
                          const displayFilename = isPendingFilename
                            ? 'Awaiting download...'
                            : attachment.filename

                          return (
                            <tr key={attachment.id} className="hover:bg-gray-50 dark:hover:bg-gray-900/50">
                              <td className="px-4 py-3">
                                <div className="flex items-center gap-2">
                                  <FileText className="w-4 h-4 text-gray-400" />
                                  <span className={`text-sm truncate max-w-xs ${isPendingFilename ? 'text-gray-400 dark:text-gray-500 italic' : 'text-gray-900 dark:text-white'}`}>
                                    {displayFilename}
                                  </span>
                                </div>
                                {isPendingFilename && attachment.resource_id && (
                                  <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 truncate max-w-xs font-mono">
                                    Resource: {attachment.resource_id.substring(0, 12)}...
                                  </p>
                                )}
                                {attachment.description && !isPendingFilename && (
                                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 truncate max-w-xs">
                                    {attachment.description}
                                  </p>
                                )}
                              </td>
                              <td className="px-4 py-3">
                                <span className="text-xs font-mono text-gray-600 dark:text-gray-400 uppercase">
                                  {attachment.file_type || (isPendingFilename ? '...' : 'unknown')}
                                </span>
                              </td>
                              <td className="px-4 py-3 text-xs text-gray-500 dark:text-gray-400">
                                {attachment.file_size ? formatFileSize(attachment.file_size) : (isPendingFilename ? '...' : 'Unknown')}
                              </td>
                              <td className="px-4 py-3">
                                <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded ${getDownloadStatusBadge(attachment.download_status)}`}>
                                  {attachment.download_status === 'downloaded' && <CheckCircle className="w-3 h-3" />}
                                  {attachment.download_status === 'pending' && <Clock className="w-3 h-3" />}
                                  {attachment.download_status === 'downloading' && <Loader2 className="w-3 h-3 animate-spin" />}
                                  {attachment.download_status === 'failed' && <XCircle className="w-3 h-3" />}
                                  {attachment.download_status}
                                </span>
                              </td>
                              <td className="px-4 py-3 text-xs text-gray-500 dark:text-gray-400">
                                {attachment.downloaded_at ? formatDateTime(attachment.downloaded_at) : '-'}
                              </td>
                              <td className="px-4 py-3 text-right">
                                <div className="flex items-center justify-end gap-1">
                                  {attachment.asset_id && (
                                    <>
                                      <button
                                        onClick={() => handleViewAsset(attachment.asset_id!)}
                                        className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
                                        title="View Asset"
                                      >
                                        <Eye className="w-4 h-4" />
                                      </button>
                                      <button
                                        onClick={() => handleDownloadAttachment(attachment)}
                                        className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
                                        title="Download File"
                                      >
                                        <Download className="w-4 h-4" />
                                      </button>
                                    </>
                                  )}
                                  {!attachment.asset_id && attachment.download_status === 'pending' && (
                                    <span className="text-xs text-gray-400 italic">Pending</span>
                                  )}
                                  {!attachment.asset_id && attachment.download_status === 'failed' && (
                                    <span className="text-xs text-red-400 italic">Failed</span>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Summaries Tab */}
            {activeTab === 'summaries' && (
              <div>
                {summaries.length === 0 ? (
                  <div className="text-center py-8">
                    <Sparkles className="w-10 h-10 mx-auto text-gray-300 dark:text-gray-600 mb-3" />
                    <p className="text-gray-500 dark:text-gray-400 mb-4">No summaries generated yet</p>
                    <p className="text-xs text-gray-400 dark:text-gray-500">
                      Summaries can be generated from extracted attachment content
                    </p>
                  </div>
                ) : (
                  <div className="space-y-6">
                    {summaries.map((summary) => (
                      <div
                        key={summary.id}
                        className={`border rounded-lg p-5 ${
                          summary.is_canonical
                            ? 'border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/10'
                            : 'border-gray-200 dark:border-gray-700'
                        }`}
                      >
                        <div className="flex items-start justify-between mb-4">
                          <div className="flex items-center gap-3">
                            {summary.is_canonical && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-amber-100 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 rounded">
                                <Star className="w-3 h-3" />
                                Canonical
                              </span>
                            )}
                            <span className="text-xs text-gray-500 dark:text-gray-400">
                              {summary.summary_type} summary
                            </span>
                          </div>
                          <div className="flex items-center gap-2 text-xs text-gray-400">
                            <span className="font-mono">{summary.model}</span>
                            {summary.confidence_score && (
                              <span className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 rounded">
                                {(summary.confidence_score * 100).toFixed(0)}% confidence
                              </span>
                            )}
                          </div>
                        </div>
                        <p className="text-sm text-gray-600 dark:text-gray-300 whitespace-pre-wrap mb-4">
                          {summary.summary}
                        </p>
                        {summary.key_requirements && summary.key_requirements.length > 0 && (
                          <div className="mb-4">
                            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">Key Requirements</p>
                            <ul className="list-disc list-inside text-sm text-gray-600 dark:text-gray-300 space-y-1">
                              {summary.key_requirements.slice(0, 5).map((req: any, idx: number) => (
                                <li key={idx}>{typeof req === 'string' ? req : req.requirement || req.description || JSON.stringify(req)}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        <div className="flex items-center justify-between text-xs text-gray-400">
                          <span>Generated {formatDateTime(summary.created_at)}</span>
                          {summary.token_count && <span>{summary.token_count.toLocaleString()} tokens</span>}
                        </div>
                      </div>
                    ))}
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

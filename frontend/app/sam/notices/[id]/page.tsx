'use client'

import { useState, useEffect, use, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { samApi, assetsApi, SamNotice, SamSolicitation, SamAttachment } from '@/lib/api'
import { formatDate as formatDateUtil, formatDateTime as formatDateTimeUtil } from '@/lib/date-utils'
import { Button } from '@/components/ui/Button'
import SamBreadcrumbs from '@/components/sam/SamBreadcrumbs'
import { NoticeTypeBadge, SamSummaryStatusBadge } from '@/components/sam/SamStatusBadge'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  FileText,
  RefreshCw,
  AlertTriangle,
  Calendar,
  Building2,
  ExternalLink,
  Clock,
  Paperclip,
  ChevronRight,
  Loader2,
  Sparkles,
  Download,
  Tag,
  Eye,
  CheckCircle,
  XCircle,
  Code,
  Hash,
} from 'lucide-react'

interface PageProps {
  params: Promise<{ id: string }>
}

export default function SamNoticeDetailPage({ params }: PageProps) {
  return (
    <ProtectedRoute>
      <SamNoticeDetailContent params={params} />
    </ProtectedRoute>
  )
}

function SamNoticeDetailContent({ params }: PageProps) {
  const resolvedParams = use(params)
  const noticeId = resolvedParams.id
  const router = useRouter()
  const { token } = useAuth()

  // State
  const [notice, setNotice] = useState<SamNotice | null>(null)
  const [solicitation, setSolicitation] = useState<SamSolicitation | null>(null)
  const [attachments, setAttachments] = useState<SamAttachment[]>([])
  const [fullDescription, setFullDescription] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isRegenerating, setIsRegenerating] = useState(false)
  const [isDownloadingAttachments, setIsDownloadingAttachments] = useState(false)
  const [activeTab, setActiveTab] = useState<'summary' | 'description' | 'attachments' | 'metadata'>('summary')

  // Load notice details
  const loadNotice = useCallback(async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const noticeData = await samApi.getNotice(token, noticeId, { includeMetadata: true })
      setNotice(noticeData)

      // Load full description
      try {
        const descData = await samApi.getNoticeDescription(token, noticeId)
        setFullDescription(descData.description)
      } catch (err) {
        // Full description endpoint may not exist, use truncated from notice
        setFullDescription(noticeData.description)
      }

      // Load attachments for this notice
      const attachmentsData = await samApi.getNoticeAttachments(token, noticeId)
      setAttachments(attachmentsData)

      // Load solicitation for context if not standalone
      if (noticeData.solicitation_id) {
        const solData = await samApi.getSolicitation(token, noticeData.solicitation_id)
        setSolicitation(solData)
      } else {
        setSolicitation(null)
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load notice')
    } finally {
      setIsLoading(false)
    }
  }, [token, noticeId])

  useEffect(() => {
    if (token) {
      loadNotice()
    }
  }, [token, loadNotice])

  // Poll while summary is generating
  useEffect(() => {
    if (notice?.summary_status === 'generating') {
      const interval = setInterval(() => loadNotice(), 3000)
      return () => clearInterval(interval)
    }
  }, [notice?.summary_status, loadNotice])

  // Handle refresh from SAM.gov
  const handleRefreshFromSam = async () => {
    if (!token) return

    setIsRefreshing(true)
    setError('')

    try {
      await samApi.refreshNotice(token, noticeId)
      await loadNotice()
    } catch (err: any) {
      setError(err.message || 'Failed to refresh from SAM.gov')
    } finally {
      setIsRefreshing(false)
    }
  }

  // Handle regenerate summary (works for all notices)
  const handleRegenerateSummary = async () => {
    if (!token) return

    setIsRegenerating(true)
    setError('')

    try {
      await samApi.regenerateNoticeSummary(token, noticeId)
      // Update local state to show generating status
      setNotice(prev => prev ? { ...prev, summary_status: 'generating' } : null)
    } catch (err: any) {
      setError(err.message || 'Failed to regenerate summary')
    } finally {
      setIsRegenerating(false)
    }
  }

  // Handle download all attachments
  const handleDownloadAttachments = async () => {
    if (!token) return

    setIsDownloadingAttachments(true)
    setError('')

    try {
      const result = await samApi.downloadNoticeAttachments(token, noticeId)
      // Reload attachments to show updated status
      await loadNotice()
      if (result.failed > 0) {
        setError(`Downloaded ${result.downloaded} of ${result.total} attachments. ${result.failed} failed.`)
      }
    } catch (err: any) {
      setError(err.message || 'Failed to download attachments')
    } finally {
      setIsDownloadingAttachments(false)
    }
  }

  // Use date utilities for consistent EST display
  const formatDate = (dateStr: string | null) => formatDateUtil(dateStr)
  const formatDateTime = (dateStr: string | null) => formatDateTimeUtil(dateStr)

  // Format file size
  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  // Get download status badge class
  const getDownloadStatusBadge = (status: string) => {
    switch (status) {
      case 'downloaded':
        return 'bg-emerald-100 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400'
      case 'downloading':
        return 'bg-blue-100 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400'
      case 'failed':
        return 'bg-red-100 dark:bg-red-900/20 text-red-700 dark:text-red-400'
      default:
        return 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
    }
  }

  // Handle view asset
  const handleViewAsset = (assetId: string) => {
    router.push(`/assets/${assetId}`)
  }

  // Handle download attachment file
  const handleDownloadFile = async (attachment: SamAttachment) => {
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
      setError(err.message || 'Failed to download file')
    }
  }

  // Render summary content for all notices
  const renderSummaryContent = () => {
    if (!notice) return null

    const status = notice.summary_status

    if (status === 'generating') {
      return (
        <div className="flex flex-col items-center justify-center py-8">
          <div className="w-10 h-10 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin mb-4" />
          <p className="text-sm text-gray-500 dark:text-gray-400">Generating AI summary...</p>
        </div>
      )
    }

    if (status === 'pending' || !status) {
      return (
        <div className="text-center py-8">
          <Sparkles className="w-10 h-10 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-2">Summary pending</p>
          <p className="text-xs text-gray-400 dark:text-gray-500 mb-4">
            A summary will be generated automatically or you can generate one now.
          </p>
          <Button
            variant="secondary"
            onClick={handleRegenerateSummary}
            disabled={isRegenerating}
            className="gap-2"
          >
            {isRegenerating ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Sparkles className="w-4 h-4" />
            )}
            Generate Summary
          </Button>
        </div>
      )
    }

    if (status === 'failed') {
      return (
        <div className="text-center py-8">
          <AlertTriangle className="w-10 h-10 text-red-400 mx-auto mb-4" />
          <p className="text-sm text-red-600 dark:text-red-400 mb-2">Summary generation failed</p>
          <p className="text-xs text-gray-400 dark:text-gray-500 mb-4">
            There was an error generating the AI summary. You can try again.
          </p>
          <Button
            variant="secondary"
            onClick={handleRegenerateSummary}
            disabled={isRegenerating}
            className="gap-2"
          >
            {isRegenerating ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            Retry
          </Button>
        </div>
      )
    }

    if (status === 'no_llm') {
      return (
        <div>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
              <AlertTriangle className="w-4 h-4" />
              <span className="text-sm">No LLM configured - showing original description</span>
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={handleRegenerateSummary}
              disabled={isRegenerating}
              className="gap-2"
            >
              {isRegenerating ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Sparkles className="w-4 h-4" />
              )}
              Generate Summary
            </Button>
          </div>
          {fullDescription ? (
            <div
              className="prose prose-sm dark:prose-invert max-w-none text-gray-700 dark:text-gray-300"
              dangerouslySetInnerHTML={{ __html: fullDescription }}
            />
          ) : (
            <p className="text-gray-500 dark:text-gray-400 italic">No description available.</p>
          )}
        </div>
      )
    }

    // status === 'ready'
    return (
      <div>
        {notice.summary_generated_at && (
          <p className="text-xs text-gray-400 dark:text-gray-500 mb-4">
            Summary generated {formatDateTime(notice.summary_generated_at)}
          </p>
        )}
        {fullDescription ? (
          <div
            className="prose prose-sm dark:prose-invert max-w-none text-gray-700 dark:text-gray-300"
            dangerouslySetInnerHTML={{ __html: fullDescription }}
          />
        ) : (
          <p className="text-gray-500 dark:text-gray-400 italic">No summary available.</p>
        )}
        {/* Link to parent solicitation summary if this is a solicitation-linked notice */}
        {!notice.is_standalone && solicitation && (
          <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-2">
              This notice is part of a solicitation. You can also view the solicitation-level summary.
            </p>
            <Link
              href={`/sam/solicitations/${solicitation.id}`}
              className="inline-flex items-center gap-2 text-indigo-600 dark:text-indigo-400 hover:underline text-sm"
            >
              View Solicitation Summary
              <ChevronRight className="w-4 h-4" />
            </Link>
          </div>
        )}
      </div>
    )
  }

  // Render tabs for description/attachments
  const renderTabs = () => {
    const tabs = [
      { id: 'summary', label: 'Summary', icon: Sparkles, count: null },
      { id: 'description', label: 'Description', icon: FileText, count: null },
      { id: 'attachments', label: 'Attachments', icon: Paperclip, count: attachments.length },
      { id: 'metadata', label: 'Metadata', icon: Code, count: null },
    ] as const

    return (
      <div className="border-b border-gray-200 dark:border-gray-700 mb-6">
        <nav className="-mb-px flex space-x-8">
          {tabs.map((tab) => {
            const Icon = tab.icon
            const isActive = activeTab === tab.id
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`
                  flex items-center gap-2 py-4 px-1 border-b-2 font-medium text-sm transition-colors
                  ${isActive
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
                  }
                `}
              >
                <Icon className="w-4 h-4" />
                {tab.label}
                {tab.count !== null && (
                  <span className={`ml-1 px-2 py-0.5 text-xs rounded-full ${
                    isActive
                      ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400'
                      : 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400'
                  }`}>
                    {tab.count}
                  </span>
                )}
              </button>
            )
          })}
        </nav>
      </div>
    )
  }

  // Render tab content
  const renderTabContent = () => {
    if (activeTab === 'summary') {
      return renderSummaryContent()
    }

    if (activeTab === 'description') {
      return (
        <div className="space-y-4">
          {fullDescription ? (
            <div
              className="prose prose-sm dark:prose-invert max-w-none text-gray-700 dark:text-gray-300"
              dangerouslySetInnerHTML={{ __html: fullDescription }}
            />
          ) : (
            <p className="text-gray-500 dark:text-gray-400 italic">No description available.</p>
          )}
          {notice?.description_url && (
            <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Full Description API</p>
              <a
                href={notice.description_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline break-all"
              >
                {notice.description_url}
              </a>
            </div>
          )}
        </div>
      )
    }

    if (activeTab === 'attachments') {
      if (attachments.length === 0) {
        return (
          <div className="text-center py-8">
            <Paperclip className="w-10 h-10 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <p className="text-sm text-gray-500 dark:text-gray-400">No attachments for this notice.</p>
          </div>
        )
      }

      return (
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
                              onClick={() => handleDownloadFile(attachment)}
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
      )
    }

    if (activeTab === 'metadata') {
      // Get metadata from notice or solicitation
      const metadata = notice?.raw_data || solicitation?.raw_data

      if (!metadata) {
        return (
          <div className="text-center py-8">
            <Code className="w-10 h-10 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <p className="text-sm text-gray-500 dark:text-gray-400">
              No metadata available. Run a refresh from SAM.gov to populate metadata.
            </p>
          </div>
        )
      }

      return (
        <div className="space-y-4">
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
            Raw SAM.gov API response data
          </p>
          <div className="bg-gray-50 dark:bg-gray-900 rounded-lg p-4 overflow-auto max-h-[600px]">
            <pre className="text-xs font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
              {JSON.stringify(metadata, null, 2)}
            </pre>
          </div>
        </div>
      )
    }

    return null
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Breadcrumbs */}
        <SamBreadcrumbs
          items={[
            { label: 'Notices', href: '/sam/notices' },
            { label: notice?.sam_notice_id || 'Notice' },
          ]}
        />

        {/* Error State */}
        {error && (
          <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
            <div className="flex items-center gap-3">
              <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
              <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
            </div>
          </div>
        )}

        {/* Loading State */}
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-blue-500 animate-spin" />
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading notice...</p>
          </div>
        ) : notice ? (
          <>
            {/* Header */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 mb-6">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-4 flex-1">
                  <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 text-white shadow-lg shadow-cyan-500/25">
                    <FileText className="w-6 h-6" />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <NoticeTypeBadge type={notice.notice_type} />
                      {notice.version_number > 1 && (
                        <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300">
                          Version {notice.version_number}
                        </span>
                      )}
                      {notice.is_standalone && (
                        <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300">
                          Standalone Notice
                        </span>
                      )}
                      {notice.summary_status && (
                        <SamSummaryStatusBadge status={notice.summary_status as 'pending' | 'generating' | 'ready' | 'failed' | 'no_llm'} />
                      )}
                    </div>
                    <h1 className="text-xl font-bold text-gray-900 dark:text-white mb-1">
                      {notice.title || 'Untitled Notice'}
                    </h1>
                    <p className="text-sm font-mono text-gray-500 dark:text-gray-400">
                      {notice.sam_notice_id}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    onClick={handleRefreshFromSam}
                    disabled={isRefreshing}
                    className="gap-2"
                  >
                    <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
                    Update from SAM
                  </Button>
                </div>
              </div>

              {/* Meta info grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 pt-6 border-t border-gray-100 dark:border-gray-700">
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Posted Date</p>
                  <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-1.5">
                    <Calendar className="w-4 h-4 text-gray-400" />
                    {formatDate(notice.posted_date)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Response Deadline</p>
                  <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-1.5">
                    <Clock className="w-4 h-4 text-gray-400" />
                    {formatDateTime(notice.response_deadline)}
                  </p>
                </div>
                {/* Agency - from notice or solicitation */}
                {(notice.agency_name || solicitation?.agency_name) && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Agency</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-1.5">
                      <Building2 className="w-4 h-4 text-gray-400" />
                      {notice.agency_name || solicitation?.agency_name}
                    </p>
                  </div>
                )}
                {/* NAICS Code - from notice or solicitation */}
                {(notice.naics_code || solicitation?.naics_code) && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">NAICS Code</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-1.5">
                      <Hash className="w-4 h-4 text-gray-400" />
                      {notice.naics_code || solicitation?.naics_code}
                    </p>
                  </div>
                )}
              </div>

              {/* Additional metadata row - Bureau, Office, PSC, Set-Aside */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
                {/* Bureau - from notice or solicitation */}
                {(notice.bureau_name || solicitation?.bureau_name) && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Bureau</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">
                      {notice.bureau_name || solicitation?.bureau_name}
                    </p>
                  </div>
                )}
                {/* Office - from notice or solicitation */}
                {(notice.office_name || solicitation?.office_name) && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Office</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">
                      {notice.office_name || solicitation?.office_name}
                    </p>
                  </div>
                )}
                {/* PSC Code - from notice or solicitation */}
                {(notice.psc_code || solicitation?.psc_code) && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">PSC Code</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-1.5">
                      <Tag className="w-4 h-4 text-gray-400" />
                      {notice.psc_code || solicitation?.psc_code}
                    </p>
                  </div>
                )}
                {/* Set-Aside - from notice or solicitation */}
                {(notice.set_aside_code || solicitation?.set_aside_code) && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Set-Aside</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">
                      {notice.set_aside_code || solicitation?.set_aside_code}
                    </p>
                  </div>
                )}
              </div>
            </div>

            {/* Parent Solicitation Link (for non-standalone notices) */}
            {!notice.is_standalone && solicitation && (
              <Link
                href={`/sam/solicitations/${solicitation.id}`}
                className="block mb-6 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 hover:border-indigo-300 dark:hover:border-indigo-600 transition-colors group"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center text-white">
                      <Building2 className="w-5 h-5" />
                    </div>
                    <div>
                      <p className="text-xs text-gray-500 dark:text-gray-400">Parent Solicitation</p>
                      <p className="font-medium text-gray-900 dark:text-white">
                        {solicitation.solicitation_number || solicitation.notice_id}
                      </p>
                    </div>
                  </div>
                  <ChevronRight className="w-5 h-5 text-gray-400 group-hover:text-indigo-500 transition-colors" />
                </div>
              </Link>
            )}

            {/* Changes Summary */}
            {notice.changes_summary && (
              <div className="bg-amber-50 dark:bg-amber-900/20 rounded-xl border border-amber-200 dark:border-amber-800/50 p-6 mb-6">
                <h2 className="text-lg font-semibold text-amber-900 dark:text-amber-200 mb-3">
                  Changes in This Version
                </h2>
                <p className="text-amber-800 dark:text-amber-300">
                  {notice.changes_summary}
                </p>
              </div>
            )}

            {/* Main Content - Tabbed Panel */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 mb-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Notice Details
                </h2>
                {activeTab === 'summary' && notice.summary_status === 'ready' && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handleRegenerateSummary}
                    disabled={isRegenerating}
                    className="gap-2"
                  >
                    {isRegenerating ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Sparkles className="w-4 h-4" />
                    )}
                    Regenerate Summary
                  </Button>
                )}
                {activeTab === 'attachments' && attachments.some(a => a.download_status === 'pending') && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handleDownloadAttachments}
                    disabled={isDownloadingAttachments}
                    className="gap-2"
                  >
                    {isDownloadingAttachments ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Download className="w-4 h-4" />
                    )}
                    Download All
                  </Button>
                )}
              </div>

              {renderTabs()}
              {renderTabContent()}
            </div>

            {/* SAM.gov Link */}
            {(notice.ui_link || solicitation?.ui_link) && (
              <div className="text-center">
                <a
                  href={notice.ui_link || solicitation?.ui_link || ''}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
                >
                  View on SAM.gov
                  <ExternalLink className="w-4 h-4" />
                </a>
              </div>
            )}
          </>
        ) : (
          <div className="text-center py-16">
            <FileText className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <p className="text-gray-500 dark:text-gray-400">Notice not found.</p>
          </div>
        )}
      </div>
    </div>
  )
}

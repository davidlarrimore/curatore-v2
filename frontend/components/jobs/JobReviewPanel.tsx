'use client'

import { useState, useEffect } from 'react'
import toast from 'react-hot-toast'
import { contentApi, jobsApi, processingApi, utils } from '@/lib/api'

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

interface JobReviewPanelProps {
  jobId: string
  documents: JobDocument[]
  onDocumentUpdate: (documentId: string) => void
  accessToken: string
}

type TabType = 'quality' | 'editor'
type FilterType = 'all' | 'completed' | 'failed' | 'rag_ready'

export function JobReviewPanel({
  jobId,
  documents,
  onDocumentUpdate,
  accessToken,
}: JobReviewPanelProps) {
  const [selectedDocument, setSelectedDocument] = useState<JobDocument | null>(null)
  const [activeTab, setActiveTab] = useState<TabType>('quality')
  const [documentContent, setDocumentContent] = useState<string>('')
  const [editedContent, setEditedContent] = useState<string>('')
  const [isEditing, setIsEditing] = useState<boolean>(false)
  const [filterStatus, setFilterStatus] = useState<FilterType>('all')
  const [reprocessingJobId, setReprocessingJobId] = useState<string | null>(null)
  const [processingLog, setProcessingLog] = useState<Array<{ timestamp?: string; level?: string; message?: string }>>([])
  const [logLoading, setLogLoading] = useState<boolean>(false)
  const [logError, setLogError] = useState<string>('')
  const [fullResult, setFullResult] = useState<any>(null)

  // Filter documents based on selected filter
  const filteredDocuments = documents.filter(doc => {
    if (filterStatus === 'all') return true
    if (filterStatus === 'completed') return doc.status === 'COMPLETED'
    if (filterStatus === 'failed') return doc.status === 'FAILED'
    if (filterStatus === 'rag_ready') return doc.is_rag_ready === true
    return true
  })

  // Calculate summary stats
  const stats = {
    total: documents.length,
    completed: documents.filter(d => d.status === 'COMPLETED').length,
    failed: documents.filter(d => d.status === 'FAILED').length,
    ragReady: documents.filter(d => d.is_rag_ready === true).length,
  }

  // Load document content when selected and on editor tab
  useEffect(() => {
    if (!selectedDocument || activeTab !== 'editor') return
    if (selectedDocument.status !== 'COMPLETED') {
      setDocumentContent('')
      setEditedContent('')
      return
    }
    loadDocumentContent(selectedDocument.document_id)
  }, [selectedDocument, activeTab])

  // Load processing log for failed documents
  useEffect(() => {
    setProcessingLog([])
    setLogError('')
    if (!selectedDocument || selectedDocument.status !== 'FAILED') return
    fetchProcessingLog(selectedDocument.document_id)
  }, [selectedDocument])

  // Load full processing result for quality scores (optional - fallback to job document data)
  useEffect(() => {
    if (!selectedDocument || selectedDocument.status !== 'COMPLETED') {
      setFullResult(null)
      return
    }

    // Try to load full result, but don't fail if it doesn't exist
    loadFullResult(selectedDocument.document_id)
  }, [selectedDocument])

  // Check if document is no longer in the list
  useEffect(() => {
    if (selectedDocument && !documents.find(d => d.document_id === selectedDocument.document_id)) {
      setSelectedDocument(null)
      toast.info('Document no longer available in this job')
    }
  }, [documents, selectedDocument])

  const loadDocumentContent = async (documentId: string) => {
    try {
      const result = await contentApi.getDocumentContent(documentId, accessToken)
      setDocumentContent(result.content)
      setEditedContent(result.content)
    } catch (error: any) {
      console.error('Failed to load document content:', error)

      // Handle 404 specifically - processed file not found
      if (error?.status === 404) {
        toast.error('Processed content not found. The document may not have been fully processed yet.')
        setDocumentContent('# Document Not Available\n\nThe processed content for this document is not available yet. The document may still be processing or the processing may have failed.')
      } else {
        toast.error('Failed to load document content')
        setDocumentContent('# Error Loading Content\n\nAn error occurred while loading the document content.')
      }
      setEditedContent('')
    }
  }

  const loadFullResult = async (documentId: string) => {
    try {
      const result = await processingApi.getProcessingResult(documentId)
      setFullResult(result)
    } catch (error) {
      // Not a critical error - we can fall back to job document data
      console.warn('Processing result not available, using job document data:', error)
      setFullResult(null)
    }
  }

  const fetchProcessingLog = async (documentId: string) => {
    setLogLoading(true)
    try {
      const jobData = await jobsApi.getJobByDocument(documentId, accessToken)
      if (jobData) {
        const logs = jobData?.logs || jobData?.log || jobData?.events || []
        const normalized = Array.isArray(logs)
          ? logs.map((l: any) => ({
              timestamp: l.timestamp || l.ts || l.time,
              level: l.level || l.severity || 'info',
              message: l.message || l.msg || String(l)
            }))
          : []
        setProcessingLog(normalized)
      }
    } catch (error) {
      console.error('Failed to load processing log:', error)
      setLogError('Failed to load processing log')
    } finally {
      setLogLoading(false)
    }
  }

  const handleSaveAndRescore = async () => {
    if (!selectedDocument || !editedContent) return

    setIsEditing(true)
    const loadingToast = toast.loading('Saving and re-scoring...')

    try {
      const response = await contentApi.updateDocumentContent(
        selectedDocument.document_id,
        editedContent,
        accessToken
      )

      setReprocessingJobId(response.job_id)
      toast.success('Queued for processing', { id: loadingToast })

      // Poll until complete
      const result = await pollJobUntilComplete(response.job_id)

      if (result.status === 'COMPLETED') {
        toast.success('Re-scoring complete!', { id: loadingToast })

        // Refresh document
        await loadFullResult(selectedDocument.document_id)

        // Notify parent to refresh job data
        onDocumentUpdate(selectedDocument.document_id)
      } else if (result.status === 'FAILED') {
        toast.error('Re-scoring failed', { id: loadingToast })
      } else if (result.status === 'CANCELLED') {
        toast.info('Re-scoring was cancelled', { id: loadingToast })
      }
    } catch (error: any) {
      if (error?.status === 409) {
        toast.error('Another operation is in progress. Please retry in a moment.', { id: loadingToast })
      } else {
        toast.error('Failed to save and re-score', { id: loadingToast })
      }
      console.error('Save and re-score error:', error)
    } finally {
      setIsEditing(false)
      setReprocessingJobId(null)
    }
  }

  const pollJobUntilComplete = async (jobId: string): Promise<any> => {
    const maxAttempts = 150 // 5 minutes at 2s intervals
    for (let i = 0; i < maxAttempts; i++) {
      const status = await jobsApi.getJob(accessToken, jobId)

      if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(status.status)) {
        return status
      }

      // Progress indicator every 30s
      if (i % 15 === 0 && i > 0) {
        toast.loading(`Processing... (${Math.floor(i * 2 / 60)}m elapsed)`, { id: 'polling' })
      }

      await new Promise(resolve => setTimeout(resolve, 2000))
    }

    toast.error('Processing timeout. Check job status manually.', { id: 'polling' })
    throw new Error('Polling timeout')
  }

  const formatTimestamp = (raw: any): string => {
    if (!raw) return ''
    try {
      let d: Date | null = null
      if (typeof raw === 'number') {
        d = new Date(raw > 1e12 ? raw : raw * 1000)
      } else if (typeof raw === 'string') {
        const trimmed = raw.trim()
        const num = Number(trimmed)
        if (!Number.isNaN(num) && trimmed.length >= 10 && trimmed.length <= 13) {
          d = new Date(num > 1e12 ? num : num * 1000)
        } else {
          const parsed = new Date(trimmed)
          if (!Number.isNaN(parsed.getTime())) d = parsed
        }
      }
      if (!d || Number.isNaN(d.getTime())) return String(raw)
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    } catch {
      return String(raw)
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'COMPLETED':
        return 'bg-green-100 text-green-800'
      case 'FAILED':
        return 'bg-red-100 text-red-800'
      case 'RUNNING':
        return 'bg-blue-100 text-blue-800'
      default:
        return 'bg-gray-100 text-gray-800'
    }
  }

  const getDocumentDisplayName = (doc: JobDocument): string => {
    const displayName = utils.getDisplayFilename(doc.filename)

    // If filename is just a hash (32 hex chars with no extension), use document_id as fallback
    if (/^[0-9a-f]{32}$/i.test(displayName)) {
      return `Document ${doc.document_id.substring(0, 8)}...`
    }

    return displayName
  }

  // Empty state when no completed documents
  if (stats.completed === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500 mb-4">No completed documents to review</p>
        <p className="text-sm text-gray-400">
          Completed: {stats.completed} | Failed: {stats.failed}
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Main Content */}
      <div className="flex gap-4 flex-1 overflow-hidden">
        {/* Document List */}
        <div className="w-1/3 bg-white rounded-lg border border-gray-200 flex flex-col">
          <div className="p-4 border-b border-gray-200">
            <h3 className="font-semibold text-gray-900 mb-3">Documents</h3>

            {/* Filter */}
            <div className="flex gap-2 text-xs">
              <button
                onClick={() => setFilterStatus('all')}
                className={`px-3 py-1 rounded ${
                  filterStatus === 'all' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700'
                }`}
              >
                All ({documents.length})
              </button>
              <button
                onClick={() => setFilterStatus('completed')}
                className={`px-3 py-1 rounded ${
                  filterStatus === 'completed' ? 'bg-green-600 text-white' : 'bg-gray-100 text-gray-700'
                }`}
              >
                Completed ({stats.completed})
              </button>
              <button
                onClick={() => setFilterStatus('failed')}
                className={`px-3 py-1 rounded ${
                  filterStatus === 'failed' ? 'bg-red-600 text-white' : 'bg-gray-100 text-gray-700'
                }`}
              >
                Failed ({stats.failed})
              </button>
              <button
                onClick={() => setFilterStatus('rag_ready')}
                className={`px-3 py-1 rounded ${
                  filterStatus === 'rag_ready' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700'
                }`}
              >
                RAG Ready ({stats.ragReady})
              </button>
            </div>
          </div>

          {/* Document List */}
          <div className="flex-1 overflow-y-auto">
            {filteredDocuments.length === 0 ? (
              <div className="p-4 text-center text-gray-500 text-sm">
                No documents match this filter
              </div>
            ) : (
              filteredDocuments.map((doc) => (
                <button
                  key={doc.id}
                  onClick={() => setSelectedDocument(doc)}
                  className={`w-full text-left p-3 border-b border-gray-100 hover:bg-gray-50 transition-colors ${
                    selectedDocument?.id === doc.id ? 'bg-blue-50 border-l-4 border-l-blue-600' : ''
                  }`}
                >
                  <div className="font-medium text-sm text-gray-900 truncate">{getDocumentDisplayName(doc)}</div>
                  <div className="flex items-center gap-2 mt-1">
                    <span className={`text-xs px-2 py-0.5 rounded ${getStatusColor(doc.status)}`}>
                      {doc.status}
                    </span>
                    {doc.conversion_score !== undefined && (
                      <span className={`text-xs ${doc.conversion_score >= 70 ? 'text-green-600' : 'text-yellow-600'}`}>
                        Score: {doc.conversion_score}
                      </span>
                    )}
                    {doc.is_rag_ready && (
                      <span className="text-xs text-blue-600">✓ RAG Ready</span>
                    )}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Review Details Panel */}
        <div className="flex-1 bg-white rounded-lg border border-gray-200 flex flex-col">
          {!selectedDocument ? (
            <div className="flex items-center justify-center h-full text-gray-500">
              Select a document to review
            </div>
          ) : (
            <>
              {/* Document Header */}
              <div className="p-4 border-b border-gray-200">
                <h3 className="font-semibold text-gray-900 truncate">{getDocumentDisplayName(selectedDocument)}</h3>
                <div className="flex items-center gap-2 mt-1">
                  <span className={`text-xs px-2 py-0.5 rounded ${getStatusColor(selectedDocument.status)}`}>
                    {selectedDocument.status}
                  </span>
                  {selectedDocument.conversion_score !== undefined && (
                    <span className="text-sm text-gray-600">
                      Score: {selectedDocument.conversion_score}/100
                    </span>
                  )}
                </div>
              </div>

              {/* Tabs */}
              <div className="border-b border-gray-200">
                <nav className="flex -mb-px">
                  <button
                    onClick={() => setActiveTab('quality')}
                    className={`px-6 py-3 text-sm font-medium ${
                      activeTab === 'quality'
                        ? 'border-b-2 border-blue-500 text-blue-600'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                  >
                    Quality Scores
                  </button>
                  <button
                    onClick={() => setActiveTab('editor')}
                    className={`px-6 py-3 text-sm font-medium ${
                      activeTab === 'editor'
                        ? 'border-b-2 border-blue-500 text-blue-600'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                    disabled={selectedDocument.status !== 'COMPLETED'}
                  >
                    Live Editor
                  </button>
                </nav>
              </div>

              {/* Tab Content */}
              <div className="flex-1 overflow-y-auto p-4">
                {activeTab === 'quality' && (
                  <div className="space-y-4">
                    {selectedDocument.status === 'FAILED' ? (
                      <div>
                        <div className="bg-red-50 border border-red-200 rounded p-4 mb-4">
                          <h4 className="font-semibold text-red-800 mb-2">Processing Failed</h4>
                          {selectedDocument.error_message && (
                            <p className="text-sm text-red-700">{selectedDocument.error_message}</p>
                          )}
                        </div>

                        {/* Processing Log */}
                        {logLoading ? (
                          <div className="text-center text-gray-500">Loading logs...</div>
                        ) : logError ? (
                          <div className="text-center text-red-600">{logError}</div>
                        ) : processingLog.length > 0 ? (
                          <div>
                            <h4 className="font-semibold text-gray-900 mb-2">Processing Log</h4>
                            <div className="space-y-2">
                              {processingLog.map((log, idx) => (
                                <div
                                  key={idx}
                                  className={`p-2 rounded text-xs font-mono ${
                                    log.level === 'ERROR'
                                      ? 'bg-red-50 text-red-800'
                                      : log.level === 'WARNING'
                                      ? 'bg-yellow-50 text-yellow-800'
                                      : 'bg-gray-50 text-gray-800'
                                  }`}
                                >
                                  <span className="text-gray-500">{formatTimestamp(log.timestamp)}</span>
                                  <span className="ml-2 font-semibold">[{log.level}]</span>
                                  <span className="ml-2">{log.message}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}
                      </div>
                    ) : (
                      <div className="space-y-4">
                        {/* Conversion Score */}
                        <div>
                          <h4 className="font-semibold text-gray-900 mb-2">Conversion Quality</h4>
                          <div className="bg-gray-50 p-3 rounded">
                            <div className="flex items-center justify-between">
                              <span className="text-gray-700">Conversion Score</span>
                              <span className={`text-2xl font-bold ${
                                (selectedDocument.conversion_score ?? 0) >= 70 ? 'text-green-600' : 'text-yellow-600'
                              }`}>
                                {selectedDocument.conversion_score ?? 0}/100
                              </span>
                            </div>
                          </div>
                        </div>

                        {/* LLM Evaluation - use fullResult if available, otherwise use quality_scores from job document */}
                        {(fullResult?.llm_evaluation || selectedDocument.quality_scores) && (
                          <div>
                            <h4 className="font-semibold text-gray-900 mb-2">LLM Evaluation</h4>
                            <div className="space-y-2">
                              {(() => {
                                const evaluation = fullResult?.llm_evaluation || selectedDocument.quality_scores || {}
                                return (
                                  <>
                                    {evaluation.clarity !== undefined && (
                                      <div className="flex items-center justify-between bg-gray-50 p-2 rounded">
                                        <span className="text-gray-700">Clarity</span>
                                        <span className={`font-semibold ${
                                          evaluation.clarity >= 7 ? 'text-green-600' : 'text-yellow-600'
                                        }`}>
                                          {evaluation.clarity}/10
                                        </span>
                                      </div>
                                    )}
                                    {evaluation.completeness !== undefined && (
                                      <div className="flex items-center justify-between bg-gray-50 p-2 rounded">
                                        <span className="text-gray-700">Completeness</span>
                                        <span className={`font-semibold ${
                                          evaluation.completeness >= 7 ? 'text-green-600' : 'text-yellow-600'
                                        }`}>
                                          {evaluation.completeness}/10
                                        </span>
                                      </div>
                                    )}
                                    {evaluation.relevance !== undefined && (
                                      <div className="flex items-center justify-between bg-gray-50 p-2 rounded">
                                        <span className="text-gray-700">Relevance</span>
                                        <span className={`font-semibold ${
                                          evaluation.relevance >= 7 ? 'text-green-600' : 'text-yellow-600'
                                        }`}>
                                          {evaluation.relevance}/10
                                        </span>
                                      </div>
                                    )}
                                    {evaluation.markdown_quality !== undefined && (
                                      <div className="flex items-center justify-between bg-gray-50 p-2 rounded">
                                        <span className="text-gray-700">Markdown Quality</span>
                                        <span className={`font-semibold ${
                                          evaluation.markdown_quality >= 7 ? 'text-green-600' : 'text-yellow-600'
                                        }`}>
                                          {evaluation.markdown_quality}/10
                                        </span>
                                      </div>
                                    )}
                                  </>
                                )
                              })()}
                            </div>
                          </div>
                        )}

                        {/* LLM Recommendations */}
                        {fullResult?.llm_evaluation?.recommendations && (
                          <div>
                            <h4 className="font-semibold text-gray-900 mb-2">Recommendations</h4>
                            <div className="bg-blue-50 border border-blue-200 rounded p-3">
                              <p className="text-sm text-gray-700 whitespace-pre-wrap">
                                {fullResult.llm_evaluation.recommendations}
                              </p>
                            </div>
                          </div>
                        )}

                        {/* Document Summary */}
                        {fullResult?.document_summary && (
                          <div>
                            <h4 className="font-semibold text-gray-900 mb-2">Document Summary</h4>
                            <div className="bg-gray-50 border border-gray-200 rounded p-3">
                              <p className="text-sm text-gray-700 whitespace-pre-wrap">
                                {fullResult.document_summary}
                              </p>
                            </div>
                          </div>
                        )}

                        {/* RAG Ready Status */}
                        <div>
                          <h4 className="font-semibold text-gray-900 mb-2">RAG Ready Status</h4>
                          <div className={`p-3 rounded ${
                            selectedDocument.is_rag_ready ? 'bg-green-50 border border-green-200' : 'bg-yellow-50 border border-yellow-200'
                          }`}>
                            <div className="flex items-center justify-between">
                              <span className="text-gray-700">Ready for RAG</span>
                              <span className={`text-lg font-semibold ${
                                selectedDocument.is_rag_ready ? 'text-green-600' : 'text-yellow-600'
                              }`}>
                                {selectedDocument.is_rag_ready ? '✓ Yes' : '✗ No'}
                              </span>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {activeTab === 'editor' && (
                  <div className="h-full flex flex-col">
                    {selectedDocument.status !== 'COMPLETED' ? (
                      <div className="text-center text-gray-500 py-8">
                        Editor is only available for completed documents
                      </div>
                    ) : !documentContent && !editedContent ? (
                      <div className="text-center text-gray-500 py-8">
                        <p className="mb-2">Unable to load document content</p>
                        <p className="text-sm">The processed markdown file may not be available yet.</p>
                      </div>
                    ) : (
                      <>
                        <div className="mb-2 flex items-center justify-between">
                          <h4 className="font-semibold text-gray-900">Edit Markdown Content</h4>
                          {isEditing && (
                            <span className="text-sm text-blue-600 animate-pulse">Processing...</span>
                          )}
                        </div>
                        <textarea
                          value={editedContent}
                          onChange={(e) => setEditedContent(e.target.value)}
                          disabled={isEditing || documentContent.startsWith('# Document Not Available') || documentContent.startsWith('# Error Loading')}
                          className="flex-1 w-full p-3 border border-gray-300 rounded font-mono text-sm resize-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-50 disabled:cursor-not-allowed"
                          placeholder="Loading document content..."
                        />
                        <div className="mt-3 flex items-center justify-between">
                          <button
                            onClick={() => setEditedContent(documentContent)}
                            disabled={isEditing || editedContent === documentContent || documentContent.startsWith('# Document Not Available') || documentContent.startsWith('# Error Loading')}
                            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 disabled:text-gray-400 disabled:cursor-not-allowed"
                          >
                            Reset Changes
                          </button>
                          <button
                            onClick={handleSaveAndRescore}
                            disabled={isEditing || editedContent === documentContent || !editedContent || documentContent.startsWith('# Document Not Available') || documentContent.startsWith('# Error Loading')}
                            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                          >
                            {isEditing ? 'Saving...' : 'Save & Re-Score'}
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

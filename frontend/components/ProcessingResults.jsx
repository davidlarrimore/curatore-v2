// frontend/components/ProcessingResults.jsx
'use client'

import { useState } from 'react'

export function ProcessingResults({ documents, onDelete, onRefresh, apiUrl, isLoading }) {
  const [selectedDoc, setSelectedDoc] = useState(null)
  const [showContent, setShowContent] = useState({})

  const getStatusBadge = (doc) => {
    if (doc.status === 'completed' && doc.success) {
      return doc.pass_all_thresholds 
        ? 'bg-green-100 text-green-800' 
        : 'bg-yellow-100 text-yellow-800'
    }
    return 'bg-red-100 text-red-800'
  }

  const getStatusText = (doc) => {
    if (doc.status === 'completed' && doc.success) {
      return doc.pass_all_thresholds ? '✅ RAG Ready' : '⚠️ Needs Work'
    }
    return '❌ Failed'
  }

  const downloadDocument = async (documentId, filename) => {
    try {
      const response = await fetch(`${apiUrl}/api/v1/documents/${documentId}/download`)
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error('Download failed:', error)
    }
  }

  const toggleContent = async (documentId) => {
    if (showContent[documentId]) {
      setShowContent(prev => ({ ...prev, [documentId]: null }))
      return
    }

    try {
      const response = await fetch(`${apiUrl}/api/v1/documents/${documentId}/content`)
      if (response.ok) {
        const data = await response.json()
        setShowContent(prev => ({ ...prev, [documentId]: data.content }))
      }
    } catch (error) {
      console.error('Failed to load content:', error)
    }
  }

  const formatProcessingTime = (seconds) => {
    if (!seconds) return 'N/A'
    return seconds < 1 ? '<1s' : `${seconds.toFixed(1)}s`
  }

  if (documents.length === 0) {
    return (
      <div className="bg-white rounded-2xl border shadow-sm p-8 text-center">
        <div className="text-6xl mb-4">📄</div>
        <h3 className="text-xl font-medium text-gray-700 mb-2">No Documents Processed Yet</h3>
        <p className="text-gray-500">Upload some documents to get started with RAG optimization</p>
      </div>
    )
  }

  const successfulDocs = documents.filter(doc => doc.success)
  const ragReadyDocs = successfulDocs.filter(doc => doc.pass_all_thresholds)
  const vectorOptimizedDocs = successfulDocs.filter(doc => doc.vector_optimized)

  return (
    <div className="bg-white rounded-2xl border shadow-sm p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-semibold">📊 Processing Results</h2>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="px-4 py-2 text-blue-600 hover:text-blue-800 disabled:opacity-50"
        >
          🔄 Refresh
        </button>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-blue-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-blue-600">{documents.length}</div>
          <div className="text-sm text-blue-800">Total</div>
        </div>
        <div className="bg-green-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-green-600">{ragReadyDocs.length}</div>
          <div className="text-sm text-green-800">RAG Ready</div>
        </div>
        <div className="bg-purple-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-purple-600">{vectorOptimizedDocs.length}</div>
          <div className="text-sm text-purple-800">Optimized</div>
        </div>
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-gray-600">{successfulDocs.length}</div>
          <div className="text-sm text-gray-800">Successful</div>
        </div>
      </div>

      {/* Document List */}
      <div className="space-y-4">
        {documents.map((doc) => (
          <div key={doc.document_id} className="border rounded-lg p-4">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <div className="flex items-center space-x-3">
                  <span className="text-2xl">📄</span>
                  <div>
                    <h3 className="font-medium text-gray-900">{doc.filename}</h3>
                    <div className="flex items-center space-x-4 text-sm text-gray-500 mt-1">
                      <span>⏱️ {formatProcessingTime(doc.processing_time)}</span>
                      {doc.conversion_score !== undefined && (
                        <span>📊 {doc.conversion_score}/100</span>
                      )}
                      {doc.vector_optimized && <span>🎯 Optimized</span>}
                    </div>
                  </div>
                </div>
              </div>
              
              <div className="flex items-center space-x-3">
                <span className={`px-3 py-1 rounded-full text-sm font-medium ${getStatusBadge(doc)}`}>
                  {getStatusText(doc)}
                </span>
              </div>
            </div>

            {/* Document Summary */}
            {doc.document_summary && (
              <div className="mt-3 p-3 bg-gray-50 rounded text-sm text-gray-700">
                <strong>Summary:</strong> {doc.document_summary}
              </div>
            )}

            {/* Quality Scores */}
            {doc.llm_evaluation && (
              <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <div className="text-center">
                  <div className="font-medium">Clarity</div>
                  <div className="text-blue-600">{doc.llm_evaluation.clarity_score || 'N/A'}/10</div>
                </div>
                <div className="text-center">
                  <div className="font-medium">Complete</div>
                  <div className="text-green-600">{doc.llm_evaluation.completeness_score || 'N/A'}/10</div>
                </div>
                <div className="text-center">
                  <div className="font-medium">Relevant</div>
                  <div className="text-purple-600">{doc.llm_evaluation.relevance_score || 'N/A'}/10</div>
                </div>
                <div className="text-center">
                  <div className="font-medium">Markdown</div>
                  <div className="text-orange-600">{doc.llm_evaluation.markdown_score || 'N/A'}/10</div>
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="mt-4 flex items-center justify-between">
              <div className="flex space-x-2">
                <button
                  type="button"
                  onClick={() => toggleContent(doc.document_id)}
                  className="px-3 py-1 text-sm bg-blue-50 text-blue-700 rounded hover:bg-blue-100"
                >
                  {showContent[doc.document_id] ? '📖 Hide Content' : '👁️ View Content'}
                </button>
                {doc.success && (
                  <button
                    type="button"
                    onClick={() => downloadDocument(doc.document_id, `${doc.filename.split('.')[0]}.md`)}
                    className="px-3 py-1 text-sm bg-green-50 text-green-700 rounded hover:bg-green-100"
                  >
                    💾 Download
                  </button>
                )}
              </div>
              
              <button
                type="button"
                onClick={() => onDelete(doc.document_id)}
                className="px-3 py-1 text-sm bg-red-50 text-red-700 rounded hover:bg-red-100"
              >
                🗑️ Delete
              </button>
            </div>

            {/* Content Preview */}
            {showContent[doc.document_id] && (
              <div className="mt-4 border-t pt-4">
                <h4 className="font-medium mb-2">📝 Processed Content</h4>
                <div className="bg-gray-50 p-4 rounded max-h-96 overflow-y-auto">
                  <pre className="text-sm text-gray-700 whitespace-pre-wrap font-mono">
                    {showContent[doc.document_id]}
                  </pre>
                </div>
              </div>
            )}

            {/* Error Message */}
            {!doc.success && doc.message && (
              <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded text-red-800 text-sm">
                <strong>Error:</strong> {doc.message}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

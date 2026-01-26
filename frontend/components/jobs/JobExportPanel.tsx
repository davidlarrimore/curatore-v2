'use client'

import { useState } from 'react'
import toast from 'react-hot-toast'
import { fileApi, utils } from '@/lib/api'
import { Download } from 'lucide-react'

interface JobDocument {
  id: string
  document_id: string
  filename: string
  status: string
  conversion_score?: number
  quality_scores?: Record<string, any>
  error_message?: string
  processing_time_seconds?: number
}

interface JobExportPanelProps {
  jobId: string
  documents: JobDocument[]
  accessToken: string
}

export function JobExportPanel({
  jobId,
  documents,
  accessToken,
}: JobExportPanelProps) {
  const [selectedDocIds, setSelectedDocIds] = useState<Set<string>>(new Set())
  const [exportType, setExportType] = useState<'individual' | 'combined'>('individual')
  const [includeSummary, setIncludeSummary] = useState<boolean>(true)
  const [isExporting, setIsExporting] = useState<boolean>(false)
  const [downloadingId, setDownloadingId] = useState<string>('')

  // Filter to completed documents only
  const completedDocuments = documents.filter(d => d.status === 'COMPLETED')

  // Calculate stats
  const stats = {
    total: completedDocuments.length,
    selected: selectedDocIds.size,
  }

  const handleToggleDocument = (documentId: string) => {
    const updated = new Set(selectedDocIds)
    if (updated.has(documentId)) {
      updated.delete(documentId)
    } else {
      updated.add(documentId)
    }
    setSelectedDocIds(updated)
  }

  const handleSelectAll = () => {
    setSelectedDocIds(new Set(completedDocuments.map(d => d.document_id)))
  }

  const handleClearAll = () => {
    setSelectedDocIds(new Set())
  }

  const downloadIndividualFile = async (document: JobDocument) => {
    setDownloadingId(document.document_id)
    try {
      // Pass jobId to ensure we download the correct processed file for this job
      const blob = await fileApi.downloadDocument(document.document_id, 'processed', jobId)
      const displayName = utils.getDisplayFilename(document.filename)
      const filename = `${displayName.split('.')[0]}.md`
      utils.downloadBlob(blob, filename)
      toast.success(`Downloaded ${displayName}`)
    } catch (error: any) {
      console.error('Download failed:', error)

      // Handle 404 specifically - file not found
      if (error?.status === 404) {
        toast.error('Processed file not found. The document may not have been fully processed yet.')
      } else {
        const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred'
        toast.error(`Failed to download: ${errorMessage}`)
      }
    } finally {
      setDownloadingId('')
    }
  }

  const handleExportSelected = async () => {
    if (selectedDocIds.size === 0) {
      toast.error('Please select documents to export')
      return
    }

    setIsExporting(true)
    const loadingToast = toast.loading(`Creating ZIP archive with ${selectedDocIds.size} files...`)

    try {
      const selectedArray = Array.from(selectedDocIds)
      const timestamp = utils.generateTimestamp()
      const zipName = `job_${jobId}_export_${timestamp}.zip`

      const blob = await fileApi.downloadBulkDocuments(
        selectedArray,
        exportType,
        zipName,
        includeSummary
      )

      utils.downloadBlob(blob, zipName)
      toast.success(`Exported ${selectedDocIds.size} documents`, { id: loadingToast })
    } catch (error: any) {
      console.error('Export failed:', error)

      if (error?.status === 404) {
        toast.error('Some processed files not found. Documents may not be fully processed yet.', { id: loadingToast })
      } else {
        const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred'
        toast.error(`Export failed: ${errorMessage}`, { id: loadingToast })
      }
    } finally {
      setIsExporting(false)
    }
  }

  const handleExportAll = async () => {
    if (completedDocuments.length === 0) {
      toast.error('No completed documents to export')
      return
    }

    setIsExporting(true)
    const loadingToast = toast.loading(`Creating ZIP archive with ${completedDocuments.length} files...`)

    try {
      const allDocIds = completedDocuments.map(d => d.document_id)
      const timestamp = utils.generateTimestamp()
      const zipName = `job_${jobId}_all_${timestamp}.zip`

      const blob = await fileApi.downloadBulkDocuments(
        allDocIds,
        exportType,
        zipName,
        includeSummary
      )

      utils.downloadBlob(blob, zipName)
      toast.success(`Exported ${completedDocuments.length} documents`, { id: loadingToast })
    } catch (error: any) {
      console.error('Export failed:', error)

      if (error?.status === 404) {
        toast.error('Some processed files not found. Documents may not be fully processed yet.', { id: loadingToast })
      } else {
        const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred'
        toast.error(`Export failed: ${errorMessage}`, { id: loadingToast })
      }
    } finally {
      setIsExporting(false)
    }
  }

  const getScoreColor = (score?: number) => {
    if (score === undefined) return 'text-gray-400'
    if (score >= 70) return 'text-green-600'
    if (score >= 50) return 'text-yellow-600'
    return 'text-red-600'
  }

  // Empty state when no completed documents
  if (completedDocuments.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500 mb-4">No completed documents to export</p>
        <p className="text-sm text-gray-400">
          Complete document processing before exporting
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Selection Controls */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex gap-2">
          <button
            onClick={handleSelectAll}
            className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 rounded transition-colors"
          >
            Select All
          </button>
          <button
            onClick={handleClearAll}
            className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 rounded transition-colors"
            disabled={selectedDocIds.size === 0}
          >
            Clear All
          </button>
        </div>
      </div>

      {/* Document Table */}
      <div className="flex-1 bg-white rounded-lg border border-gray-200 overflow-hidden flex flex-col">
        <div className="overflow-x-auto flex-1">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-12">
                  Select
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Filename
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-24">
                  Score
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-24">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {completedDocuments.map((doc) => (
                <tr key={doc.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 whitespace-nowrap">
                    <input
                      type="checkbox"
                      checked={selectedDocIds.has(doc.document_id)}
                      onChange={() => handleToggleDocument(doc.document_id)}
                      className="h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-sm font-medium text-gray-900 truncate max-w-md">
                      {utils.getDisplayFilename(doc.filename)}
                    </div>
                    <div className="text-xs text-gray-500">{doc.document_id}</div>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span className={`text-sm font-semibold ${getScoreColor(doc.conversion_score)}`}>
                      {doc.conversion_score !== undefined ? `${doc.conversion_score}` : '-'}
                    </span>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <button
                      onClick={() => downloadIndividualFile(doc)}
                      disabled={downloadingId === doc.document_id}
                      className="text-blue-600 hover:text-blue-800 disabled:text-gray-400 disabled:cursor-not-allowed"
                      title="Download individual file"
                    >
                      {downloadingId === doc.document_id ? (
                        <span className="animate-spin">⏳</span>
                      ) : (
                        <Download className="h-4 w-4" />
                      )}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Export Options */}
      <div className="mt-4 bg-white border border-gray-200 rounded-lg p-4">
        <h4 className="font-semibold text-gray-900 mb-3">Export Options</h4>

        {/* Export Type */}
        <div className="mb-4">
          <label className="text-sm text-gray-700 mb-2 block">Export Type</label>
          <div className="flex gap-4">
            <label className="flex items-center">
              <input
                type="radio"
                value="individual"
                checked={exportType === 'individual'}
                onChange={(e) => setExportType(e.target.value as 'individual')}
                className="h-4 w-4 text-blue-600 border-gray-300 focus:ring-blue-500"
              />
              <span className="ml-2 text-sm text-gray-700">Individual Files</span>
            </label>
            <label className="flex items-center">
              <input
                type="radio"
                value="combined"
                checked={exportType === 'combined'}
                onChange={(e) => setExportType(e.target.value as 'combined')}
                className="h-4 w-4 text-blue-600 border-gray-300 focus:ring-blue-500"
              />
              <span className="ml-2 text-sm text-gray-700">Combined Archive</span>
            </label>
          </div>
        </div>

        {/* Include Summary */}
        <div className="mb-4">
          <label className="flex items-center">
            <input
              type="checkbox"
              checked={includeSummary}
              onChange={(e) => setIncludeSummary(e.target.checked)}
              className="h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
            />
            <span className="ml-2 text-sm text-gray-700">Include Summary Report</span>
          </label>
        </div>

        {/* Export Buttons */}
        <div className="flex gap-2">
          <button
            onClick={handleExportSelected}
            disabled={isExporting || selectedDocIds.size === 0}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {isExporting ? 'Exporting...' : `Export Selected (${selectedDocIds.size})`}
          </button>
          <button
            onClick={handleExportAll}
            disabled={isExporting}
            className="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            Export All ({completedDocuments.length})
          </button>
        </div>
      </div>
    </div>
  )
}

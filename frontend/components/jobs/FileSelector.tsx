'use client'

import { useMemo, useState, useEffect } from 'react'
import { FileInfo } from '@/types'
import StorageBrowser from './StorageBrowser'
import toast from 'react-hot-toast'
import { objectStorageApi } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'

/**
 * Selected file from storage browser.
 * Maps to the StorageBrowser's internal SelectedFile type.
 */
interface SelectedStorageFile {
  key: string
  filename: string
  bucket: string
  size: number
}

interface FileSelectorProps {
  /**
   * Currently selected files.
   * The FileSelector translates between StorageBrowser's format and FileInfo.
   */
  selectedFiles: FileInfo[]

  /**
   * Callback when selection changes.
   */
  onSelectedFilesChange: (files: FileInfo[]) => void

  /**
   * Maximum number of files that can be selected.
   * If not provided, unlimited files can be selected.
   */
  maxSelections?: number
}

/**
 * FileSelector - Storage-based file selection for job creation.
 *
 * This component wraps the StorageBrowser to provide file selection from
 * object storage. Files must be uploaded to storage first via the Storage page.
 *
 * Key changes from previous version:
 * - No longer supports direct upload (removed upload area, drag-drop)
 * - Browses files from object storage instead of legacy filesystem
 * - Supports folder navigation with bucket/prefix structure
 *
 * @example
 * ```tsx
 * <FileSelector
 *   selectedFiles={selectedFiles}
 *   onSelectedFilesChange={setSelectedFiles}
 *   maxSelections={100}
 * />
 * ```
 */
export function FileSelector({
  selectedFiles,
  onSelectedFilesChange,
  maxSelections,
}: FileSelectorProps) {
  const { token } = useAuth()
  const [artifactMap, setArtifactMap] = useState<Map<string, string>>(new Map())
  const [isLoadingArtifacts, setIsLoadingArtifacts] = useState(true)

  // Load artifacts on mount to build object_key -> document_id mapping
  useEffect(() => {
    async function loadArtifacts() {
      try {
        setIsLoadingArtifacts(true)
        const artifacts = await objectStorageApi.listArtifacts('uploaded', 1000, 0, token || undefined)
        const map = new Map<string, string>()
        artifacts.forEach(artifact => {
          map.set(artifact.object_key, artifact.document_id)
        })
        setArtifactMap(map)
      } catch (error) {
        console.error('Failed to load artifacts:', error)
        toast.error('Failed to load file information')
      } finally {
        setIsLoadingArtifacts(false)
      }
    }
    loadArtifacts()
  }, [token])

  // Convert FileInfo[] to StorageBrowser's internal format
  const storageSelectedFiles: SelectedStorageFile[] = useMemo(() => {
    return selectedFiles.map(file => ({
      key: file.file_path || file.document_id,
      filename: file.filename,
      bucket: 'curatore-uploads', // Default bucket, may vary
      size: file.file_size,
    }))
  }, [selectedFiles])

  // Handle selection changes from StorageBrowser
  const handleSelectionChange = (files: SelectedStorageFile[]) => {
    // Convert StorageBrowser format to FileInfo
    const allFileInfos = files.map(file => ({
      document_id: artifactMap.get(file.key) || extractDocumentId(file.key),
      filename: file.filename,
      original_filename: file.filename,
      file_size: file.size,
      upload_time: Date.now(),
      file_path: file.key,
    }))

    // Filter out files without valid document_ids
    const fileInfos = allFileInfos.filter(info => info.document_id !== '')

    // Warn if any files were filtered out
    const filteredCount = allFileInfos.length - fileInfos.length
    if (filteredCount > 0) {
      toast.error(
        `${filteredCount} file(s) skipped: Not uploaded through Curatore. Only uploaded files can be processed.`,
        { duration: 5000 }
      )
    }

    onSelectedFilesChange(fileInfos)
  }

  // Show loading state while artifacts are loading
  if (isLoadingArtifacts) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="text-center">
          <div className="w-8 h-8 border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 rounded-full animate-spin mx-auto mb-2"></div>
          <p className="text-sm text-gray-500 dark:text-gray-400">Loading files...</p>
        </div>
      </div>
    )
  }

  return (
    <StorageBrowser
      selectedFiles={storageSelectedFiles}
      onSelectionChange={handleSelectionChange}
      maxSelections={maxSelections}
    />
  )
}

/**
 * Extract document ID from storage key.
 *
 * Storage keys follow the pattern: {org_id}/{document_id}/uploaded/{filename}
 * This extracts the document_id portion.
 */
function extractDocumentId(key: string): string {
  const parts = key.split('/')
  // Key format: org_id/document_id/uploaded/filename
  if (parts.length >= 4 && parts[2] === 'uploaded') {
    const documentId = parts[1]
    // Validate it's not a file path (must be UUID or doc_* format)
    if (documentId && !documentId.includes('.') && (
      documentId.startsWith('doc_') ||
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(documentId)
    )) {
      return documentId
    }
  }
  // If we can't extract a valid document_id, return empty string
  // This will cause the file to be filtered out
  return ''
}

export default FileSelector

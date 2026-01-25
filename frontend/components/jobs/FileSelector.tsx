'use client'

import { useMemo } from 'react'
import { FileInfo } from '@/types'
import StorageBrowser from './StorageBrowser'

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
    const fileInfos: FileInfo[] = files.map(file => ({
      document_id: extractDocumentId(file.key),
      filename: file.filename,
      original_filename: file.filename,
      file_size: file.size,
      upload_time: Date.now(),
      file_path: file.key,
    }))

    onSelectedFilesChange(fileInfos)
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
  if (parts.length >= 3) {
    return parts[1] // document_id is the second part
  }
  // Fallback: use the key as-is
  return key
}

export default FileSelector

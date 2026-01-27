'use client'

import React, { useState, useEffect, useCallback } from 'react'
import {
  Folder,
  FileText,
  ChevronUp,
  Loader2,
  AlertCircle,
  HardDrive,
  ChevronDown,
  ExternalLink,
} from 'lucide-react'
import { objectStorageApi } from '@/lib/api'
import { utils } from '@/lib/api'
import FolderBreadcrumb from './FolderBreadcrumb'

interface StorageFile {
  key: string
  filename: string
  size: number
  content_type: string | null
  etag: string
  last_modified: string
  is_folder: boolean
}

interface Bucket {
  name: string
  display_name: string
  is_protected: boolean
  is_default: boolean
}

interface SelectedFile {
  key: string
  filename: string
  bucket: string
  size: number
}

interface StorageBrowserProps {
  selectedFiles: SelectedFile[]
  onSelectionChange: (files: SelectedFile[]) => void
  maxSelections?: number
}

export default function StorageBrowser({
  selectedFiles,
  onSelectionChange,
  maxSelections,
}: StorageBrowserProps) {
  // State
  const [buckets, setBuckets] = useState<Bucket[]>([])
  const [currentBucket, setCurrentBucket] = useState<string>('')
  const [currentPrefix, setCurrentPrefix] = useState<string>('')
  const [folders, setFolders] = useState<string[]>([])
  const [files, setFiles] = useState<StorageFile[]>([])
  const [isProtected, setIsProtected] = useState<boolean>(false)
  const [parentPath, setParentPath] = useState<string | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [bucketDropdownOpen, setBucketDropdownOpen] = useState<boolean>(false)
  const [selectingFolder, setSelectingFolder] = useState<string | null>(null)

  // Get current bucket display name
  const currentBucketDisplay = buckets.find(b => b.name === currentBucket)?.display_name || currentBucket

  // Load buckets on mount
  useEffect(() => {
    loadBuckets()
  }, [])

  // Load bucket contents when bucket or prefix changes
  useEffect(() => {
    if (currentBucket) {
      loadContents(currentBucket, currentPrefix)
    }
  }, [currentBucket, currentPrefix])

  const loadBuckets = async () => {
    try {
      setLoading(true)
      setError(null)
      const result = await objectStorageApi.listBuckets()

      // Filter out protected buckets (users can only browse non-protected buckets)
      const accessibleBuckets = result.buckets.filter(b => !b.is_protected)
      setBuckets(accessibleBuckets)

      // Set default bucket if available
      if (accessibleBuckets.length > 0) {
        const defaultBucket = accessibleBuckets.find(b => b.is_default) || accessibleBuckets[0]
        setCurrentBucket(defaultBucket.name)
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load storage buckets')
    } finally {
      setLoading(false)
    }
  }

  const loadContents = async (bucket: string, prefix: string) => {
    try {
      setLoading(true)
      setError(null)
      const result = await objectStorageApi.browse(bucket, prefix)
      setFolders(result.folders)
      setFiles(result.files.filter(f => !f.is_folder))
      setIsProtected(result.is_protected)
      setParentPath(result.parent_path)
    } catch (err: any) {
      setError(err.message || 'Failed to load folder contents')
    } finally {
      setLoading(false)
    }
  }

  const handleNavigateToFolder = (folderName: string) => {
    const newPrefix = currentPrefix + folderName + '/'
    setCurrentPrefix(newPrefix)
  }

  const handleNavigateToPath = (path: string) => {
    setCurrentPrefix(path)
  }

  const handleNavigateUp = () => {
    if (parentPath !== null) {
      setCurrentPrefix(parentPath)
    }
  }

  const handleBucketChange = (bucket: Bucket) => {
    setCurrentBucket(bucket.name)
    setCurrentPrefix('')
    setBucketDropdownOpen(false)
  }

  const handleFileToggle = useCallback((file: StorageFile) => {
    const fileKey = `${currentBucket}:${file.key}`
    const isSelected = selectedFiles.some(f => `${f.bucket}:${f.key}` === fileKey)

    if (isSelected) {
      // Deselect
      onSelectionChange(selectedFiles.filter(f => `${f.bucket}:${f.key}` !== fileKey))
    } else {
      // Select (check max limit)
      if (maxSelections && selectedFiles.length >= maxSelections) {
        return // Don't add more
      }
      onSelectionChange([
        ...selectedFiles,
        {
          key: file.key,
          filename: file.filename,
          bucket: currentBucket,
          size: file.size,
        },
      ])
    }
  }, [currentBucket, selectedFiles, onSelectionChange, maxSelections])

  const handleFolderToggle = useCallback(async (folderName: string) => {
    const folderPrefix = currentPrefix + folderName + '/'

    try {
      setSelectingFolder(folderName)

      // Fetch all files in this folder recursively
      const folderFiles = await fetchFolderFilesRecursively(currentBucket, folderPrefix)

      // Check if all files in the folder are already selected
      const folderFileKeys = new Set(folderFiles.map(f => `${currentBucket}:${f.key}`))
      const allFolderFilesSelected = folderFiles.every(f =>
        selectedFiles.some(sf => `${sf.bucket}:${sf.key}` === `${currentBucket}:${f.key}`)
      )

      if (allFolderFilesSelected) {
        // Deselect all files in this folder
        onSelectionChange(selectedFiles.filter(sf =>
          !folderFileKeys.has(`${sf.bucket}:${sf.key}`)
        ))
      } else {
        // Select all files in this folder
        const newSelections = folderFiles.map(f => ({
          key: f.key,
          filename: f.filename,
          bucket: currentBucket,
          size: f.size,
        }))

        // Add to existing selections (avoid duplicates)
        const existingKeys = new Set(selectedFiles.map(f => `${f.bucket}:${f.key}`))
        const toAdd = newSelections.filter(f => !existingKeys.has(`${f.bucket}:${f.key}`))

        if (maxSelections) {
          const remaining = maxSelections - selectedFiles.length
          if (remaining > 0) {
            onSelectionChange([...selectedFiles, ...toAdd.slice(0, remaining)])
          }
        } else {
          onSelectionChange([...selectedFiles, ...toAdd])
        }
      }
    } catch (err) {
      console.error('Failed to select folder:', err)
    } finally {
      setSelectingFolder(null)
    }
  }, [currentBucket, currentPrefix, selectedFiles, onSelectionChange, maxSelections])

  const fetchFolderFilesRecursively = async (bucket: string, prefix: string): Promise<StorageFile[]> => {
    const result = await objectStorageApi.browse(bucket, prefix)
    let allFiles: StorageFile[] = [...result.files.filter(f => !f.is_folder)]

    // Recursively fetch files from subfolders
    for (const folder of result.folders) {
      const subfolderFiles = await fetchFolderFilesRecursively(bucket, prefix + folder + '/')
      allFiles = [...allFiles, ...subfolderFiles]
    }

    return allFiles
  }

  const getFolderSelectionState = useCallback((folderName: string): 'none' | 'partial' | 'all' => {
    const folderPrefix = currentPrefix + folderName + '/'

    // Check files that belong to this folder (start with folder prefix)
    const folderFileKeys = selectedFiles
      .filter(f => f.bucket === currentBucket && f.key.startsWith(folderPrefix))

    if (folderFileKeys.length === 0) return 'none'

    // We can't easily determine total files without fetching, so we'll show 'partial'
    // unless we happen to know all files are selected (which we don't without a fetch)
    return 'partial'
  }, [currentBucket, currentPrefix, selectedFiles])

  const isFileSelected = (file: StorageFile): boolean => {
    const fileKey = `${currentBucket}:${file.key}`
    return selectedFiles.some(f => `${f.bucket}:${f.key}` === fileKey)
  }

  const handleSelectAll = () => {
    const newSelections = files.map(f => ({
      key: f.key,
      filename: f.filename,
      bucket: currentBucket,
      size: f.size,
    }))

    // Add to existing selections (avoid duplicates)
    const existingKeys = new Set(selectedFiles.map(f => `${f.bucket}:${f.key}`))
    const toAdd = newSelections.filter(f => !existingKeys.has(`${f.bucket}:${f.key}`))

    if (maxSelections) {
      const remaining = maxSelections - selectedFiles.length
      onSelectionChange([...selectedFiles, ...toAdd.slice(0, remaining)])
    } else {
      onSelectionChange([...selectedFiles, ...toAdd])
    }
  }

  const handleDeselectAll = () => {
    // Remove only files from current folder
    const currentFolderKeys = new Set(files.map(f => `${currentBucket}:${f.key}`))
    onSelectionChange(selectedFiles.filter(f => !currentFolderKeys.has(`${f.bucket}:${f.key}`)))
  }

  // Check if all files in current folder are selected
  const allSelected = files.length > 0 && files.every(f => isFileSelected(f))
  const someSelected = files.some(f => isFileSelected(f))

  // Empty state - no buckets or no content
  if (!loading && buckets.length === 0) {
    return (
      <div className="relative overflow-hidden rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/50 px-6 py-12 text-center">
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute -top-24 -right-24 w-64 h-64 rounded-full bg-gradient-to-br from-indigo-500/5 to-purple-500/5 blur-3xl"></div>
          <div className="absolute -bottom-24 -left-24 w-64 h-64 rounded-full bg-gradient-to-br from-blue-500/5 to-cyan-500/5 blur-3xl"></div>
        </div>

        <div className="relative">
          <div className="mx-auto w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/25 mb-4">
            <HardDrive className="w-8 h-8 text-white" />
          </div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
            No storage available
          </h3>
          <p className="text-gray-500 dark:text-gray-400 max-w-sm mx-auto mb-4">
            Upload files to storage first before creating a job.
          </p>
          <a
            href="/storage"
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 transition-colors"
          >
            Go to Storage
            <ExternalLink className="w-4 h-4" />
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
      {/* Header with bucket selector and breadcrumb */}
      <div className="border-b border-gray-200 dark:border-gray-700 p-4">
        <div className="flex flex-col sm:flex-row sm:items-center gap-3">
          {/* Bucket Selector */}
          <div className="relative">
            <button
              onClick={() => setBucketDropdownOpen(!bucketDropdownOpen)}
              className="flex items-center gap-2 px-3 py-2 bg-gray-100 dark:bg-gray-900 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-800 transition-colors min-w-[180px]"
            >
              <HardDrive className="w-4 h-4" />
              <span className="flex-1 text-left truncate">{currentBucketDisplay}</span>
              <ChevronDown className={`w-4 h-4 transition-transform ${bucketDropdownOpen ? 'rotate-180' : ''}`} />
            </button>

            {bucketDropdownOpen && (
              <div className="absolute top-full left-0 mt-1 w-56 bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 py-1 z-20">
                {buckets.map(bucket => (
                  <button
                    key={bucket.name}
                    onClick={() => handleBucketChange(bucket)}
                    className={`w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors ${
                      bucket.name === currentBucket
                        ? 'bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400'
                        : 'text-gray-700 dark:text-gray-300'
                    }`}
                  >
                    <HardDrive className="w-4 h-4" />
                    <span className="flex-1 truncate">{bucket.display_name}</span>
                    {bucket.is_default && (
                      <span className="text-xs text-gray-400 dark:text-gray-500">Default</span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Breadcrumb Navigation */}
          <div className="flex-1 overflow-hidden">
            <FolderBreadcrumb
              bucket={currentBucket}
              bucketDisplayName={currentBucketDisplay}
              prefix={currentPrefix}
              onNavigate={handleNavigateToPath}
            />
          </div>
        </div>

        {/* Selection info */}
        {selectedFiles.length > 0 && (
          <div className="mt-3 flex items-center gap-4 text-sm">
            <span className="text-gray-600 dark:text-gray-400">
              {selectedFiles.length} file{selectedFiles.length !== 1 ? 's' : ''} selected
              {maxSelections && <span className="text-gray-400"> (max {maxSelections})</span>}
            </span>
            <button
              onClick={() => onSelectionChange([])}
              className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 font-medium"
            >
              Clear all
            </button>
          </div>
        )}
      </div>

      {/* Content area */}
      <div className="min-h-[300px] max-h-[400px] overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-12 px-4">
            <AlertCircle className="w-10 h-10 text-red-500 mb-3" />
            <p className="text-sm text-red-600 dark:text-red-400 text-center">{error}</p>
            <button
              onClick={() => loadContents(currentBucket, currentPrefix)}
              className="mt-3 px-4 py-2 text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded-lg transition-colors"
            >
              Try again
            </button>
          </div>
        ) : (
          <div className="divide-y divide-gray-100 dark:divide-gray-700">
            {/* Navigate up button */}
            {parentPath !== null && (
              <button
                onClick={handleNavigateUp}
                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors text-left"
              >
                <div className="w-10 h-10 rounded-lg bg-gray-100 dark:bg-gray-800 flex items-center justify-center">
                  <ChevronUp className="w-5 h-5 text-gray-500" />
                </div>
                <span className="text-sm text-gray-600 dark:text-gray-400">..</span>
              </button>
            )}

            {/* Folders with selection */}
            {folders.map(folder => {
              const selectionState = getFolderSelectionState(folder)
              const isSelected = selectionState !== 'none'
              const isPartial = selectionState === 'partial'
              const isSelecting = selectingFolder === folder

              return (
                <div
                  key={folder}
                  className={`flex items-center gap-3 px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors ${
                    isSelected ? 'bg-indigo-50 dark:bg-indigo-900/20' : ''
                  }`}
                >
                  {isSelecting ? (
                    <div className="w-4 h-4 flex items-center justify-center">
                      <Loader2 className="w-4 h-4 animate-spin text-indigo-500" />
                    </div>
                  ) : (
                    <input
                      type="checkbox"
                      checked={isSelected}
                      ref={(el) => {
                        if (el) el.indeterminate = isPartial
                      }}
                      onChange={(e) => {
                        e.stopPropagation()
                        handleFolderToggle(folder)
                      }}
                      onClick={(e) => e.stopPropagation()}
                      className="w-4 h-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                    />
                  )}
                  <button
                    onClick={() => handleNavigateToFolder(folder)}
                    className="flex-1 flex items-center gap-3 text-left"
                    disabled={isSelecting}
                  >
                    <div className="w-10 h-10 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center">
                      <Folder className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                    </div>
                    <span className="flex-1 text-sm font-medium text-gray-900 dark:text-white truncate">
                      {folder}
                    </span>
                  </button>
                </div>
              )
            })}

            {/* Files with checkboxes */}
            {files.length > 0 && (
              <>
                {/* Select all / deselect all header */}
                <div className="flex items-center gap-3 px-4 py-2 bg-gray-50 dark:bg-gray-800/50">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    ref={(el) => {
                      if (el) el.indeterminate = someSelected && !allSelected
                    }}
                    onChange={() => allSelected ? handleDeselectAll() : handleSelectAll()}
                    className="w-4 h-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                    {allSelected ? 'Deselect all' : someSelected ? 'Select remaining' : 'Select all'} ({files.length})
                  </span>
                </div>

                {files.map(file => {
                  const selected = isFileSelected(file)
                  return (
                    <label
                      key={file.key}
                      className={`flex items-center gap-3 px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors cursor-pointer ${
                        selected ? 'bg-indigo-50 dark:bg-indigo-900/20' : ''
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={() => handleFileToggle(file)}
                        className="w-4 h-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                      />
                      <div className="w-10 h-10 rounded-lg bg-gray-100 dark:bg-gray-800 flex items-center justify-center flex-shrink-0">
                        <FileText className="w-5 h-5 text-gray-500" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                          {file.filename}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          {utils.formatFileSize(file.size)}
                        </p>
                      </div>
                    </label>
                  )
                })}
              </>
            )}

            {/* Empty folder state */}
            {folders.length === 0 && files.length === 0 && (
              <div className="flex flex-col items-center justify-center py-12 px-4">
                <Folder className="w-12 h-12 text-gray-300 dark:text-gray-600 mb-3" />
                <p className="text-sm text-gray-500 dark:text-gray-400 text-center">
                  This folder is empty
                </p>
                <a
                  href="/storage"
                  className="mt-3 inline-flex items-center gap-2 text-sm text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300"
                >
                  Upload files in Storage
                  <ExternalLink className="w-4 h-4" />
                </a>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

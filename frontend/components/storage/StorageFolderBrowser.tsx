'use client'

import React, { useState, useEffect } from 'react'
import {
  Folder,
  FileText,
  ChevronUp,
  Loader2,
  AlertCircle,
  HardDrive,
  ChevronDown,
  Plus,
  Trash2,
  Download,
  Eye,
  FolderPlus,
  MoreHorizontal,
  Upload,
  Copy,
  Check,
} from 'lucide-react'
import { objectStorageApi, organizationsApi, utils } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import FolderBreadcrumb from '../shared/FolderBreadcrumb'
import toast from 'react-hot-toast'

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

interface StorageFolderBrowserProps {
  onFilePreview?: (bucket: string, key: string, filename: string) => void
  onFileDownload?: (bucket: string, key: string, filename: string) => void
  onFileUpload?: (bucket: string, prefix: string) => void
}

export default function StorageFolderBrowser({
  onFilePreview,
  onFileDownload,
  onFileUpload,
}: StorageFolderBrowserProps) {
  // Auth
  const { token } = useAuth()

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
  const [showCreateFolderModal, setShowCreateFolderModal] = useState<boolean>(false)
  const [newFolderName, setNewFolderName] = useState<string>('')
  const [isCreatingFolder, setIsCreatingFolder] = useState<boolean>(false)
  const [deletingFolder, setDeletingFolder] = useState<string | null>(null)
  const [deletingFile, setDeletingFile] = useState<string | null>(null)
  const [copiedPath, setCopiedPath] = useState<string | null>(null)

  // Organization data for folder name mapping
  const [currentOrganization, setCurrentOrganization] = useState<{ id: string; name: string; display_name: string } | null>(null)

  // Get current bucket display name
  const currentBucketDisplay = buckets.find(b => b.name === currentBucket)?.display_name || currentBucket

  // Helper function to check if a string is a UUID
  const isUUID = (str: string): boolean => {
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
    return uuidRegex.test(str)
  }

  // Helper function to get display name for a folder
  const getFolderDisplayName = (folderName: string): string => {
    // Check if at root level and folder name is a UUID (organization folder)
    if (currentPrefix === '' && isUUID(folderName) && currentOrganization) {
      // Check if this UUID matches the current organization
      if (folderName.toLowerCase() === currentOrganization.id.toLowerCase()) {
        return currentOrganization.display_name || currentOrganization.name
      }
      // For other org UUIDs, we could fetch them, but for now just show "Organization"
      return `Organization (${folderName.substring(0, 8)}...)`
    }

    // Return the folder name as-is for non-org folders
    return folderName
  }

  // Strip the org_id prefix (first path segment) from a storage path
  const stripOrgPrefix = (path: string): string => {
    const parts = path.split('/')
    // First segment is the org_id UUID — remove it
    if (parts.length > 1 && isUUID(parts[0])) {
      return parts.slice(1).join('/')
    }
    return path
  }

  // Copy a folder path to clipboard with feedback
  const handleCopyPath = (path: string) => {
    const cleanPath = stripOrgPrefix(path).replace(/\/$/, '')
    navigator.clipboard.writeText(cleanPath)
    setCopiedPath(path)
    toast.success('Folder path copied')
    setTimeout(() => setCopiedPath(null), 2000)
  }

  // Load current organization on mount
  useEffect(() => {
    if (token) {
      loadCurrentOrganization()
    }
  }, [token])

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

  const loadCurrentOrganization = async () => {
    if (!token) return

    try {
      const org = await organizationsApi.getCurrentOrganization(token)
      setCurrentOrganization({
        id: org.id,
        name: org.name,
        display_name: org.display_name
      })
    } catch (err: any) {
      console.warn('Failed to load organization:', err)
      // Not critical - just won't have org name mapping
    }
  }

  const loadBuckets = async () => {
    try {
      setLoading(true)
      setError(null)
      const result = await objectStorageApi.listBuckets()

      // Show all buckets (including protected) for admin view
      setBuckets(result.buckets)

      // Set default bucket if available
      if (result.buckets.length > 0) {
        const defaultBucket = result.buckets.find(b => b.is_default) || result.buckets[0]
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

  const handleCreateFolder = async () => {
    const trimmedName = newFolderName.trim()

    if (!trimmedName) {
      toast.error('Folder name cannot be empty')
      return
    }

    // Validate folder name (no special characters except dash/underscore)
    if (!/^[a-zA-Z0-9_-]+$/.test(trimmedName)) {
      toast.error('Folder name can only contain letters, numbers, dashes, and underscores')
      return
    }

    setIsCreatingFolder(true)
    try {
      // Build folder path: currentPrefix + folderName (backend adds trailing /)
      // Example: "" + "my-folder" = "my-folder"
      // Example: "org-123/" + "my-folder" = "org-123/my-folder"
      const folderPath = currentPrefix + trimmedName

      console.log('Creating folder:', {
        bucket: currentBucket,
        prefix: currentPrefix,
        folderName: trimmedName,
        fullPath: folderPath
      })

      await objectStorageApi.createFolder(currentBucket, folderPath)
      toast.success(`Folder "${trimmedName}" created`)
      setShowCreateFolderModal(false)
      setNewFolderName('')
      // Reload current folder
      await loadContents(currentBucket, currentPrefix)
    } catch (err: any) {
      console.error('Failed to create folder:', err)
      toast.error(`Failed to create folder: ${err.message}`)
    } finally {
      setIsCreatingFolder(false)
    }
  }

  const handleDeleteFolder = async (folderName: string) => {
    if (isProtected) {
      toast.error('Cannot delete folders in protected buckets')
      return
    }

    const confirmed = window.confirm(
      `Delete folder "${folderName}" and all its contents? This cannot be undone.`
    )
    if (!confirmed) return

    setDeletingFolder(folderName)
    try {
      const folderPath = currentPrefix + folderName
      await objectStorageApi.deleteFolder(currentBucket, folderPath, true)
      toast.success(`Folder "${folderName}" deleted`)
      // Reload current folder
      await loadContents(currentBucket, currentPrefix)
    } catch (err: any) {
      console.error('Failed to delete folder:', err)
      toast.error(`Failed to delete folder: ${err.message}`)
    } finally {
      setDeletingFolder(null)
    }
  }

  const handleDeleteFile = async (file: StorageFile) => {
    if (isProtected) {
      toast.error('Cannot delete files in protected buckets')
      return
    }

    const confirmed = window.confirm(
      `Delete file "${file.filename}"? This cannot be undone.`
    )
    if (!confirmed) return

    setDeletingFile(file.key)
    try {
      await objectStorageApi.deleteFile(currentBucket, file.key, token ?? undefined)
      toast.success(`File "${file.filename}" deleted`)
      // Reload current folder
      await loadContents(currentBucket, currentPrefix)
    } catch (err: any) {
      console.error('Failed to delete file:', err)
      toast.error(`Failed to delete file: ${err.message}`)
    } finally {
      setDeletingFile(null)
    }
  }

  const handleFileAction = (file: StorageFile, action: 'preview' | 'download') => {
    if (action === 'preview' && onFilePreview) {
      onFilePreview(currentBucket, file.key, file.filename)
    } else if (action === 'download' && onFileDownload) {
      onFileDownload(currentBucket, file.key, file.filename)
    }
  }

  // Empty state
  if (!loading && buckets.length === 0) {
    return (
      <div className="relative overflow-hidden rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/50 px-6 py-12 text-center">
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute -top-24 -right-24 w-64 h-64 rounded-full bg-gradient-to-br from-indigo-500/5 to-purple-500/5 blur-3xl"></div>
        </div>

        <div className="relative">
          <div className="mx-auto w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/25 mb-4">
            <HardDrive className="w-8 h-8 text-white" />
          </div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
            No storage available
          </h3>
          <p className="text-gray-500 dark:text-gray-400 max-w-sm mx-auto">
            Object storage is not configured or no buckets are available.
          </p>
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
              className="flex items-center gap-3 px-4 py-2.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors min-w-[220px] shadow-sm"
            >
              <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center flex-shrink-0">
                <HardDrive className="w-5 h-5 text-white" />
              </div>
              <div className="flex-1 text-left min-w-0">
                <div className="text-sm font-semibold text-gray-900 dark:text-white truncate">
                  {currentBucketDisplay}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400">
                  {buckets.find(b => b.name === currentBucket)?.is_protected ? 'Read-only' : 'Writable'}
                </div>
              </div>
              <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform flex-shrink-0 ${bucketDropdownOpen ? 'rotate-180' : ''}`} />
            </button>

            {bucketDropdownOpen && (
              <div className="absolute top-full left-0 mt-2 w-80 bg-white dark:bg-gray-800 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 py-2 z-20 overflow-hidden">
                <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-700">
                  <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Storage Locations
                  </p>
                </div>
                {buckets.map(bucket => (
                  <button
                    key={bucket.name}
                    onClick={() => handleBucketChange(bucket)}
                    className={`w-full flex items-center gap-3 px-3 py-3 text-sm text-left hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors ${
                      bucket.name === currentBucket
                        ? 'bg-indigo-50 dark:bg-indigo-900/20'
                        : ''
                    }`}
                  >
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${
                      bucket.name === currentBucket
                        ? 'bg-gradient-to-br from-indigo-500 to-purple-600'
                        : 'bg-gray-100 dark:bg-gray-700'
                    }`}>
                      <HardDrive className={`w-5 h-5 ${
                        bucket.name === currentBucket ? 'text-white' : 'text-gray-500 dark:text-gray-400'
                      }`} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className={`text-sm font-semibold truncate ${
                        bucket.name === currentBucket
                          ? 'text-indigo-600 dark:text-indigo-400'
                          : 'text-gray-900 dark:text-white'
                      }`}>
                        {bucket.display_name}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className={`text-xs px-2 py-0.5 rounded-full ${
                          bucket.is_protected
                            ? 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400'
                            : 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400'
                        }`}>
                          {bucket.is_protected ? 'Read-only' : 'Writable'}
                        </span>
                        {bucket.is_default && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400">
                            Default
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Breadcrumb Navigation */}
          <div className="flex-1 overflow-hidden flex items-center gap-2">
            <FolderBreadcrumb
              bucket={currentBucket}
              bucketDisplayName={currentBucketDisplay}
              prefix={currentPrefix}
              onNavigate={handleNavigateToPath}
            />
            {currentPrefix && (
              <button
                onClick={() => handleCopyPath(currentPrefix)}
                className="flex-shrink-0 p-1.5 text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded-md transition-colors"
                title="Copy folder path"
              >
                {copiedPath === currentPrefix ? (
                  <Check className="w-3.5 h-3.5 text-emerald-500" />
                ) : (
                  <Copy className="w-3.5 h-3.5" />
                )}
              </button>
            )}
          </div>

          {/* Actions */}
          {!isProtected && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => onFileUpload?.(currentBucket, currentPrefix)}
                className="flex items-center gap-2 px-3 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg transition-colors shadow-sm"
              >
                <Upload className="w-4 h-4" />
                <span className="hidden sm:inline">Upload</span>
              </button>
              <button
                onClick={() => setShowCreateFolderModal(true)}
                className="flex items-center gap-2 px-3 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors shadow-sm"
              >
                <FolderPlus className="w-4 h-4" />
                <span className="hidden sm:inline">New Folder</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Content area - Table View */}
      <div className="min-h-[400px] overflow-hidden">
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
          <div className="overflow-x-auto">
            {/* Table Header */}
            <div className="bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700 px-4 py-3">
              <div className="grid grid-cols-12 gap-4 text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider">
                <div className="col-span-5">Name</div>
                <div className="col-span-2">Type</div>
                <div className="col-span-2">Size</div>
                <div className="col-span-2">Modified</div>
                <div className="col-span-1 text-right">Actions</div>
              </div>
            </div>

            {/* Table Body */}
            <div className="divide-y divide-gray-100 dark:divide-gray-700">
              {/* Navigate up button */}
              {parentPath !== null && (
                <button
                  onClick={handleNavigateUp}
                  className="w-full px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
                >
                  <div className="grid grid-cols-12 gap-4 items-center">
                    <div className="col-span-5 flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-gray-100 dark:bg-gray-800 flex items-center justify-center flex-shrink-0">
                        <ChevronUp className="w-4 h-4 text-gray-500" />
                      </div>
                      <span className="text-sm text-gray-600 dark:text-gray-400">..</span>
                    </div>
                    <div className="col-span-7"></div>
                  </div>
                </button>
              )}

              {/* Folders */}
              {folders.map(folder => {
                const displayName = getFolderDisplayName(folder)
                return (
                  <div
                    key={folder}
                    className="px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors group"
                  >
                    <div className="grid grid-cols-12 gap-4 items-center">
                      <button
                        onClick={() => handleNavigateToFolder(folder)}
                        className="col-span-5 flex items-center gap-3 text-left min-w-0"
                      >
                        <div className="w-8 h-8 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center flex-shrink-0">
                          <Folder className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                        </div>
                        <div className="flex flex-col min-w-0">
                          <span className="text-sm font-medium text-gray-900 dark:text-white truncate">
                            {displayName}
                          </span>
                          {displayName !== folder && (
                            <span className="text-xs text-gray-500 dark:text-gray-400 font-mono truncate">
                              {folder}
                            </span>
                          )}
                        </div>
                      </button>
                    <div className="col-span-2 text-sm text-gray-500 dark:text-gray-400">
                      Folder
                    </div>
                    <div className="col-span-2 text-sm text-gray-500 dark:text-gray-400">
                      —
                    </div>
                    <div className="col-span-2 text-sm text-gray-500 dark:text-gray-400">
                      —
                    </div>
                    <div className="col-span-1 flex items-center justify-end gap-1">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleCopyPath(currentPrefix + folder + '/')
                        }}
                        className="opacity-0 group-hover:opacity-100 p-2 text-gray-600 dark:text-gray-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 hover:text-indigo-600 dark:hover:text-indigo-400 rounded-lg transition-all"
                        title="Copy folder path"
                      >
                        {copiedPath === currentPrefix + folder + '/' ? (
                          <Check className="w-4 h-4 text-emerald-500" />
                        ) : (
                          <Copy className="w-4 h-4" />
                        )}
                      </button>
                      {!isProtected && (
                        <button
                          onClick={() => handleDeleteFolder(folder)}
                          disabled={deletingFolder === folder}
                          className="opacity-0 group-hover:opacity-100 p-2 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-all disabled:opacity-50"
                          title="Delete folder"
                        >
                          {deletingFolder === folder ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <Trash2 className="w-4 h-4" />
                          )}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )
              })}

              {/* Files */}
              {files.map(file => (
                <div
                  key={file.key}
                  className="px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors group"
                >
                  <div className="grid grid-cols-12 gap-4 items-center">
                    <div className="col-span-5 flex items-center gap-3 min-w-0">
                      <div className="w-8 h-8 rounded-lg bg-gray-100 dark:bg-gray-800 flex items-center justify-center flex-shrink-0">
                        <FileText className="w-4 h-4 text-gray-500" />
                      </div>
                      <span className="text-sm font-medium text-gray-900 dark:text-white truncate">
                        {file.filename}
                      </span>
                    </div>
                    <div className="col-span-2 text-sm text-gray-500 dark:text-gray-400">
                      {file.content_type?.split('/')[1]?.toUpperCase() || 'File'}
                    </div>
                    <div className="col-span-2 text-sm text-gray-500 dark:text-gray-400">
                      {utils.formatFileSize(file.size)}
                    </div>
                    <div className="col-span-2 text-sm text-gray-500 dark:text-gray-400">
                      {new Date(file.last_modified).toLocaleDateString()}
                    </div>
                    <div className="col-span-1 flex items-center justify-end gap-1">
                      <button
                        onClick={() => handleFileAction(file, 'preview')}
                        className="opacity-0 group-hover:opacity-100 p-2 text-gray-600 dark:text-gray-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 hover:text-blue-600 dark:hover:text-blue-400 rounded-lg transition-all"
                        title="Preview"
                      >
                        <Eye className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleFileAction(file, 'download')}
                        className="opacity-0 group-hover:opacity-100 p-2 text-gray-600 dark:text-gray-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 hover:text-indigo-600 dark:hover:text-indigo-400 rounded-lg transition-all"
                        title="Download"
                      >
                        <Download className="w-4 h-4" />
                      </button>
                      {!isProtected && (
                        <button
                          onClick={() => handleDeleteFile(file)}
                          disabled={deletingFile === file.key}
                          className="opacity-0 group-hover:opacity-100 p-2 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-all disabled:opacity-50"
                          title="Delete file"
                        >
                          {deletingFile === file.key ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <Trash2 className="w-4 h-4" />
                          )}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}

              {/* Empty folder state */}
              {folders.length === 0 && files.length === 0 && (
                <div className="flex flex-col items-center justify-center py-16 px-4">
                  <Folder className="w-12 h-12 text-gray-300 dark:text-gray-600 mb-3" />
                  <p className="text-sm text-gray-500 dark:text-gray-400 text-center">
                    This folder is empty
                  </p>
                  {!isProtected && (
                    <div className="flex items-center gap-3 mt-6">
                      <button
                        onClick={() => onFileUpload?.(currentBucket, currentPrefix)}
                        className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 rounded-lg transition-colors"
                      >
                        <Upload className="w-4 h-4" />
                        Upload files
                      </button>
                      <button
                        onClick={() => setShowCreateFolderModal(true)}
                        className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded-lg transition-colors"
                      >
                        <FolderPlus className="w-4 h-4" />
                        Create folder
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Create Folder Modal */}
      {showCreateFolderModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="relative bg-white dark:bg-gray-800 rounded-2xl shadow-2xl max-w-md w-full overflow-hidden">
            {/* Modal Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-600">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-white/20 flex items-center justify-center">
                  <FolderPlus className="w-5 h-5 text-white" />
                </div>
                <h3 className="text-lg font-semibold text-white">Create New Folder</h3>
              </div>
            </div>

            {/* Modal Content */}
            <div className="p-6">
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Folder Name
                </label>
                <input
                  type="text"
                  value={newFolderName}
                  onChange={(e) => setNewFolderName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      handleCreateFolder()
                    }
                  }}
                  placeholder="my-folder"
                  className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
                  autoFocus
                />
                <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                  Only letters, numbers, dashes, and underscores allowed
                </p>
              </div>

              <div className="text-sm text-gray-600 dark:text-gray-400">
                <p>
                  <strong>Current location:</strong>
                </p>
                <p className="mt-1 font-mono text-xs bg-gray-50 dark:bg-gray-900 px-3 py-2 rounded">
                  {currentBucket}/{currentPrefix || '(root)'}
                </p>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
              <button
                onClick={() => {
                  setShowCreateFolderModal(false)
                  setNewFolderName('')
                }}
                disabled={isCreatingFolder}
                className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateFolder}
                disabled={isCreatingFolder || !newFolderName.trim()}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isCreatingFolder ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Creating...
                  </>
                ) : (
                  <>
                    <FolderPlus className="w-4 h-4" />
                    Create Folder
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter, useParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { sharepointSyncApi, SharePointSyncConfig, SharePointSyncedDocument } from '@/lib/api'
import { formatDateTime, formatDuration } from '@/lib/date-utils'
import { Button } from '@/components/ui/Button'
import { ConfirmDeleteDialog } from '@/components/ui/ConfirmDeleteDialog'
import { useDeletionJobs } from '@/lib/deletion-jobs-context'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import toast from 'react-hot-toast'
import {
  FolderSync,
  ArrowLeft,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  Pause,
  Archive,
  Play,
  FileText,
  Folder,
  Calendar,
  Trash2,
  ExternalLink,
  Loader2,
  History,
  Settings,
  Edit3,
  AlertCircle,
  X,
  Info,
  HardDrive,
  Power,
  ToggleLeft,
  ToggleRight,
  Save,
  Shield,
  CheckSquare,
  Square,
} from 'lucide-react'

// ============================================================================
// Edit Modal Component
// ============================================================================

interface SharePointBrowseItem {
  id: string
  name: string
  type: 'file' | 'folder'
  size?: number
  modified?: string
  web_url?: string
  folder?: string
  drive_id?: string
  mime_type?: string
}

interface EditModalProps {
  config: SharePointSyncConfig
  token: string | null
  isOpen: boolean
  onClose: () => void
  onSave: (updates: any, resetAssets: boolean) => Promise<{ success: boolean; error?: string }>
  onImportFiles: (items: SharePointBrowseItem[]) => Promise<void>
  onRemoveItems: (itemIds: string[]) => Promise<void>
}

function EditModal({ config, token, isOpen, onClose, onSave, onImportFiles, onRemoveItems }: EditModalProps) {
  // Tab state
  const [activeTab, setActiveTab] = useState<'general' | 'folders'>('general')

  // Form state
  const [name, setName] = useState(config.name)
  const [description, setDescription] = useState(config.description || '')
  const [syncFrequency, setSyncFrequency] = useState(config.sync_frequency)
  const [recursive, setRecursive] = useState(config.sync_config?.recursive ?? true)
  const [syncMode, setSyncMode] = useState<'all' | 'selected'>(
    (config.sync_config?.selection_mode as 'all' | 'selected') || 'all'
  )
  const [includePatterns, setIncludePatterns] = useState(
    (config.sync_config?.include_patterns || []).join(', ')
  )
  const [excludePatterns, setExcludePatterns] = useState(
    (config.sync_config?.exclude_patterns || []).join(', ')
  )

  // Folder browser state
  const [browseItems, setBrowseItems] = useState<SharePointBrowseItem[]>([])
  const [isLoadingFolders, setIsLoadingFolders] = useState(false)
  const [folderError, setFolderError] = useState('')

  // Selection state
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set())
  const [syncedItemIds, setSyncedItemIds] = useState<Set<string>>(new Set())
  const [initialSelectedItems, setInitialSelectedItems] = useState<Set<string>>(new Set())

  // UI state
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')
  const [breakingChanges, setBreakingChanges] = useState<string[]>([])
  const [showResetConfirm, setShowResetConfirm] = useState(false)
  const [existingAssetCount, setExistingAssetCount] = useState(0)

  // Reset form when config changes
  useEffect(() => {
    if (isOpen) {
      setActiveTab('general')
      setName(config.name)
      setDescription(config.description || '')
      setSyncFrequency(config.sync_frequency)
      setRecursive(config.sync_config?.recursive ?? true)
      setSyncMode((config.sync_config?.selection_mode as 'all' | 'selected') || 'all')
      setIncludePatterns((config.sync_config?.include_patterns || []).join(', '))
      setExcludePatterns((config.sync_config?.exclude_patterns || []).join(', '))
      setError('')
      setFolderError('')
      setBreakingChanges([])
      setShowResetConfirm(false)
      setBrowseItems([])
      setSelectedItems(new Set())
      setSyncedItemIds(new Set())
      setInitialSelectedItems(new Set())
    }
  }, [config, isOpen])

  // Load folder contents and synced documents when switching to folders tab
  const loadFolderContents = useCallback(async () => {
    if (!token || !config.folder_url) return

    setIsLoadingFolders(true)
    setFolderError('')

    try {
      // Load folder contents and synced documents in parallel
      const [browseResponse, docsResponse] = await Promise.all([
        sharepointSyncApi.browseFolder(token, {
          connection_id: config.connection_id || undefined,
          folder_url: config.folder_url,
          recursive: false,
          include_folders: true,
        }),
        sharepointSyncApi.listDocuments(token, config.id, { limit: 1000 }),
      ])

      const items = browseResponse.items || []
      setBrowseItems(items)

      // Get IDs of already synced items
      const syncedIds = new Set<string>(
        (docsResponse.documents || [])
          .filter((doc: SharePointSyncedDocument) => doc.sync_status === 'synced')
          .map((doc: SharePointSyncedDocument) => doc.sharepoint_item_id)
      )
      setSyncedItemIds(syncedIds)

      // Pre-select synced items
      const preSelected = new Set<string>(
        items.filter(item => syncedIds.has(item.id)).map(item => item.id)
      )
      setSelectedItems(preSelected)
      setInitialSelectedItems(new Set(preSelected))
    } catch (err: any) {
      setFolderError(err.message || 'Failed to load folder contents')
    } finally {
      setIsLoadingFolders(false)
    }
  }, [token, config.folder_url, config.connection_id, config.id])

  // Load folders when tab changes
  useEffect(() => {
    if (activeTab === 'folders' && browseItems.length === 0 && !isLoadingFolders) {
      loadFolderContents()
    }
  }, [activeTab, browseItems.length, isLoadingFolders, loadFolderContents])

  // Toggle item selection
  const toggleItemSelection = (itemId: string) => {
    setSelectedItems(prev => {
      const next = new Set(prev)
      if (next.has(itemId)) {
        next.delete(itemId)
      } else {
        next.add(itemId)
      }
      return next
    })
  }

  // Select all items
  const selectAllItems = () => {
    const itemIds = browseItems.map(i => i.id)
    setSelectedItems(new Set(itemIds))
  }

  // Select all files only
  const selectAllFiles = () => {
    const fileIds = browseItems.filter(i => i.type === 'file').map(i => i.id)
    setSelectedItems(new Set(fileIds))
  }

  // Clear selection
  const clearSelection = () => {
    setSelectedItems(new Set())
  }

  // Calculate selection changes
  const getSelectionChanges = useCallback(() => {
    const newlySelected = [...selectedItems].filter(id => !initialSelectedItems.has(id))
    const newlyDeselected = [...initialSelectedItems].filter(id => !selectedItems.has(id))
    return { newlySelected, newlyDeselected }
  }, [selectedItems, initialSelectedItems])

  // Detect breaking changes
  const detectBreakingChanges = useCallback(() => {
    const changes: string[] = []

    const wasRecursive = config.sync_config?.recursive ?? true
    if (wasRecursive && !recursive) {
      changes.push('Recursive disabled - files in subfolders will be orphaned')
    }

    return changes
  }, [recursive, config])

  // Build updates object
  const buildUpdates = useCallback(() => {
    const updates: Record<string, any> = {}

    if (name !== config.name) updates.name = name
    if (description !== (config.description || '')) updates.description = description
    if (syncFrequency !== config.sync_frequency) updates.sync_frequency = syncFrequency

    // Build sync_config updates
    const syncConfigUpdates: Record<string, any> = {}
    const wasRecursive = config.sync_config?.recursive ?? true
    if (recursive !== wasRecursive) syncConfigUpdates.recursive = recursive

    const wasSelectionMode = config.sync_config?.selection_mode || 'all'
    if (syncMode !== wasSelectionMode) syncConfigUpdates.selection_mode = syncMode

    const newInclude = includePatterns
      .split(',')
      .map((p: string) => p.trim())
      .filter(Boolean)
    const oldInclude = config.sync_config?.include_patterns || []
    if (JSON.stringify(newInclude) !== JSON.stringify(oldInclude)) {
      syncConfigUpdates.include_patterns = newInclude
    }

    const newExclude = excludePatterns
      .split(',')
      .map((p: string) => p.trim())
      .filter(Boolean)
    const oldExclude = config.sync_config?.exclude_patterns || []
    if (JSON.stringify(newExclude) !== JSON.stringify(oldExclude)) {
      syncConfigUpdates.exclude_patterns = newExclude
    }

    if (Object.keys(syncConfigUpdates).length > 0) {
      updates.sync_config = syncConfigUpdates
    }

    return updates
  }, [name, description, syncFrequency, recursive, syncMode, includePatterns, excludePatterns, config])

  // Handle save attempt
  const handleSave = async (resetAssets: boolean = false) => {
    setError('')
    setIsSaving(true)

    try {
      const updates = buildUpdates()
      const { newlySelected, newlyDeselected } = getSelectionChanges()

      // If no config changes and no selection changes, just close
      if (Object.keys(updates).length === 0 && newlySelected.length === 0 && newlyDeselected.length === 0) {
        onClose()
        return
      }

      // Save config updates if there are any
      if (Object.keys(updates).length > 0) {
        const result = await onSave(updates, resetAssets)

        if (!result.success) {
          if (result.error) {
            // Check if it's a breaking changes error
            try {
              const errorData = JSON.parse(result.error)
              if (errorData.breaking_changes) {
                setBreakingChanges(errorData.breaking_changes)
                setExistingAssetCount(errorData.existing_assets || 0)
                setShowResetConfirm(true)
                return
              } else {
                setError(result.error)
                return
              }
            } catch {
              setError(result.error)
              return
            }
          }
          return
        }
      }

      // Remove deselected items (items that were synced but user unchecked)
      if (newlyDeselected.length > 0) {
        await onRemoveItems(newlyDeselected)
      }

      // Import newly selected files
      if (newlySelected.length > 0) {
        const itemsToImport = browseItems.filter(item => newlySelected.includes(item.id))
        await onImportFiles(itemsToImport)
      }

      onClose()
    } catch (err: any) {
      setError(err.message || 'Failed to save changes')
    } finally {
      setIsSaving(false)
    }
  }

  const { newlySelected, newlyDeselected } = getSelectionChanges()
  const hasChanges = Object.keys(buildUpdates()).length > 0 || newlySelected.length > 0 || newlyDeselected.length > 0
  const currentBreakingChanges = detectBreakingChanges()

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Modal - wider */}
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="relative w-full max-w-4xl bg-white dark:bg-gray-800 rounded-2xl shadow-2xl">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center">
                <Edit3 className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Edit Sync Configuration
                </h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Update settings for {config.name}
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Reset Confirmation View */}
          {showResetConfirm ? (
            <div className="p-6">
              <div className="rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 mb-6">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="w-6 h-6 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <h3 className="text-sm font-semibold text-red-800 dark:text-red-200 mb-2">
                      Breaking Changes Detected
                    </h3>
                    <p className="text-sm text-red-700 dark:text-red-300 mb-3">
                      This update will invalidate {existingAssetCount} existing synced assets.
                      They must be deleted before proceeding.
                    </p>
                    <ul className="space-y-1">
                      {breakingChanges.map((change, idx) => (
                        <li key={idx} className="text-sm text-red-600 dark:text-red-400 flex items-center gap-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                          {change}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>

              <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4 mb-6">
                <p className="text-sm text-gray-700 dark:text-gray-300 mb-2">
                  <strong>What will happen:</strong>
                </p>
                <ul className="text-sm text-gray-600 dark:text-gray-400 space-y-1">
                  <li>• {existingAssetCount} assets and their extracted content will be deleted</li>
                  <li>• Storage space will be freed</li>
                  <li>• Documents will be removed from search</li>
                  <li>• After update, run a sync to import files from the new location</li>
                </ul>
              </div>

              <div className="flex items-center justify-end gap-3">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setShowResetConfirm(false)
                    setBreakingChanges([])
                  }}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  onClick={() => handleSave(true)}
                  disabled={isSaving}
                  className="gap-2 bg-red-600 hover:bg-red-700"
                >
                  {isSaving ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Trash2 className="w-4 h-4" />
                  )}
                  Delete Assets & Update
                </Button>
              </div>
            </div>
          ) : (
            /* Normal Edit Form */
            <>
              {/* Connection & Folder Info - Always visible */}
              <div className="px-6 pt-4 pb-2 bg-gray-50 dark:bg-gray-900/30">
                <div className="flex flex-col sm:flex-row sm:items-start gap-4">
                  {/* SharePoint Connection */}
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <FolderSync className="w-4 h-4 text-indigo-500" />
                      <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                        SharePoint Connection
                      </span>
                      <div className="relative group">
                        <Info className="w-3.5 h-3.5 text-gray-400 cursor-help" />
                        <div className="absolute left-0 top-full mt-2 px-3 py-2 bg-gray-900 dark:bg-gray-700 text-white text-xs rounded-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 w-56 z-20 shadow-lg">
                          <div className="absolute left-4 bottom-full w-0 h-0 border-l-4 border-r-4 border-b-4 border-transparent border-b-gray-900 dark:border-b-gray-700" />
                          The connection cannot be changed. To use a different connection, create a new sync configuration.
                        </div>
                      </div>
                    </div>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">
                      {config.connection_name || 'Default Connection'}
                    </p>
                  </div>

                  {/* SharePoint Folder */}
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <Folder className="w-4 h-4 text-indigo-500" />
                      <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                        SharePoint Folder
                      </span>
                      <div className="relative group">
                        <Info className="w-3.5 h-3.5 text-gray-400 cursor-help" />
                        <div className="absolute right-0 top-full mt-2 px-3 py-2 bg-gray-900 dark:bg-gray-700 text-white text-xs rounded-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 w-56 z-20 shadow-lg">
                          <div className="absolute right-4 bottom-full w-0 h-0 border-l-4 border-r-4 border-b-4 border-transparent border-b-gray-900 dark:border-b-gray-700" />
                          The folder URL cannot be changed. To sync a different folder, create a new sync configuration.
                        </div>
                      </div>
                    </div>
                    <p className="text-sm font-medium text-gray-900 dark:text-white truncate" title={config.folder_url}>
                      {config.folder_name || config.folder_url.split('/').pop() || config.folder_url}
                    </p>
                  </div>
                </div>
              </div>

              {/* Tabs */}
              <div className="px-6 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/30">
                <div className="flex gap-6">
                  <button
                    onClick={() => setActiveTab('general')}
                    className={`py-3 text-sm font-medium border-b-2 transition-colors ${
                      activeTab === 'general'
                        ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                        : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
                    }`}
                  >
                    General
                  </button>
                  <button
                    onClick={() => setActiveTab('folders')}
                    className={`py-3 text-sm font-medium border-b-2 transition-colors ${
                      activeTab === 'folders'
                        ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                        : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
                    }`}
                  >
                    Folders & Filters
                  </button>
                </div>
              </div>

              <div className="p-6 space-y-6 max-h-[50vh] overflow-y-auto">
                {/* Error Message */}
                {error && (
                  <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-3">
                    <div className="flex items-center gap-2">
                      <AlertCircle className="w-4 h-4 text-red-600 dark:text-red-400" />
                      <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
                    </div>
                  </div>
                )}

                {/* General Tab */}
                {activeTab === 'general' && (
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Name *
                      </label>
                      <input
                        type="text"
                        value={name}
                        onChange={e => setName(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                      />
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Description
                      </label>
                      <textarea
                        value={description}
                        onChange={e => setDescription(e.target.value)}
                        rows={3}
                        className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                      />
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Sync Frequency
                      </label>
                      <select
                        value={syncFrequency}
                        onChange={e => setSyncFrequency(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                      >
                        <option value="manual">Manual only</option>
                        <option value="hourly">Hourly</option>
                        <option value="daily">Daily</option>
                      </select>
                      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                        You can always trigger a sync manually using the &quot;Sync Now&quot; button.
                      </p>
                    </div>
                  </div>
                )}

                {/* Folders Tab */}
                {activeTab === 'folders' && (
                  <div className="space-y-6">
                    {/* Sync Mode Toggle */}
                    <div>
                      <h4 className="text-sm font-medium text-gray-900 dark:text-white mb-3">
                        Sync Mode
                      </h4>
                      <div className="space-y-2">
                        <button
                          onClick={() => setSyncMode('all')}
                          className={`w-full p-3 rounded-lg border text-left transition-colors ${
                            syncMode === 'all'
                              ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                              : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                          }`}
                        >
                          <div className="flex items-center gap-3">
                            <div className={`w-6 h-6 rounded-full flex items-center justify-center ${
                              syncMode === 'all'
                                ? 'bg-indigo-600'
                                : 'bg-gray-200 dark:bg-gray-600'
                            }`}>
                              {syncMode === 'all' && (
                                <CheckCircle2 className="w-4 h-4 text-white" />
                              )}
                            </div>
                            <div>
                              <p className="font-medium text-gray-900 dark:text-white text-sm">Sync All</p>
                              <p className="text-xs text-gray-500 dark:text-gray-400">
                                Sync everything in this folder (respects include/exclude patterns)
                              </p>
                            </div>
                          </div>
                        </button>
                        <button
                          onClick={() => setSyncMode('selected')}
                          className={`w-full p-3 rounded-lg border text-left transition-colors ${
                            syncMode === 'selected'
                              ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                              : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                          }`}
                        >
                          <div className="flex items-center gap-3">
                            <div className={`w-6 h-6 rounded-full flex items-center justify-center ${
                              syncMode === 'selected'
                                ? 'bg-indigo-600'
                                : 'bg-gray-200 dark:bg-gray-600'
                            }`}>
                              {syncMode === 'selected' && (
                                <CheckCircle2 className="w-4 h-4 text-white" />
                              )}
                            </div>
                            <div>
                              <p className="font-medium text-gray-900 dark:text-white text-sm">Select specific files/folders</p>
                              <p className="text-xs text-gray-500 dark:text-gray-400">
                                Choose exactly which items to sync
                              </p>
                            </div>
                          </div>
                        </button>
                      </div>
                    </div>

                    {/* Recursive Setting */}
                    <div className="flex items-center justify-between p-4 rounded-lg bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-700">
                      <div>
                        <p className="text-sm font-medium text-gray-900 dark:text-white">
                          Include Subfolders (Recursive)
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                          Sync files from all subfolders within this folder
                        </p>
                        {(config.sync_config?.recursive ?? true) && !recursive && (
                          <p className="text-xs text-amber-600 dark:text-amber-400 mt-1 flex items-center gap-1">
                            <AlertTriangle className="w-3 h-3" />
                            Disabling will require deleting subfolder assets
                          </p>
                        )}
                      </div>
                      <button
                        onClick={() => setRecursive(!recursive)}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                          recursive
                            ? 'bg-indigo-600'
                            : 'bg-gray-300 dark:bg-gray-600'
                        }`}
                      >
                        <span
                          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            recursive ? 'translate-x-6' : 'translate-x-1'
                          }`}
                        />
                      </button>
                    </div>

                    {/* File Filters */}
                    <div>
                      <h4 className="text-sm font-medium text-gray-900 dark:text-white mb-3">
                        File Filters
                      </h4>
                      <div className="space-y-4">
                        <div>
                          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                            Include Patterns (comma-separated)
                          </label>
                          <input
                            type="text"
                            value={includePatterns}
                            onChange={e => setIncludePatterns(e.target.value)}
                            placeholder="e.g., *.pdf, *.docx, *.xlsx"
                            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                          />
                          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                            Leave empty to include all files. Only matching files will be synced.
                          </p>
                        </div>

                        <div>
                          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                            Exclude Patterns (comma-separated)
                          </label>
                          <input
                            type="text"
                            value={excludePatterns}
                            onChange={e => setExcludePatterns(e.target.value)}
                            placeholder="e.g., ~$*, *.tmp, .DS_Store"
                            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                          />
                          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                            Files matching these patterns will be skipped during sync.
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* Folder Browser with Selection - Only shown in 'selected' mode */}
                    {syncMode === 'selected' && (
                    <div>
                      <div className="flex items-center justify-between mb-3">
                        <h4 className="text-sm font-medium text-gray-900 dark:text-white">
                          Select Files & Folders to Sync
                        </h4>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={loadFolderContents}
                          disabled={isLoadingFolders}
                          className="gap-1.5"
                        >
                          <RefreshCw className={`w-3.5 h-3.5 ${isLoadingFolders ? 'animate-spin' : ''}`} />
                          Refresh
                        </Button>
                      </div>

                      {folderError ? (
                        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 text-center">
                          <AlertCircle className="w-6 h-6 text-red-500 mx-auto mb-2" />
                          <p className="text-sm text-red-700 dark:text-red-300">{folderError}</p>
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={loadFolderContents}
                            className="mt-3"
                          >
                            Try Again
                          </Button>
                        </div>
                      ) : isLoadingFolders ? (
                        <div className="flex items-center justify-center py-8 border border-gray-200 dark:border-gray-700 rounded-lg">
                          <Loader2 className="w-6 h-6 animate-spin text-indigo-600" />
                          <span className="ml-2 text-sm text-gray-500">Loading folder contents...</span>
                        </div>
                      ) : browseItems.length === 0 ? (
                        <div className="text-center py-8 border border-gray-200 dark:border-gray-700 rounded-lg">
                          <Folder className="w-10 h-10 text-gray-300 dark:text-gray-600 mx-auto mb-3" />
                          <p className="text-sm text-gray-500 dark:text-gray-400">
                            No files found in this folder
                          </p>
                        </div>
                      ) : (
                        <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                          {/* Selection Controls */}
                          <div className="flex items-center justify-between px-4 py-2 bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700">
                            <div className="flex items-center gap-2">
                              <Button variant="ghost" size="sm" onClick={selectAllItems}>
                                Select All
                              </Button>
                              <Button variant="ghost" size="sm" onClick={selectAllFiles}>
                                Files Only
                              </Button>
                              <Button variant="ghost" size="sm" onClick={clearSelection}>
                                Clear
                              </Button>
                            </div>
                            <span className="text-sm text-gray-500 dark:text-gray-400">
                              {selectedItems.size} of {browseItems.length} selected
                            </span>
                          </div>

                          {/* Item List */}
                          <div className="max-h-64 overflow-y-auto divide-y divide-gray-100 dark:divide-gray-700">
                            {browseItems.map((item) => {
                              const isSelected = selectedItems.has(item.id)
                              const isSynced = syncedItemIds.has(item.id)

                              return (
                                <button
                                  key={item.id}
                                  onClick={() => toggleItemSelection(item.id)}
                                  className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-gray-50 dark:hover:bg-gray-750 cursor-pointer"
                                >
                                  {/* Checkbox */}
                                  <div className="flex-shrink-0">
                                    {isSelected ? (
                                      <CheckSquare className="w-5 h-5 text-indigo-600" />
                                    ) : (
                                      <Square className="w-5 h-5 text-gray-400" />
                                    )}
                                  </div>

                                  {/* File/Folder Icon and Name */}
                                  <div className="flex items-center gap-2 min-w-0 flex-1">
                                    {item.type === 'folder' ? (
                                      <Folder className="w-4 h-4 text-amber-500 flex-shrink-0" />
                                    ) : (
                                      <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
                                    )}
                                    <span className="text-sm text-gray-900 dark:text-white truncate">
                                      {item.name}
                                    </span>
                                  </div>

                                  {/* Status & Size */}
                                  <div className="flex items-center gap-2 flex-shrink-0">
                                    {item.size && (
                                      <span className="text-xs text-gray-500 dark:text-gray-400">
                                        {(item.size / 1024).toFixed(1)} KB
                                      </span>
                                    )}
                                    {isSynced && (
                                      <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">
                                        Synced
                                      </span>
                                    )}
                                    {item.type === 'folder' && (
                                      <span className="text-xs text-amber-600 dark:text-amber-400">
                                        Folder
                                      </span>
                                    )}
                                  </div>
                                </button>
                              )
                            })}
                          </div>

                          {/* Footer with summary */}
                          <div className="px-4 py-2 bg-gray-50 dark:bg-gray-900/50 border-t border-gray-200 dark:border-gray-700">
                            <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                              <span>
                                {browseItems.length} items in folder
                                {recursive && ' (subfolders will also be synced)'}
                              </span>
                              {(() => {
                                const { newlySelected, newlyDeselected } = getSelectionChanges()
                                if (newlySelected.length > 0 || newlyDeselected.length > 0) {
                                  return (
                                    <span className="text-indigo-600 dark:text-indigo-400">
                                      {newlySelected.length > 0 && `+${newlySelected.length} to add`}
                                      {newlySelected.length > 0 && newlyDeselected.length > 0 && ', '}
                                      {newlyDeselected.length > 0 && `${newlyDeselected.length} to remove`}
                                    </span>
                                  )
                                }
                                return null
                              })()}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                    )}
                  </div>
                )}

                {/* Breaking Changes Warning */}
                {currentBreakingChanges.length > 0 && (
                  <div className="rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 p-3">
                    <div className="flex items-start gap-2">
                      <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
                      <div>
                        <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
                          Breaking changes detected
                        </p>
                        <ul className="mt-1 space-y-0.5">
                          {currentBreakingChanges.map((change, idx) => (
                            <li key={idx} className="text-xs text-amber-700 dark:text-amber-300">
                              • {change}
                            </li>
                          ))}
                        </ul>
                        <p className="text-xs text-amber-600 dark:text-amber-400 mt-2">
                          If there are existing synced assets, you&apos;ll be asked to confirm deletion.
                        </p>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Footer */}
              <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 rounded-b-2xl">
                <Button variant="secondary" onClick={onClose} disabled={isSaving}>
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  onClick={() => handleSave(false)}
                  disabled={isSaving || !hasChanges || !name.trim()}
                  className="gap-2"
                >
                  {isSaving ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Save className="w-4 h-4" />
                  )}
                  Save Changes
                </Button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// Format bytes to human readable
function formatBytes(bytes: number, decimals = 1): string {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(decimals)) + ' ' + sizes[i]
}

// Toast notification type
interface Toast {
  id: string
  type: 'success' | 'error' | 'info' | 'warning'
  message: string
}

// Run status from history
interface SyncRun {
  id: string
  status: string
  config: Record<string, any>
  progress: Record<string, any> | null
  results_summary: Record<string, any> | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export default function SharePointSyncConfigPage() {
  return (
    <ProtectedRoute>
      <SharePointSyncConfigContent />
    </ProtectedRoute>
  )
}

function SharePointSyncConfigContent() {
  const router = useRouter()
  const params = useParams()
  const configId = params.configId as string
  const { token } = useAuth()
  const { addJob } = useDeletionJobs()

  const [config, setConfig] = useState<SharePointSyncConfig | null>(null)
  const [documents, setDocuments] = useState<SharePointSyncedDocument[]>([])
  const [documentsTotal, setDocumentsTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [isSyncing, setIsSyncing] = useState(false)
  const [activeTab, setActiveTab] = useState<'documents' | 'deleted' | 'history'>('documents')
  const [syncHistory, setSyncHistory] = useState<SyncRun[]>([])
  const [toasts, setToasts] = useState<Toast[]>([])
  const [currentRun, setCurrentRun] = useState<SyncRun | null>(null)
  const [showEditModal, setShowEditModal] = useState(false)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)

  // Toast helper functions
  const addToast = useCallback((type: Toast['type'], message: string) => {
    const id = Date.now().toString()
    setToasts(prev => [...prev, { id, type, message }])
    // Auto-remove after 6 seconds
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, 6000)
  }, [])

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
      }
    }
  }, [])

  const loadConfig = useCallback(async () => {
    if (!token || !configId) return

    try {
      const configData = await sharepointSyncApi.getConfig(token, configId)
      setConfig(configData)

      // Check if currently syncing
      if (configData.is_syncing) {
        setIsSyncing(true)
        startPolling()
      } else {
        setIsSyncing(false)
        stopPolling()
      }

      return configData
    } catch (err: any) {
      setError(err.message || 'Failed to load sync configuration')
      return null
    }
  }, [token, configId])

  const loadDocuments = useCallback(async (syncStatus?: string) => {
    if (!token || !configId) return

    try {
      const response = await sharepointSyncApi.listDocuments(token, configId, {
        sync_status: syncStatus,
        limit: 100,
      })
      setDocuments(response.documents)
      setDocumentsTotal(response.total)
    } catch (err: any) {
      console.error('Failed to load documents:', err)
    }
  }, [token, configId])

  const loadHistory = useCallback(async () => {
    if (!token || !configId) return

    try {
      const response = await sharepointSyncApi.getHistory(token, configId, { limit: 20 })
      setSyncHistory(response.runs)

      // Find current running/pending run
      const activeRun = response.runs.find(r => r.status === 'running' || r.status === 'pending')
      if (activeRun) {
        setCurrentRun(activeRun)
        setIsSyncing(true)
        startPolling()
      } else {
        setCurrentRun(null)
      }

      return response.runs
    } catch (err: any) {
      console.error('Failed to load history:', err)
      return []
    }
  }, [token, configId])

  const startPolling = useCallback(() => {
    // Clear any existing polling
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
    }

    // Poll every 3 seconds
    pollIntervalRef.current = setInterval(async () => {
      if (!token || !configId) return

      try {
        // Fetch latest config and history
        const [configData, historyResponse] = await Promise.all([
          sharepointSyncApi.getConfig(token, configId),
          sharepointSyncApi.getHistory(token, configId, { limit: 5 }),
        ])

        setConfig(configData)

        // Find the most recent run
        const latestRun = historyResponse.runs[0]
        if (latestRun) {
          setCurrentRun(latestRun)

          // Check if completed or failed
          if (latestRun.status === 'completed' || latestRun.status === 'failed') {
            setIsSyncing(false)
            stopPolling()

            // Refresh all data
            await loadDocuments(activeTab === 'deleted' ? 'deleted_in_source' : 'synced')
            setSyncHistory(historyResponse.runs)

            // Show completion toast
            if (latestRun.status === 'completed') {
              const summary = latestRun.results_summary
              if (summary) {
                const newFiles = summary.new_files || 0
                const updated = summary.updated_files || 0
                const failed = summary.failed_files || 0

                if (failed > 0) {
                  addToast('warning', `Sync completed with errors: ${newFiles} new, ${updated} updated, ${failed} failed`)
                } else {
                  addToast('success', `Sync completed: ${newFiles} new, ${updated} updated files`)
                }
              } else {
                addToast('success', 'Sync completed successfully')
              }
            } else {
              addToast('error', `Sync failed: ${latestRun.error_message || 'Unknown error'}`)
            }
          }
        }

        // Also check config.is_syncing
        if (!configData.is_syncing) {
          setIsSyncing(false)
          stopPolling()
        }
      } catch (err) {
        console.error('Failed to poll status:', err)
      }
    }, 3000)
  }, [token, configId, activeTab, addToast, loadDocuments])

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
  }, [])

  // Initial load
  useEffect(() => {
    if (token && configId) {
      setIsLoading(true)
      Promise.all([
        loadConfig(),
        loadDocuments(),
        loadHistory(),
      ]).finally(() => setIsLoading(false))
    }
  }, [token, configId])

  // Load documents based on active tab
  useEffect(() => {
    if (activeTab === 'documents') {
      loadDocuments('synced')
    } else if (activeTab === 'deleted') {
      loadDocuments('deleted_in_source')
    }
  }, [activeTab, loadDocuments])

  // Check for active sync on config load
  useEffect(() => {
    if (config?.is_syncing) {
      setIsSyncing(true)
      startPolling()
    }
  }, [config?.is_syncing, startPolling])

  // Redirect if config is being deleted
  useEffect(() => {
    if (config?.status === 'deleting') {
      router.push('/sharepoint-sync')
    }
  }, [config?.status, router])

  const handleSync = async (fullSync: boolean = false) => {
    if (!token || !configId || isSyncing) return

    setIsSyncing(true)
    addToast('info', fullSync ? 'Starting full sync...' : 'Starting sync...')

    try {
      const result = await sharepointSyncApi.triggerSync(token, configId, fullSync)

      // Start polling for status
      startPolling()

      // Refresh history to show new run
      await loadHistory()
    } catch (err: any) {
      addToast('error', `Failed to start sync: ${err.message}`)
      setIsSyncing(false)
    }
  }

  const handleCancelStuck = async () => {
    if (!token || !configId) return

    if (!confirm('This will cancel any pending or running sync jobs. Continue?')) {
      return
    }

    try {
      const result = await sharepointSyncApi.cancelStuckRuns(token, configId)
      addToast('success', result.message)
      setIsSyncing(false)
      await loadConfig()
      await loadHistory()
    } catch (err: any) {
      addToast('error', `Failed to cancel stuck runs: ${err.message}`)
    }
  }

  const handleCleanup = async (deleteAssets: boolean = false) => {
    if (!token || !configId) return

    if (!confirm(
      deleteAssets
        ? 'This will remove deleted document records AND soft-delete the associated assets. Continue?'
        : 'This will remove deleted document records. The assets will remain. Continue?'
    )) {
      return
    }

    try {
      const result = await sharepointSyncApi.cleanupDeleted(token, configId, deleteAssets)
      addToast('success', result.message)
      loadDocuments('deleted_in_source')
      loadConfig()
    } catch (err: any) {
      addToast('error', `Failed to cleanup: ${err.message}`)
    }
  }

  const handleToggleActive = async () => {
    if (!token || !configId || !config) return

    const newState = !config.is_active

    try {
      await sharepointSyncApi.updateConfig(token, configId, { is_active: newState })
      addToast('success', `Sync ${newState ? 'enabled' : 'disabled'}`)
      loadConfig()
    } catch (err: any) {
      addToast('error', `Failed to ${newState ? 'enable' : 'disable'} sync: ${err.message}`)
    }
  }

  const handleArchive = async () => {
    if (!token || !configId || !config) return

    if (config.is_active) {
      addToast('warning', 'Disable sync first before archiving')
      return
    }

    const docCount = config.stats?.synced_files || config.stats?.storage?.synced_count || 0

    if (!confirm(
      `Archive this sync configuration?\n\n` +
      `This will:\n` +
      `- Remove ${docCount} documents from the search index\n` +
      `- Stop all syncing\n` +
      `- Keep all assets intact\n\n` +
      `After archiving, you can permanently delete this configuration.`
    )) {
      return
    }

    try {
      const result = await sharepointSyncApi.archiveConfig(token, configId)
      addToast('success', `Archived: ${result.archive_stats.opensearch_removed} documents removed from search`)
      loadConfig()
    } catch (err: any) {
      addToast('error', `Failed to archive: ${err.message}`)
    }
  }

  const handleDelete = async () => {
    if (!token || !configId || !config) return

    // Must be archived to delete
    if (config.status !== 'archived') {
      addToast('warning', 'Archive the sync configuration first before deleting')
      return
    }

    // Show confirmation dialog
    setShowDeleteDialog(true)
  }

  const confirmDelete = async () => {
    if (!token || !configId || !config) return

    try {
      const response = await sharepointSyncApi.deleteConfig(token, configId)

      // Add to global deletion tracking
      addJob({
        runId: response.run_id,
        configId: configId,
        configName: config.name,
        configType: 'sharepoint',
      })

      // Close dialog
      setShowDeleteDialog(false)

      // Show immediate feedback
      toast.success('Deletion started...')

      // Redirect to list page
      router.push('/sharepoint-sync')
    } catch (err: any) {
      if (err?.status === 409) {
        addToast('warning', 'Deletion is already in progress')
        setShowDeleteDialog(false)
        router.push('/sharepoint-sync')
      } else {
        addToast('error', `Failed to delete: ${err.message}`)
      }
    }
  }

  const handleSaveConfig = async (
    updates: Record<string, any>,
    resetAssets: boolean
  ): Promise<{ success: boolean; error?: string }> => {
    if (!token || !configId) {
      return { success: false, error: 'Not authenticated' }
    }

    try {
      await sharepointSyncApi.updateConfig(token, configId, {
        ...updates,
        reset_existing_assets: resetAssets,
      })

      addToast('success', 'Configuration updated successfully')

      // Reload config and documents
      await loadConfig()
      await loadDocuments(activeTab === 'deleted' ? 'deleted_in_source' : 'synced')

      return { success: true }
    } catch (err: any) {
      // Check if it's a structured error response
      const detail = err.detail
      if (detail && typeof detail === 'object' && detail.breaking_changes) {
        return { success: false, error: JSON.stringify(detail) }
      }
      return { success: false, error: err.message || 'Failed to update configuration' }
    }
  }

  const handleImportFiles = async (items: SharePointBrowseItem[]) => {
    if (!token || !configId || !config || items.length === 0) return

    try {
      const itemsToImport = items.map(item => ({
        id: item.id,
        name: item.name,
        type: item.type,
        folder: item.folder || '',
        drive_id: item.drive_id || config.folder_drive_id || undefined,
        size: item.size,
        web_url: item.web_url,
        mime: item.mime_type,
      }))

      await sharepointSyncApi.importFiles(token, {
        connection_id: config.connection_id || undefined,
        folder_url: config.folder_url,
        selected_items: itemsToImport,
        sync_config_id: config.id, // Link to existing sync config
        create_sync_config: false, // Don't create new config, use existing
      })

      addToast('success', `Started importing ${items.length} ${items.length === 1 ? 'item' : 'items'}`)

      // Reload config and documents after a short delay
      setTimeout(async () => {
        await loadConfig()
        await loadDocuments('synced')
      }, 1000)
    } catch (err: any) {
      addToast('error', `Failed to import files: ${err.message}`)
    }
  }

  const handleRemoveItems = async (itemIds: string[]) => {
    if (!token || !configId || itemIds.length === 0) return

    try {
      const result = await sharepointSyncApi.removeItems(token, configId, itemIds, true)

      addToast(
        'success',
        `Removed ${result.documents_removed} ${result.documents_removed === 1 ? 'item' : 'items'}${
          result.assets_deleted > 0 ? ` and ${result.assets_deleted} ${result.assets_deleted === 1 ? 'asset' : 'assets'}` : ''
        }`
      )

      // Reload config and documents
      await loadConfig()
      await loadDocuments('synced')
    } catch (err: any) {
      addToast('error', `Failed to remove items: ${err.message}`)
      throw err // Re-throw so EditModal knows the operation failed
    }
  }

  // Use formatDateTime from date-utils for consistent EST display
  const formatDate = (dateStr: string | null) => formatDateTime(dateStr)

  const getStatusBadge = () => {
    if (!config) return null

    if (config.is_syncing || isSyncing) {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
          <Loader2 className="w-4 h-4 animate-spin" />
          Syncing
        </span>
      )
    }

    if (config.status === 'archived') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">
          <Archive className="w-4 h-4" />
          Archived
        </span>
      )
    }

    if (config.status === 'paused' || !config.is_active) {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
          <Pause className="w-4 h-4" />
          Paused
        </span>
      )
    }

    if (config.last_sync_status === 'failed') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
          <XCircle className="w-4 h-4" />
          Last Sync Failed
        </span>
      )
    }

    if (config.last_sync_status === 'success') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
          <CheckCircle2 className="w-4 h-4" />
          Synced
        </span>
      )
    }

    if (config.last_sync_status === 'partial') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
          <AlertTriangle className="w-4 h-4" />
          Partial Sync
        </span>
      )
    }

    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">
        <Clock className="w-4 h-4" />
        Pending
      </span>
    )
  }

  // Get last sync errors from history
  const getLastSyncErrors = (): string[] => {
    const lastRun = syncHistory[0]
    if (!lastRun?.results_summary?.errors) return []
    return lastRun.results_summary.errors.slice(0, 5).map((e: any) =>
      `${e.file}: ${e.error}`
    )
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950 flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin mx-auto" />
          <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading...</p>
        </div>
      </div>
    )
  }

  if (error || !config) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-6 text-center">
            <AlertTriangle className="w-12 h-12 text-red-500 mx-auto mb-4" />
            <h2 className="text-lg font-semibold text-red-800 dark:text-red-200 mb-2">
              {error || 'Configuration not found'}
            </h2>
            <Link href="/sharepoint-sync">
              <Button variant="secondary" className="gap-2">
                <ArrowLeft className="w-4 h-4" />
                Back to Sync Configs
              </Button>
            </Link>
          </div>
        </div>
      </div>
    )
  }

  const lastErrors = getLastSyncErrors()

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      {/* Toast Notifications */}
      <div className="fixed top-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg max-w-sm animate-slide-in ${
              toast.type === 'success'
                ? 'bg-emerald-500 text-white'
                : toast.type === 'error'
                ? 'bg-red-500 text-white'
                : toast.type === 'warning'
                ? 'bg-amber-500 text-white'
                : 'bg-blue-500 text-white'
            }`}
          >
            {toast.type === 'success' && <CheckCircle2 className="w-5 h-5 flex-shrink-0" />}
            {toast.type === 'error' && <XCircle className="w-5 h-5 flex-shrink-0" />}
            {toast.type === 'warning' && <AlertTriangle className="w-5 h-5 flex-shrink-0" />}
            {toast.type === 'info' && <Info className="w-5 h-5 flex-shrink-0" />}
            <p className="text-sm font-medium flex-1">{toast.message}</p>
            <button
              onClick={() => removeToast(toast.id)}
              className="p-1 hover:bg-white/20 rounded transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-6">
          <Link
            href="/sharepoint-sync"
            className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 mb-4"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Sync Configs
          </Link>

          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="flex items-start gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25 flex-shrink-0">
                <Folder className="w-6 h-6" />
              </div>
              <div>
                <div className="flex items-center gap-3 flex-wrap">
                  <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                    {config.name}
                  </h1>
                  {getStatusBadge()}
                </div>
                {config.description && (
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                    {config.description}
                  </p>
                )}
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-2 break-all">
                  {config.folder_url}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3 flex-shrink-0">
              {/* Edit Button - only when not archived */}
              {config.status !== 'archived' && (
                <Button
                  variant="secondary"
                  onClick={() => setShowEditModal(true)}
                  disabled={isSyncing}
                  className="gap-2"
                  title="Edit configuration"
                >
                  <Edit3 className="w-4 h-4" />
                  Edit
                </Button>
              )}

              {/* Sync Toggle - only when status is active */}
              {config.status === 'active' && (
                <button
                  onClick={handleToggleActive}
                  disabled={isSyncing}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-colors ${
                    config.is_active
                      ? 'bg-emerald-50 border-emerald-200 text-emerald-700 dark:bg-emerald-900/20 dark:border-emerald-800 dark:text-emerald-400'
                      : 'bg-gray-50 border-gray-200 text-gray-500 dark:bg-gray-800 dark:border-gray-700 dark:text-gray-400'
                  } ${isSyncing ? 'opacity-50 cursor-not-allowed' : 'hover:opacity-80'}`}
                  title={config.is_active ? 'Disable sync' : 'Enable sync'}
                >
                  {config.is_active ? (
                    <ToggleRight className="w-5 h-5" />
                  ) : (
                    <ToggleLeft className="w-5 h-5" />
                  )}
                  <span className="text-sm font-medium">
                    {config.is_active ? 'Enabled' : 'Disabled'}
                  </span>
                </button>
              )}

              {/* Sync Buttons - only when active and enabled */}
              {config.status === 'active' && config.is_active && (
                <>
                  <Button
                    variant="primary"
                    onClick={() => handleSync(false)}
                    disabled={isSyncing}
                    className="gap-2"
                  >
                    {isSyncing ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Play className="w-4 h-4" />
                    )}
                    {isSyncing ? 'Syncing...' : 'Sync Now'}
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => handleSync(true)}
                    disabled={isSyncing}
                    className="gap-2"
                  >
                    <RefreshCw className={`w-4 h-4 ${isSyncing ? 'animate-spin' : ''}`} />
                    Full Sync
                  </Button>
                  {isSyncing && (
                    <Button
                      variant="ghost"
                      onClick={handleCancelStuck}
                      className="gap-2 text-red-600 hover:text-red-700 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-900/20"
                      title="Cancel any stuck or pending sync jobs"
                    >
                      <XCircle className="w-4 h-4" />
                      Cancel Stuck
                    </Button>
                  )}
                </>
              )}

              {/* Archive Button - only when disabled but not yet archived */}
              {config.status === 'active' && !config.is_active && (
                <Button
                  variant="secondary"
                  onClick={handleArchive}
                  disabled={isSyncing}
                  className="gap-2"
                  title="Archive this sync configuration"
                >
                  <Archive className="w-4 h-4" />
                  Archive
                </Button>
              )}

              {/* Delete Button - only when archived */}
              {config.status === 'archived' && (
                <Button
                  variant="ghost"
                  onClick={handleDelete}
                  className="gap-2 text-red-600 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-900/20"
                  title="Permanently delete sync configuration and all assets"
                >
                  <Trash2 className="w-4 h-4" />
                  Delete
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* Archived Info Banner */}
        {config.status === 'archived' && (
          <div className="mb-6 rounded-xl bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center">
                  <Archive className="w-5 h-5 text-gray-500 dark:text-gray-400" />
                </div>
              </div>
              <div className="flex-1">
                <p className="text-sm font-medium text-gray-800 dark:text-gray-200">
                  This sync configuration is archived
                </p>
                <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                  Syncing is stopped and documents have been removed from the search index.
                  Assets ({config.stats?.synced_files || config.stats?.storage?.synced_count || 0} files) are still accessible but won't appear in search results.
                </p>
                <p className="text-xs text-gray-600 dark:text-gray-400 mt-2">
                  To permanently delete all assets and free up storage, click the <strong>Delete</strong> button above.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Disabled Info Banner */}
        {config.status === 'active' && !config.is_active && (
          <div className="mb-6 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 p-4">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 rounded-full bg-amber-100 dark:bg-amber-800 flex items-center justify-center">
                  <Pause className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                </div>
              </div>
              <div className="flex-1">
                <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
                  Sync is disabled
                </p>
                <p className="text-xs text-amber-700 dark:text-amber-400 mt-1">
                  No new files will be synced from SharePoint. Enable sync to resume, or archive if you want to delete this configuration.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Sync Progress Banner */}
        {isSyncing && currentRun && (
          <div className="mb-6 rounded-xl bg-blue-50 dark:bg-blue-900/20 border border-blue-100 dark:border-blue-800 p-4">
            <div className="flex items-center gap-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 rounded-full bg-blue-100 dark:bg-blue-800 flex items-center justify-center">
                  <Loader2 className="w-5 h-5 text-blue-600 dark:text-blue-400 animate-spin" />
                </div>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-blue-800 dark:text-blue-200">
                  {currentRun.config?.full_sync ? 'Full sync' : 'Incremental sync'} in progress...
                </p>
                <p className="text-xs text-blue-600 dark:text-blue-400 mt-0.5">
                  Started {formatDate(currentRun.started_at || currentRun.created_at)}
                </p>
                {currentRun.progress && (
                  <p className="text-xs text-blue-600 dark:text-blue-400 mt-1">
                    {currentRun.progress.message || 'Processing files...'}
                  </p>
                )}
              </div>
              <Link
                href={`/admin/queue/${currentRun.id}`}
                className="flex-shrink-0 text-xs font-medium text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-200 underline"
              >
                View Job →
              </Link>
            </div>
          </div>
        )}

        {/* Error Banner for Last Sync */}
        {!isSyncing && lastErrors.length > 0 && (
          <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-800 p-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-red-800 dark:text-red-200">
                  Last sync completed with {lastErrors.length} error{lastErrors.length > 1 ? 's' : ''}
                </p>
                <ul className="mt-2 space-y-1">
                  {lastErrors.map((err, idx) => (
                    <li key={idx} className="text-xs text-red-600 dark:text-red-400 truncate">
                      {err}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        )}

        {/* Stats Cards - Show live progress during sync */}
        {isSyncing && config.stats?.phase === 'syncing' && config.stats?.total_files > 0 ? (
          <div className="mb-6">
            {/* Live Sync Progress */}
            <div className="bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-xl border border-indigo-200 dark:border-indigo-700 p-6">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-indigo-100 dark:bg-indigo-800 flex items-center justify-center">
                    <Loader2 className="w-5 h-5 text-indigo-600 dark:text-indigo-400 animate-spin" />
                  </div>
                  <div>
                    <p className="text-lg font-semibold text-gray-900 dark:text-white">
                      Syncing Files...
                    </p>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {config.stats?.processed_files || 0} of {config.stats?.total_files || 0} files processed
                    </p>
                  </div>
                </div>
                <div className="text-right flex flex-col items-end gap-1">
                  <p className="text-2xl font-bold text-indigo-600 dark:text-indigo-400">
                    {config.stats?.total_files > 0
                      ? Math.round(((config.stats?.processed_files || 0) / config.stats?.total_files) * 100)
                      : 0}%
                  </p>
                  {currentRun && (
                    <Link
                      href={`/admin/queue/${currentRun.id}`}
                      className="text-xs font-medium text-indigo-600 hover:text-indigo-800 dark:text-indigo-400 dark:hover:text-indigo-200 underline"
                    >
                      View Job →
                    </Link>
                  )}
                </div>
              </div>

              {/* Progress Bar */}
              <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-3 mb-4">
                <div
                  className="bg-gradient-to-r from-indigo-500 to-purple-500 h-3 rounded-full transition-all duration-500"
                  style={{
                    width: `${config.stats?.total_files > 0
                      ? ((config.stats?.processed_files || 0) / config.stats?.total_files) * 100
                      : 0}%`
                  }}
                />
              </div>

              {/* Current File */}
              {config.stats?.current_file && (
                <p className="text-sm text-gray-600 dark:text-gray-400 truncate mb-4">
                  Processing: <span className="font-medium">{config.stats.current_file}</span>
                </p>
              )}

              {/* Live Stats Grid */}
              <div className="grid grid-cols-4 gap-4">
                <div className="text-center p-3 bg-white/50 dark:bg-gray-800/50 rounded-lg">
                  <p className="text-xl font-bold text-emerald-600 dark:text-emerald-400">
                    {config.stats?.new_files || 0}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">New</p>
                </div>
                <div className="text-center p-3 bg-white/50 dark:bg-gray-800/50 rounded-lg">
                  <p className="text-xl font-bold text-blue-600 dark:text-blue-400">
                    {config.stats?.updated_files || 0}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Updated</p>
                </div>
                <div className="text-center p-3 bg-white/50 dark:bg-gray-800/50 rounded-lg">
                  <p className="text-xl font-bold text-gray-600 dark:text-gray-400">
                    {config.stats?.unchanged_files || 0}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Unchanged</p>
                </div>
                <div className="text-center p-3 bg-white/50 dark:bg-gray-800/50 rounded-lg">
                  <p className="text-xl font-bold text-red-600 dark:text-red-400">
                    {config.stats?.failed_files || 0}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Failed</p>
                </div>
              </div>
            </div>
          </div>
        ) : isSyncing && config.stats?.phase === 'detecting_deletions' ? (
          <div className="mb-6">
            {/* Detecting Deletions Phase */}
            <div className="bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/20 rounded-xl border border-amber-200 dark:border-amber-700 p-6">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-amber-100 dark:bg-amber-800 flex items-center justify-center">
                  <Loader2 className="w-5 h-5 text-amber-600 dark:text-amber-400 animate-spin" />
                </div>
                <div>
                  <p className="text-lg font-semibold text-gray-900 dark:text-white">
                    Detecting Deleted Files...
                  </p>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    Checking for files removed from SharePoint
                  </p>
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* Standard Stats Cards (not syncing) */
          <div className="space-y-4 mb-6">
            {/* Main Stats Row */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center">
                    <FileText className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                  </div>
                  <div>
                    <p className="text-2xl font-bold text-gray-900 dark:text-white">
                      {config.stats?.synced_files || config.stats?.storage?.synced_count || 0}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Synced Files</p>
                  </div>
                </div>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
                    <Trash2 className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                  </div>
                  <div>
                    <p className="text-2xl font-bold text-gray-900 dark:text-white">
                      {config.stats?.deleted_count || config.stats?.storage?.deleted_count || 0}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Deleted</p>
                  </div>
                </div>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-gray-100 dark:bg-gray-700 flex items-center justify-center">
                    <Clock className="w-5 h-5 text-gray-600 dark:text-gray-400" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-gray-900 dark:text-white capitalize">
                      {config.sync_frequency}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Frequency</p>
                  </div>
                </div>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-gray-100 dark:bg-gray-700 flex items-center justify-center">
                    <Calendar className="w-5 h-5 text-gray-600 dark:text-gray-400" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-gray-900 dark:text-white">
                      {config.last_sync_at ? formatDate(config.last_sync_at).split(',')[0] : 'Never'}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Last Sync</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Storage Impact Card */}
            {config.stats?.storage && (
              <div className="bg-gradient-to-r from-blue-50 to-cyan-50 dark:from-blue-900/20 dark:to-cyan-900/20 rounded-xl border border-blue-200 dark:border-blue-800 p-4">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-8 h-8 rounded-lg bg-blue-100 dark:bg-blue-800 flex items-center justify-center">
                    <HardDrive className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                  </div>
                  <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Storage Impact</h4>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  <div>
                    <p className="text-xl font-bold text-gray-900 dark:text-white">
                      {formatBytes(config.stats.storage.total_bytes || 0)}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Total Storage Used</p>
                  </div>
                  <div>
                    <p className="text-xl font-bold text-gray-900 dark:text-white">
                      {config.stats.storage.total_documents || 0}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Total Documents</p>
                  </div>
                  <div>
                    <p className="text-xl font-bold text-gray-900 dark:text-white">
                      {config.stats.storage.total_documents > 0
                        ? formatBytes((config.stats.storage.total_bytes || 0) / config.stats.storage.total_documents)
                        : '0 B'}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Avg File Size</p>
                  </div>
                  <div>
                    <p className="text-xl font-bold text-emerald-600 dark:text-emerald-400">
                      {config.stats.storage.synced_count || 0}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Active / Synced</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tabs */}
        <div className="border-b border-gray-200 dark:border-gray-700 mb-6">
          <div className="flex gap-6">
            <button
              onClick={() => setActiveTab('documents')}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'documents'
                  ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                  : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4" />
                Documents
                {documentsTotal > 0 && activeTab !== 'documents' && (
                  <span className="px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400">
                    {documentsTotal}
                  </span>
                )}
              </div>
            </button>
            <button
              onClick={() => setActiveTab('deleted')}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'deleted'
                  ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                  : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <Trash2 className="w-4 h-4" />
                Deleted
                {(config.stats?.deleted_count || 0) > 0 && (
                  <span className="px-2 py-0.5 text-xs rounded-full bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                    {config.stats?.deleted_count}
                  </span>
                )}
              </div>
            </button>
            <button
              onClick={() => { setActiveTab('history'); loadHistory(); }}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'history'
                  ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                  : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <History className="w-4 h-4" />
                History
              </div>
            </button>
          </div>
        </div>

        {/* Tab Content */}
        {activeTab === 'documents' && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            {documents.length === 0 ? (
              <div className="p-12 text-center">
                <FileText className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                  No synced documents yet
                </h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 max-w-md mx-auto mb-4">
                  Run a sync to import documents from SharePoint.
                </p>
                {config.status === 'active' && config.is_active && !isSyncing && (
                  <Button
                    variant="primary"
                    onClick={() => handleSync(false)}
                    className="gap-2"
                  >
                    <Play className="w-4 h-4" />
                    Start First Sync
                  </Button>
                )}
              </div>
            ) : (
              <div className="divide-y divide-gray-100 dark:divide-gray-700">
                {documents.map((doc) => (
                  <div key={doc.id} className="px-5 py-4 hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors">
                    <div className="flex items-center justify-between gap-4">
                      <div className="flex items-center gap-3 min-w-0">
                        <FileText className="w-5 h-5 text-gray-400 flex-shrink-0" />
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                            {doc.original_filename || 'Unknown'}
                          </p>
                          {doc.sharepoint_path && (
                            <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                              {doc.sharepoint_path}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-4 flex-shrink-0">
                        {doc.file_size && (
                          <span className="text-xs text-gray-500 dark:text-gray-400">
                            {(doc.file_size / 1024).toFixed(1)} KB
                          </span>
                        )}
                        <span className="text-xs text-gray-400 dark:text-gray-500">
                          {formatDate(doc.last_synced_at)}
                        </span>
                        {doc.sharepoint_web_url && (
                          <a
                            href={doc.sharepoint_web_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-indigo-600 hover:text-indigo-700 dark:text-indigo-400"
                          >
                            <ExternalLink className="w-4 h-4" />
                          </a>
                        )}
                        <Link href={`/assets/${doc.asset_id}`}>
                          <Button variant="ghost" size="sm">
                            View Asset
                          </Button>
                        </Link>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'deleted' && (
          <div>
            {documents.length > 0 && (
              <div className="mb-4 flex items-center justify-between">
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  {documents.length} files have been deleted in SharePoint
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleCleanup(false)}
                    className="gap-2"
                  >
                    <Trash2 className="w-4 h-4" />
                    Remove Records
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleCleanup(true)}
                    className="gap-2 text-red-600 hover:text-red-700"
                  >
                    <Trash2 className="w-4 h-4" />
                    Remove + Delete Assets
                  </Button>
                </div>
              </div>
            )}

            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              {documents.length === 0 ? (
                <div className="p-12 text-center">
                  <CheckCircle2 className="w-12 h-12 text-emerald-500 mx-auto mb-4" />
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                    No deleted files
                  </h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    All synced files are still present in SharePoint.
                  </p>
                </div>
              ) : (
                <div className="divide-y divide-gray-100 dark:divide-gray-700">
                  {documents.map((doc) => (
                    <div key={doc.id} className="px-5 py-4 bg-red-50/50 dark:bg-red-900/10">
                      <div className="flex items-center justify-between gap-4">
                        <div className="flex items-center gap-3 min-w-0">
                          <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" />
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                              {doc.original_filename || 'Unknown'}
                            </p>
                            {doc.sharepoint_path && (
                              <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                                {doc.sharepoint_path}
                              </p>
                            )}
                          </div>
                        </div>
                        <div className="text-xs text-red-600 dark:text-red-400">
                          Deleted {formatDate(doc.deleted_detected_at)}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'history' && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            {syncHistory.length === 0 ? (
              <div className="p-12 text-center">
                <History className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                  No sync history yet
                </h3>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Run a sync to see history here.
                </p>
              </div>
            ) : (
              <div className="divide-y divide-gray-100 dark:divide-gray-700">
                {syncHistory.map((run) => (
                  <div key={run.id} className="px-5 py-4">
                    <div className="flex items-center justify-between gap-4">
                      <div className="flex items-center gap-3">
                        {run.status === 'completed' ? (
                          <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                        ) : run.status === 'failed' ? (
                          <XCircle className="w-5 h-5 text-red-500" />
                        ) : run.status === 'running' || run.status === 'pending' ? (
                          <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
                        ) : (
                          <Clock className="w-5 h-5 text-gray-400" />
                        )}
                        <div>
                          <p className="text-sm font-medium text-gray-900 dark:text-white">
                            {run.config?.full_sync ? 'Full Sync' : 'Incremental Sync'}
                          </p>
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            {formatDate(run.created_at)}
                            {run.completed_at && ` • ${formatDuration(run.started_at || run.created_at, run.completed_at)}`}
                          </p>
                        </div>
                      </div>
                      <div className="text-right">
                        {run.status === 'running' || run.status === 'pending' ? (
                          <span className="text-sm text-blue-600 dark:text-blue-400">
                            In progress...
                          </span>
                        ) : run.results_summary ? (
                          <div>
                            <p className="text-sm text-gray-600 dark:text-gray-300">
                              {run.results_summary.new_files || 0} new,{' '}
                              {run.results_summary.updated_files || 0} updated
                              {(run.results_summary.failed_files || 0) > 0 && (
                                <span className="text-red-600 dark:text-red-400">
                                  , {run.results_summary.failed_files} failed
                                </span>
                              )}
                            </p>
                            {run.results_summary.deleted_detected > 0 && (
                              <p className="text-xs text-amber-600 dark:text-amber-400">
                                {run.results_summary.deleted_detected} deleted detected
                              </p>
                            )}
                          </div>
                        ) : null}
                        {run.error_message && (
                          <p className="text-sm text-red-600 dark:text-red-400 truncate max-w-xs">
                            {run.error_message}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Edit Modal */}
      {config && (
        <EditModal
          config={config}
          token={token}
          isOpen={showEditModal}
          onClose={() => setShowEditModal(false)}
          onSave={handleSaveConfig}
          onImportFiles={handleImportFiles}
          onRemoveItems={handleRemoveItems}
        />
      )}

      {/* Delete Confirmation Dialog */}
      {config && (
        <ConfirmDeleteDialog
          isOpen={showDeleteDialog}
          onClose={() => setShowDeleteDialog(false)}
          onConfirm={confirmDelete}
          title="Delete Sync Configuration"
          itemName={config.name}
          description="This will permanently remove all synced files and their extracted content."
          warningItems={[
            `Delete ${config.stats?.synced_files || config.stats?.storage?.synced_count || 0} synced assets`,
            `Remove ${((config.stats?.storage?.total_bytes || 0) / (1024 * 1024)).toFixed(1)} MB from storage`,
            'Remove documents from search index',
            'Delete all sync history and runs',
          ]}
          confirmButtonText="Delete Forever"
        />
      )}

      {/* CSS for toast animation */}
      <style jsx>{`
        @keyframes slide-in {
          from {
            transform: translateX(100%);
            opacity: 0;
          }
          to {
            transform: translateX(0);
            opacity: 1;
          }
        }
        .animate-slide-in {
          animation: slide-in 0.3s ease-out;
        }
      `}</style>
    </div>
  )
}

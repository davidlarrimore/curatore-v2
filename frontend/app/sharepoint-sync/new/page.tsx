'use client'

import { useState, useCallback, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { sharepointSyncApi, connectionsApi, SharePointBrowseItem } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  FolderSync,
  ArrowLeft,
  ArrowRight,
  AlertTriangle,
  CheckCircle2,
  Folder,
  FileText,
  Loader2,
  Link2,
  Search,
  CheckSquare,
  Square,
  RefreshCw,
} from 'lucide-react'

interface Connection {
  id: string
  name: string
  connection_type: string
  is_active: boolean
}

type WizardStep = 'connection' | 'folder' | 'files' | 'config' | 'confirm'

export default function NewSharePointSyncPage() {
  return (
    <ProtectedRoute>
      <NewSharePointSyncContent />
    </ProtectedRoute>
  )
}

function NewSharePointSyncContent() {
  const router = useRouter()
  const { token } = useAuth()

  // Wizard state
  const [step, setStep] = useState<WizardStep>('connection')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  // Form data
  const [connections, setConnections] = useState<Connection[]>([])
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null)
  const [folderUrl, setFolderUrl] = useState('')
  const [syncMode, setSyncMode] = useState<'all' | 'selected'>('all')
  const [folderInfo, setFolderInfo] = useState<{
    name: string
    id: string
    drive_id: string
  } | null>(null)
  const [browseItems, setBrowseItems] = useState<SharePointBrowseItem[]>([])
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set())
  const [syncName, setSyncName] = useState('')
  const [syncDescription, setSyncDescription] = useState('')
  const [syncFrequency, setSyncFrequency] = useState('manual')
  const [recursive, setRecursive] = useState(true)
  const [includePatterns, setIncludePatterns] = useState('')
  const [excludePatterns, setExcludePatterns] = useState('~$*,*.tmp')

  // Load connections
  const loadConnections = useCallback(async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const response = await connectionsApi.listConnections(token)
      const spConnections = response.connections.filter(
        (c: Connection) => c.connection_type === 'sharepoint' && c.is_active
      )
      setConnections(spConnections)
    } catch (err: any) {
      setError(err.message || 'Failed to load connections')
    } finally {
      setIsLoading(false)
    }
  }, [token])

  // Load connections on mount
  useEffect(() => {
    if (token) {
      loadConnections()
    }
  }, [token, loadConnections])

  // Browse folder
  const handleBrowseFolder = async () => {
    if (!token || !folderUrl) return

    setIsLoading(true)
    setError('')

    try {
      const response = await sharepointSyncApi.browseFolder(token, {
        connection_id: selectedConnectionId || undefined,
        folder_url: folderUrl,
        recursive: false,
        include_folders: true,
      })

      setFolderInfo({
        name: response.folder_name,
        id: response.folder_id,
        drive_id: response.drive_id,
      })
      setBrowseItems(response.items)

      // Auto-suggest sync name from folder name
      if (!syncName && response.folder_name) {
        setSyncName(response.folder_name)
      }
    } catch (err: any) {
      setError(err.message || 'Failed to browse SharePoint folder')
    } finally {
      setIsLoading(false)
    }
  }

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

  // Track submission state separately to prevent double-clicks
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Create sync config and import
  const handleCreateSync = async () => {
    if (!token || isSubmitting) return

    // Immediately disable button to prevent double-clicks
    setIsSubmitting(true)
    setIsLoading(true)
    setError('')

    try {
      // Build sync config
      const syncConfig: Record<string, any> = {
        recursive,
        selection_mode: syncMode,
      }

      if (includePatterns) {
        syncConfig.include_patterns = includePatterns.split(',').map(p => p.trim()).filter(Boolean)
      }

      if (excludePatterns) {
        syncConfig.exclude_patterns = excludePatterns.split(',').map(p => p.trim()).filter(Boolean)
      }

      let syncConfigId: string | null = null

      // If files are selected (only possible in 'selected' mode), import them directly
      if (syncMode === 'selected' && selectedItems.size > 0) {
        const itemsToImport = browseItems
          .filter(i => selectedItems.has(i.id))
          .map(i => ({
            id: i.id,
            name: i.name,
            type: i.type,  // Required to distinguish folders from files
            folder: i.folder || '',
            drive_id: i.drive_id || folderInfo?.drive_id,
            size: i.size,
            web_url: i.web_url,
            mime: i.mime,
          }))

        const result = await sharepointSyncApi.importFiles(token, {
          connection_id: selectedConnectionId || undefined,
          folder_url: folderUrl,
          selected_items: itemsToImport,
          sync_config_name: syncName,
          sync_config_description: syncDescription,
          create_sync_config: true,
          sync_frequency: syncFrequency,
        })
        syncConfigId = result.sync_config_id
      } else {
        // Create sync config without initial import
        const result = await sharepointSyncApi.createConfig(token, {
          name: syncName,
          description: syncDescription,
          connection_id: selectedConnectionId || undefined,
          folder_url: folderUrl,
          sync_config: syncConfig,
          sync_frequency: syncFrequency,
        })
        syncConfigId = result.id
      }

      // Redirect to the sync detail page to watch the import progress
      if (syncConfigId) {
        router.push(`/sharepoint-sync/${syncConfigId}`)
      } else {
        router.push('/sharepoint-sync')
      }
    } catch (err: any) {
      setError(err.message || 'Failed to create sync configuration')
      setIsSubmitting(false)
      setIsLoading(false)
    }
    // Note: Don't reset isSubmitting on success - we're navigating away
  }

  // Step navigation
  const goBack = () => {
    switch (step) {
      case 'folder':
        setStep('connection')
        break
      case 'files':
        setStep('folder')
        break
      case 'config':
        setStep('files')
        break
      case 'confirm':
        setStep('config')
        break
    }
  }

  const goNext = () => {
    switch (step) {
      case 'connection':
        setStep('folder')
        break
      case 'folder':
        handleBrowseFolder()
        setStep('files')
        break
      case 'files':
        setStep('config')
        break
      case 'config':
        setStep('confirm')
        break
    }
  }

  const canProceed = () => {
    switch (step) {
      case 'connection':
        return true // Connection is optional
      case 'folder':
        return folderUrl.length > 0
      case 'files':
        return true // Selection is optional
      case 'config':
        return syncName.length > 0
      case 'confirm':
        return true
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <button
            onClick={() => router.back()}
            className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 mb-4"
          >
            <ArrowLeft className="w-4 h-4" />
            Back
          </button>
          <div className="flex items-center gap-4">
            <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25">
              <FolderSync className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                New SharePoint Sync
              </h1>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                Configure folder synchronization from SharePoint
              </p>
            </div>
          </div>
        </div>

        {/* Progress Steps */}
        <div className="mb-8">
          <div className="flex items-center justify-between">
            {['connection', 'folder', 'files', 'config', 'confirm'].map((s, idx) => (
              <div key={s} className="flex items-center">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                    step === s
                      ? 'bg-indigo-600 text-white'
                      : ['connection', 'folder', 'files', 'config', 'confirm'].indexOf(step) > idx
                      ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
                      : 'bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500'
                  }`}
                >
                  {['connection', 'folder', 'files', 'config', 'confirm'].indexOf(step) > idx ? (
                    <CheckCircle2 className="w-4 h-4" />
                  ) : (
                    idx + 1
                  )}
                </div>
                {idx < 4 && (
                  <div
                    className={`w-16 sm:w-24 h-1 mx-2 rounded ${
                      ['connection', 'folder', 'files', 'config', 'confirm'].indexOf(step) > idx
                        ? 'bg-emerald-400'
                        : 'bg-gray-200 dark:bg-gray-700'
                    }`}
                  />
                )}
              </div>
            ))}
          </div>
          <div className="flex justify-between mt-2 text-xs text-gray-500 dark:text-gray-400">
            <span>Connection</span>
            <span>Folder</span>
            <span>Files</span>
            <span>Config</span>
            <span>Confirm</span>
          </div>
        </div>

        {/* Error State */}
        {error && (
          <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
            <div className="flex items-center gap-3">
              <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
              <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
            </div>
          </div>
        )}

        {/* Step Content */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          {/* Step 1: Connection Selection */}
          {step === 'connection' && (
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                Select SharePoint Connection
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
                Choose an existing SharePoint connection or skip to use environment-based authentication.
              </p>

              {isLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-6 h-6 animate-spin text-indigo-600" />
                </div>
              ) : connections.length === 0 ? (
                <div className="text-center py-8">
                  <Link2 className="w-10 h-10 text-gray-300 dark:text-gray-600 mx-auto mb-3" />
                  <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                    No SharePoint connections found. You can continue with environment-based auth or create a connection first.
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  <button
                    onClick={() => setSelectedConnectionId(null)}
                    className={`w-full p-4 rounded-lg border text-left transition-colors ${
                      selectedConnectionId === null
                        ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                        : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-gray-100 dark:bg-gray-700 flex items-center justify-center">
                        <Link2 className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                      </div>
                      <div>
                        <p className="font-medium text-gray-900 dark:text-white">Use Environment Auth</p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          Use configured environment variables
                        </p>
                      </div>
                    </div>
                  </button>
                  {connections.map((conn) => (
                    <button
                      key={conn.id}
                      onClick={() => setSelectedConnectionId(conn.id)}
                      className={`w-full p-4 rounded-lg border text-left transition-colors ${
                        selectedConnectionId === conn.id
                          ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                          : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center">
                          <Link2 className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                        </div>
                        <div>
                          <p className="font-medium text-gray-900 dark:text-white">{conn.name}</p>
                          <p className="text-xs text-gray-500 dark:text-gray-400">SharePoint Connection</p>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Step 2: Folder URL */}
          {step === 'folder' && (
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                Enter SharePoint Folder URL
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
                Paste the URL of the SharePoint folder you want to sync.
              </p>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Folder URL
                  </label>
                  <input
                    type="url"
                    value={folderUrl}
                    onChange={(e) => setFolderUrl(e.target.value)}
                    placeholder="https://company.sharepoint.com/sites/Team/Shared Documents/Folder"
                    className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  />
                  <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                    Copy the URL from your browser while viewing the folder in SharePoint
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Step 3: File Selection */}
          {step === 'files' && (
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                What would you like to sync?
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                Choose to sync everything in the folder or select specific files and folders.
              </p>

              {/* Loading indicator while fetching folder contents */}
              {isLoading && !folderInfo && (
                <div className="flex items-center justify-center py-12">
                  <div className="text-center">
                    <Loader2 className="w-8 h-8 animate-spin text-indigo-600 mx-auto mb-3" />
                    <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
                      Reading SharePoint folder...
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                      This may take a moment for large folders
                    </p>
                  </div>
                </div>
              )}

              {folderInfo && (
                <>
                  <div className="mb-4 p-3 bg-gray-50 dark:bg-gray-900/50 rounded-lg">
                    <div className="flex items-center gap-2 text-sm">
                      <Folder className="w-4 h-4 text-indigo-500" />
                      <span className="font-medium text-gray-900 dark:text-white">{folderInfo.name}</span>
                    </div>
                  </div>

                  {/* Sync Mode Toggle */}
                  <div className="mb-6 space-y-3">
                <button
                  onClick={() => {
                    setSyncMode('all')
                    clearSelection()
                  }}
                  className={`w-full p-4 rounded-lg border text-left transition-colors ${
                    syncMode === 'all'
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                      : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                      syncMode === 'all'
                        ? 'bg-indigo-100 dark:bg-indigo-900/50'
                        : 'bg-gray-100 dark:bg-gray-700'
                    }`}>
                      <FolderSync className={`w-4 h-4 ${
                        syncMode === 'all'
                          ? 'text-indigo-600 dark:text-indigo-400'
                          : 'text-gray-500 dark:text-gray-400'
                      }`} />
                    </div>
                    <div>
                      <p className="font-medium text-gray-900 dark:text-white">Sync All</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        Sync everything in this folder (respects include/exclude patterns)
                      </p>
                    </div>
                  </div>
                </button>
                <button
                  onClick={() => setSyncMode('selected')}
                  className={`w-full p-4 rounded-lg border text-left transition-colors ${
                    syncMode === 'selected'
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                      : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                      syncMode === 'selected'
                        ? 'bg-indigo-100 dark:bg-indigo-900/50'
                        : 'bg-gray-100 dark:bg-gray-700'
                    }`}>
                      <CheckSquare className={`w-4 h-4 ${
                        syncMode === 'selected'
                          ? 'text-indigo-600 dark:text-indigo-400'
                          : 'text-gray-500 dark:text-gray-400'
                      }`} />
                    </div>
                    <div>
                      <p className="font-medium text-gray-900 dark:text-white">Select specific files/folders</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        Choose exactly which items to sync
                      </p>
                    </div>
                  </div>
                </button>
              </div>

                  {/* File Browser - Only shown when "selected" mode */}
                  {syncMode === 'selected' && (
                <>
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-3">
                      <Button variant="secondary" size="sm" onClick={selectAllItems}>
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
                      {selectedItems.size} selected
                    </span>
                  </div>

                  {isLoading ? (
                    <div className="flex items-center justify-center py-8">
                      <Loader2 className="w-6 h-6 animate-spin text-indigo-600" />
                    </div>
                  ) : browseItems.length === 0 ? (
                    <div className="text-center py-8">
                      <Folder className="w-10 h-10 text-gray-300 dark:text-gray-600 mx-auto mb-3" />
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        No files found in this folder
                      </p>
                    </div>
                  ) : (
                    <div className="max-h-96 overflow-y-auto border border-gray-200 dark:border-gray-700 rounded-lg divide-y divide-gray-100 dark:divide-gray-700">
                      {browseItems.map((item) => (
                        <button
                          key={item.id}
                          onClick={() => toggleItemSelection(item.id)}
                          className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 dark:hover:bg-gray-750 cursor-pointer"
                        >
                          <div className="flex-shrink-0">
                            {selectedItems.has(item.id) ? (
                              <CheckSquare className="w-5 h-5 text-indigo-600" />
                            ) : (
                              <Square className="w-5 h-5 text-gray-400" />
                            )}
                          </div>
                          <div className="flex items-center gap-2 min-w-0 flex-1">
                            {item.type === 'folder' ? (
                              <Folder className="w-4 h-4 text-amber-500 flex-shrink-0" />
                            ) : (
                              <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
                            )}
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                                {item.name}
                              </p>
                              {item.size && (
                                <p className="text-xs text-gray-500 dark:text-gray-400">
                                  {(item.size / 1024).toFixed(1)} KB
                                </p>
                              )}
                            </div>
                          </div>
                          {item.type === 'folder' && (
                            <span className="text-xs text-gray-400 flex-shrink-0">Folder</span>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                  </>
                )}
                </>
              )}
            </div>
          )}

          {/* Step 4: Configuration */}
          {step === 'config' && (
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                Configure Sync Settings
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
                Set up how files should be synchronized from SharePoint.
              </p>

              <div className="space-y-6">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Sync Name *
                  </label>
                  <input
                    type="text"
                    value={syncName}
                    onChange={(e) => setSyncName(e.target.value)}
                    placeholder="e.g., IT Policies"
                    className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Description
                  </label>
                  <textarea
                    value={syncDescription}
                    onChange={(e) => setSyncDescription(e.target.value)}
                    placeholder="Optional description..."
                    rows={2}
                    className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Sync Frequency
                  </label>
                  <select
                    value={syncFrequency}
                    onChange={(e) => setSyncFrequency(e.target.value)}
                    className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  >
                    <option value="manual">Manual only</option>
                    <option value="hourly">Hourly</option>
                    <option value="daily">Daily</option>
                  </select>
                </div>

                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    id="recursive"
                    checked={recursive}
                    onChange={(e) => setRecursive(e.target.checked)}
                    className="w-4 h-4 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500"
                  />
                  <label htmlFor="recursive" className="text-sm text-gray-700 dark:text-gray-300">
                    Include subfolders (recursive)
                  </label>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Include Patterns (comma-separated)
                  </label>
                  <input
                    type="text"
                    value={includePatterns}
                    onChange={(e) => setIncludePatterns(e.target.value)}
                    placeholder="e.g., *.pdf, *.docx"
                    className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  />
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    Leave empty to include all files
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Exclude Patterns (comma-separated)
                  </label>
                  <input
                    type="text"
                    value={excludePatterns}
                    onChange={(e) => setExcludePatterns(e.target.value)}
                    placeholder="e.g., ~$*, *.tmp"
                    className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  />
                </div>
              </div>
            </div>
          )}

          {/* Step 5: Confirm */}
          {step === 'confirm' && (
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                Review and Create
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
                Confirm your sync configuration before creating.
              </p>

              <div className="space-y-4">
                <div className="p-4 bg-gray-50 dark:bg-gray-900/50 rounded-lg space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-500 dark:text-gray-400">Name</span>
                    <span className="text-sm font-medium text-gray-900 dark:text-white">{syncName}</span>
                  </div>
                  {syncDescription && (
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-gray-500 dark:text-gray-400">Description</span>
                      <span className="text-sm text-gray-900 dark:text-white">{syncDescription}</span>
                    </div>
                  )}
                  <div className="flex items-start justify-between">
                    <span className="text-sm text-gray-500 dark:text-gray-400">Folder</span>
                    <span className="text-sm text-gray-900 dark:text-white text-right max-w-xs truncate">
                      {folderUrl}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-500 dark:text-gray-400">Frequency</span>
                    <span className="text-sm font-medium text-gray-900 dark:text-white capitalize">
                      {syncFrequency}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-500 dark:text-gray-400">Recursive</span>
                    <span className="text-sm font-medium text-gray-900 dark:text-white">
                      {recursive ? 'Yes' : 'No'}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-500 dark:text-gray-400">Sync Mode</span>
                    <span className="text-sm font-medium text-gray-900 dark:text-white">
                      {syncMode === 'all' ? 'Sync All' : 'Selected Items'}
                    </span>
                  </div>
                  {syncMode === 'selected' && selectedItems.size > 0 && (() => {
                    const selectedList = browseItems.filter(i => selectedItems.has(i.id))
                    const folderCount = selectedList.filter(i => i.type === 'folder').length
                    const fileCount = selectedList.filter(i => i.type === 'file').length
                    const totalSize = selectedList
                      .filter(i => i.type === 'file')
                      .reduce((sum, i) => sum + (i.size || 0), 0)

                    const formatSize = (bytes: number) => {
                      if (bytes === 0) return ''
                      if (bytes < 1024) return `${bytes} B`
                      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
                      if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
                      return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
                    }

                    return (
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-gray-500 dark:text-gray-400">Initial Import</span>
                        <div className="text-right">
                          {folderCount > 0 && recursive ? (
                            <>
                              <span className="text-sm font-medium text-indigo-600 dark:text-indigo-400">
                                {folderCount} {folderCount === 1 ? 'folder' : 'folders'}
                                {fileCount > 0 && `, ${fileCount} ${fileCount === 1 ? 'file' : 'files'}`}
                              </span>
                              <p className="text-xs text-gray-500 dark:text-gray-400">
                                All files & subfolders will be synced
                              </p>
                            </>
                          ) : (
                            <>
                              <span className="text-sm font-medium text-indigo-600 dark:text-indigo-400">
                                {fileCount} {fileCount === 1 ? 'file' : 'files'}
                                {folderCount > 0 && ` + ${folderCount} ${folderCount === 1 ? 'folder' : 'folders'}`}
                              </span>
                              {totalSize > 0 && (
                                <p className="text-xs text-gray-500 dark:text-gray-400">
                                  {formatSize(totalSize)}
                                </p>
                              )}
                            </>
                          )}
                        </div>
                      </div>
                    )
                  })()}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Navigation Buttons */}
        <div className="mt-6 flex items-center justify-between">
          <Button
            variant="secondary"
            onClick={goBack}
            disabled={step === 'connection' || isLoading}
            className="gap-2"
          >
            <ArrowLeft className="w-4 h-4" />
            Back
          </Button>

          {step === 'confirm' ? (
            <Button
              variant="primary"
              onClick={handleCreateSync}
              disabled={isLoading || isSubmitting}
              className="gap-2"
            >
              {isLoading || isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4" />
                  Create Sync
                </>
              )}
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={goNext}
              disabled={!canProceed() || isLoading}
              className="gap-2"
            >
              Next
              <ArrowRight className="w-4 h-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

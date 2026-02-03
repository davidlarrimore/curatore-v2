'use client'

import { Fragment, useState, useEffect, useCallback } from 'react'
import { Dialog, Transition } from '@headlessui/react'
import { useAuth } from '@/lib/auth-context'
import { assetsApi, type Asset } from '@/lib/api'
import {
  Search,
  X,
  FileText,
  Check,
  Loader2,
  FolderOpen,
  Cloud,
  Upload,
  Globe,
} from 'lucide-react'
import { Button } from '@/components/ui/Button'

interface AssetPickerDialogProps {
  isOpen: boolean
  onClose: () => void
  onSelect: (ids: string[]) => void
  selectedIds: string[]
  multiple?: boolean
}

const SOURCE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  upload: Upload,
  sharepoint: FolderOpen,
  scrape: Globe,
  sam: Cloud,
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

export function AssetPickerDialog({
  isOpen,
  onClose,
  onSelect,
  selectedIds,
  multiple = false,
}: AssetPickerDialogProps) {
  const { token } = useAuth()
  const [assets, setAssets] = useState<Asset[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set(selectedIds))

  const loadAssets = useCallback(async () => {
    if (!token) return
    setIsLoading(true)
    try {
      const result = await assetsApi.listAssets(token, { status: 'ready', limit: 50 })
      setAssets(result.items)
    } catch (err) {
      console.error('Failed to load assets:', err)
    } finally {
      setIsLoading(false)
    }
  }, [token])

  useEffect(() => {
    if (isOpen) {
      loadAssets()
      setSelected(new Set(selectedIds))
    }
  }, [isOpen, loadAssets, selectedIds])

  const filteredAssets = assets.filter((asset) => {
    if (!searchQuery.trim()) return true
    const query = searchQuery.toLowerCase()
    return (
      asset.original_filename.toLowerCase().includes(query) ||
      asset.source_type.toLowerCase().includes(query)
    )
  })

  const toggleSelection = (id: string) => {
    const newSelected = new Set(selected)
    if (newSelected.has(id)) {
      newSelected.delete(id)
    } else {
      if (!multiple) {
        newSelected.clear()
      }
      newSelected.add(id)
    }
    setSelected(newSelected)
  }

  const handleConfirm = () => {
    onSelect(Array.from(selected))
  }

  return (
    <Transition.Root show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-300"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-200"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-gray-900/80 backdrop-blur-sm transition-opacity" />
        </Transition.Child>

        <div className="fixed inset-0 z-10 overflow-y-auto">
          <div className="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
            <Transition.Child
              as={Fragment}
              enter="ease-out duration-300"
              enterFrom="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
              enterTo="opacity-100 translate-y-0 sm:scale-100"
              leave="ease-in duration-200"
              leaveFrom="opacity-100 translate-y-0 sm:scale-100"
              leaveTo="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
            >
              <Dialog.Panel className="relative transform overflow-hidden rounded-xl bg-white dark:bg-gray-800 text-left shadow-2xl transition-all sm:my-8 sm:w-full sm:max-w-2xl">
                {/* Header */}
                <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center">
                        <FileText className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                      </div>
                      <div>
                        <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-white">
                          Select Asset{multiple ? 's' : ''}
                        </Dialog.Title>
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                          Choose from your document library
                        </p>
                      </div>
                    </div>
                    <button
                      type="button"
                      className="rounded-lg p-2 text-gray-400 hover:text-gray-500 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
                      onClick={onClose}
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>

                  {/* Search */}
                  <div className="mt-4 relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                    <input
                      type="text"
                      placeholder="Search assets..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="w-full pl-9 pr-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                </div>

                {/* Asset List */}
                <div className="max-h-[400px] overflow-y-auto">
                  {isLoading ? (
                    <div className="flex items-center justify-center py-12">
                      <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
                    </div>
                  ) : filteredAssets.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-12 text-center">
                      <FileText className="w-10 h-10 text-gray-300 dark:text-gray-600 mb-3" />
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        {searchQuery ? 'No assets match your search' : 'No assets available'}
                      </p>
                    </div>
                  ) : (
                    <div className="divide-y divide-gray-200 dark:divide-gray-700">
                      {filteredAssets.map((asset) => {
                        const isSelected = selected.has(asset.id)
                        const SourceIcon = SOURCE_ICONS[asset.source_type] || FileText

                        return (
                          <button
                            key={asset.id}
                            type="button"
                            onClick={() => toggleSelection(asset.id)}
                            className={`
                              w-full flex items-center gap-4 px-6 py-3 text-left transition-colors
                              ${isSelected
                                ? 'bg-indigo-50 dark:bg-indigo-900/20'
                                : 'hover:bg-gray-50 dark:hover:bg-gray-700/50'
                              }
                            `}
                          >
                            <div
                              className={`
                                w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0
                                ${isSelected
                                  ? 'border-indigo-600 bg-indigo-600'
                                  : 'border-gray-300 dark:border-gray-600'
                                }
                              `}
                            >
                              {isSelected && <Check className="w-3 h-3 text-white" />}
                            </div>

                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-gray-900 dark:text-white truncate">
                                  {asset.original_filename}
                                </span>
                              </div>
                              <div className="flex items-center gap-3 mt-1 text-xs text-gray-500 dark:text-gray-400">
                                <span className="flex items-center gap-1">
                                  <SourceIcon className="w-3 h-3" />
                                  {asset.source_type}
                                </span>
                                {asset.file_size && (
                                  <span>{formatFileSize(asset.file_size)}</span>
                                )}
                                <span>{formatDate(asset.created_at)}</span>
                              </div>
                            </div>
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>

                {/* Footer */}
                <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-500 dark:text-gray-400">
                      {selected.size} selected
                    </span>
                    <div className="flex items-center gap-3">
                      <Button variant="secondary" onClick={onClose}>
                        Cancel
                      </Button>
                      <Button
                        variant="primary"
                        onClick={handleConfirm}
                        disabled={selected.size === 0}
                      >
                        Select ({selected.size})
                      </Button>
                    </div>
                  </div>
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition.Root>
  )
}

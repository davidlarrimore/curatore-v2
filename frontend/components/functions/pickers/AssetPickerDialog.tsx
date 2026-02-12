'use client'

import { Fragment, useState, useEffect, useCallback, useRef } from 'react'
import { Dialog, Transition } from '@headlessui/react'
import { useAuth } from '@/lib/auth-context'
import { searchApi, assetsApi, type Asset, type SearchHit, type SearchResponse } from '@/lib/api'
import {
  Search,
  X,
  FileText,
  Check,
  Loader2,
  FolderSync,
  Cloud,
  Upload,
  Globe,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { Button } from '@/components/ui/Button'

interface AssetPickerDialogProps {
  isOpen: boolean
  onClose: () => void
  onSelect: (ids: string[]) => void
  selectedIds: string[]
  multiple?: boolean
}

// Source type display config — subset of search page's sourceTypeDisplayConfig
const SOURCE_TYPE_CONFIG: Record<string, { name: string; icon: React.ReactNode; color: string }> = {
  upload: {
    name: 'Upload',
    icon: <Upload className="w-3.5 h-3.5" />,
    color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  },
  sharepoint: {
    name: 'SharePoint',
    icon: <FolderSync className="w-3.5 h-3.5" />,
    color: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400',
  },
  web_scrape: {
    name: 'Web Scrape',
    icon: <Globe className="w-3.5 h-3.5" />,
    color: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  },
  sam_gov: {
    name: 'SAM.gov',
    icon: <Cloud className="w-3.5 h-3.5" />,
    color: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  },
}

// Asset-only source types (excludes Salesforce, forecasts)
const ASSET_SOURCE_TYPES = ['upload', 'sharepoint', 'web_scrape', 'sam_gov']

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

// UUID v4 pattern
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

// Unified item shape for rendering — normalises Asset list and SearchHit results
interface PickerItem {
  id: string
  filename: string
  source_type: string
  file_size?: number
  created_at?: string
  score?: number
}

function assetToItem(a: Asset): PickerItem {
  return {
    id: a.id,
    filename: a.original_filename,
    source_type: a.source_type,
    file_size: a.file_size ?? undefined,
    created_at: a.created_at,
  }
}

function hitToItem(h: SearchHit): PickerItem {
  return {
    id: h.asset_id,
    filename: h.filename || h.title || 'Untitled',
    source_type: h.source_type || 'unknown',
    created_at: h.created_at,
    score: h.score,
  }
}

export function AssetPickerDialog({
  isOpen,
  onClose,
  onSelect,
  selectedIds,
  multiple = false,
}: AssetPickerDialogProps) {
  const { token } = useAuth()
  const [items, setItems] = useState<PickerItem[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set(selectedIds))
  const [sourceFilter, setSourceFilter] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState('')
  const limit = 20
  const abortRef = useRef<AbortController | null>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  // Debounce query
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query)
      setOffset(0)
    }, 300)
    return () => clearTimeout(timer)
  }, [query])

  // Main data fetch — uses search API when there's a query, falls back to asset listing
  const fetchData = useCallback(async () => {
    if (!token) return

    // Cancel in-flight request
    if (abortRef.current) abortRef.current.abort()
    const ac = new AbortController()
    abortRef.current = ac

    setIsLoading(true)
    setError('')

    try {
      const trimmed = debouncedQuery.trim()

      // Direct UUID lookup — if the query is a UUID, fetch the asset directly
      if (trimmed && UUID_RE.test(trimmed)) {
        try {
          const asset = await assetsApi.getAsset(token, trimmed)
          if (!ac.signal.aborted) {
            setItems([assetToItem(asset)])
            setTotal(1)
          }
        } catch {
          if (!ac.signal.aborted) {
            setItems([])
            setTotal(0)
            setError('Asset not found for that ID')
          }
        }
        return
      }

      if (trimmed) {
        // Server-side keyword search — fast, no embedding generation
        const sourceTypes = sourceFilter ? [sourceFilter] : ASSET_SOURCE_TYPES
        const response: SearchResponse = await searchApi.search(token, {
          query: trimmed,
          search_mode: 'keyword',
          source_types: sourceTypes,
          limit,
          offset,
        })
        if (!ac.signal.aborted) {
          setItems(response.hits.map(hitToItem))
          setTotal(response.total)
        }
      } else {
        // No query — show recent assets via listing endpoint
        const params: Record<string, any> = {
          status: 'ready',
          limit,
          offset,
        }
        if (sourceFilter) params.source_type = sourceFilter
        const result = await assetsApi.listAssets(token, params)
        if (!ac.signal.aborted) {
          setItems(result.items.map(assetToItem))
          setTotal(result.total)
        }
      }
    } catch (err: any) {
      if (err.name === 'AbortError' || ac.signal.aborted) return
      console.error('[AssetPicker] search error:', err)
      if (!ac.signal.aborted) {
        setError(err.message || 'Failed to load assets')
        setItems([])
        setTotal(0)
      }
    } finally {
      // Always clear loading for the current request, even if superseded
      if (abortRef.current === ac) {
        setIsLoading(false)
      }
    }
  }, [token, debouncedQuery, sourceFilter, offset, limit])

  // Fetch when deps change
  useEffect(() => {
    if (isOpen) fetchData()
  }, [isOpen, fetchData])

  // Reset state when dialog opens
  useEffect(() => {
    if (isOpen) {
      setSelected(new Set(selectedIds))
      setQuery('')
      setDebouncedQuery('')
      setSourceFilter(null)
      setOffset(0)
      setError('')
      // Focus search input after transition
      setTimeout(() => searchInputRef.current?.focus(), 100)
    }
  }, [isOpen, selectedIds])

  const toggleSelection = (id: string) => {
    const newSelected = new Set(selected)
    if (newSelected.has(id)) {
      newSelected.delete(id)
    } else {
      if (!multiple) newSelected.clear()
      newSelected.add(id)
    }
    setSelected(newSelected)
  }

  const handleConfirm = () => {
    onSelect(Array.from(selected))
  }

  const toggleSourceFilter = (type: string) => {
    setSourceFilter(prev => prev === type ? null : type)
    setOffset(0)
  }

  // Pagination
  const totalPages = Math.ceil(total / limit)
  const currentPage = Math.floor(offset / limit) + 1

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
                          Search by name, content, or paste an asset ID
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

                  {/* Search Input */}
                  <div className="mt-4 relative">
                    <div className="absolute left-3 top-1/2 -translate-y-1/2">
                      {isLoading ? (
                        <Loader2 className="w-4 h-4 text-gray-400 animate-spin" />
                      ) : (
                        <Search className="w-4 h-4 text-gray-400" />
                      )}
                    </div>
                    <input
                      ref={searchInputRef}
                      type="text"
                      placeholder="Search documents, content, or paste UUID..."
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      className="w-full pl-9 pr-8 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                    {query && (
                      <button
                        onClick={() => setQuery('')}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    )}
                  </div>

                  {/* Source Type Filters */}
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <span className="text-xs text-gray-500 dark:text-gray-400">Source:</span>
                    {Object.entries(SOURCE_TYPE_CONFIG).map(([type, config]) => {
                      const isActive = sourceFilter === type
                      return (
                        <button
                          key={type}
                          onClick={() => toggleSourceFilter(type)}
                          disabled={isLoading}
                          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all ${
                            isActive
                              ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400 ring-1 ring-indigo-500'
                              : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
                          } ${isLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                        >
                          {config.icon}
                          {config.name}
                        </button>
                      )
                    })}
                    {sourceFilter && (
                      <button
                        onClick={() => { setSourceFilter(null); setOffset(0) }}
                        className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300 underline"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                </div>

                {/* Results */}
                <div className="max-h-[400px] overflow-y-auto">
                  {error ? (
                    <div className="flex flex-col items-center justify-center py-12 text-center px-6">
                      <FileText className="w-10 h-10 text-gray-300 dark:text-gray-600 mb-3" />
                      <p className="text-sm text-gray-500 dark:text-gray-400">{error}</p>
                    </div>
                  ) : isLoading && items.length === 0 ? (
                    <div className="flex items-center justify-center py-12">
                      <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
                    </div>
                  ) : items.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-12 text-center">
                      <FileText className="w-10 h-10 text-gray-300 dark:text-gray-600 mb-3" />
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        {debouncedQuery ? 'No assets match your search' : 'No assets available'}
                      </p>
                    </div>
                  ) : (
                    <div className="divide-y divide-gray-200 dark:divide-gray-700">
                      {items.map((item) => {
                        const isSelected = selected.has(item.id)
                        const config = SOURCE_TYPE_CONFIG[item.source_type] || {
                          name: item.source_type,
                          icon: <FileText className="w-3.5 h-3.5" />,
                          color: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400',
                        }

                        return (
                          <button
                            key={item.id}
                            type="button"
                            onClick={() => toggleSelection(item.id)}
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
                                  {item.filename}
                                </span>
                              </div>
                              <div className="flex items-center gap-3 mt-1 text-xs text-gray-500 dark:text-gray-400">
                                <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium ${config.color}`}>
                                  {config.icon}
                                  {config.name}
                                </span>
                                {item.file_size != null && item.file_size > 0 && (
                                  <span>{formatFileSize(item.file_size)}</span>
                                )}
                                {item.created_at && (
                                  <span>{formatDate(item.created_at)}</span>
                                )}
                                {item.score != null && (
                                  <span className="text-indigo-500 dark:text-indigo-400 font-medium">
                                    {Math.min(100, item.score).toFixed(0)}% match
                                  </span>
                                )}
                              </div>
                              <div className="mt-0.5 text-[10px] text-gray-400 dark:text-gray-500 font-mono truncate">
                                {item.id}
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
                    <div className="flex items-center gap-4">
                      <span className="text-sm text-gray-500 dark:text-gray-400">
                        {selected.size} selected
                      </span>
                      {/* Pagination */}
                      {totalPages > 1 && (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => setOffset(Math.max(0, offset - limit))}
                            disabled={currentPage <= 1 || isLoading}
                            className="p-1 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            <ChevronLeft className="w-4 h-4" />
                          </button>
                          <span className="text-xs text-gray-500 dark:text-gray-400">
                            {currentPage}/{totalPages}
                          </span>
                          <button
                            onClick={() => setOffset(offset + limit)}
                            disabled={currentPage >= totalPages || isLoading}
                            className="p-1 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            <ChevronRight className="w-4 h-4" />
                          </button>
                          <span className="text-xs text-gray-400 dark:text-gray-500">
                            ({total.toLocaleString()} total)
                          </span>
                        </div>
                      )}
                    </div>
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

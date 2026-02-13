'use client'

import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '@/lib/auth-context'
import { collectionsApi, type SearchCollection } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import {
  Library,
  Plus,
  Trash2,
  Eraser,
  Upload,
  Loader2,
  X,
  RefreshCw,
} from 'lucide-react'

interface CollectionsTabProps {
  onError?: (msg: string) => void
}

export default function CollectionsTab({ onError }: CollectionsTabProps) {
  const { token } = useAuth()
  const [collections, setCollections] = useState<SearchCollection[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [populateTarget, setPopulateTarget] = useState<SearchCollection | null>(null)

  const loadCollections = useCallback(async () => {
    if (!token) return
    setIsLoading(true)
    try {
      const res = await collectionsApi.listCollections(token, { limit: 100 })
      setCollections(res.collections)
    } catch (err: any) {
      onError?.(err.message || 'Failed to load collections')
    } finally {
      setIsLoading(false)
    }
  }, [token, onError])

  useEffect(() => {
    loadCollections()
  }, [loadCollections])

  const handleDelete = async (col: SearchCollection) => {
    if (!token) return
    if (!confirm(`Delete collection "${col.name}"? This will remove all chunks and cannot be undone.`)) return
    try {
      await collectionsApi.deleteCollection(token, col.id)
      await loadCollections()
    } catch (err: any) {
      onError?.(err.message || 'Failed to delete collection')
    }
  }

  const handleClear = async (col: SearchCollection) => {
    if (!token) return
    if (!confirm(`Clear all chunks from "${col.name}"? The collection will remain but item count resets to 0.`)) return
    try {
      await collectionsApi.clearCollection(token, col.id)
      await loadCollections()
    } catch (err: any) {
      onError?.(err.message || 'Failed to clear collection')
    }
  }

  const typeBadgeVariant = (t: string): 'info' | 'default' | 'warning' => {
    switch (t) {
      case 'static': return 'info'
      case 'dynamic': return 'default'
      case 'source_bound': return 'warning'
      default: return 'default'
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-8 w-8 text-indigo-500 animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Search Collections</h2>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-0.5">
            Manage isolated vector stores for scoped search
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={loadCollections}>
            <RefreshCw className="w-4 h-4 mr-1.5" />
            Refresh
          </Button>
          <Button size="sm" onClick={() => setShowCreateForm(true)}>
            <Plus className="w-4 h-4 mr-1.5" />
            Create
          </Button>
        </div>
      </div>

      {/* Create Form */}
      {showCreateForm && (
        <CreateCollectionForm
          token={token}
          onCreated={() => { setShowCreateForm(false); loadCollections() }}
          onCancel={() => setShowCreateForm(false)}
          onError={onError}
        />
      )}

      {/* Populate Modal */}
      {populateTarget && (
        <PopulateModal
          token={token}
          collection={populateTarget}
          onDone={() => { setPopulateTarget(null); loadCollections() }}
          onCancel={() => setPopulateTarget(null)}
          onError={onError}
        />
      )}

      {/* Collections Table */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead className="bg-gray-50 dark:bg-gray-800/50">
            <tr>
              <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">Name</th>
              <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">Slug</th>
              <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">Type</th>
              <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">Items</th>
              <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">Status</th>
              <th className="px-6 py-3.5 text-right text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">Actions</th>
            </tr>
          </thead>
          <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
            {collections.map((col) => (
              <tr key={col.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="text-sm font-medium text-gray-900 dark:text-white">{col.name}</div>
                  {col.description && (
                    <div className="text-xs text-gray-500 dark:text-gray-400 truncate max-w-xs">{col.description}</div>
                  )}
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <code className="text-xs text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">{col.slug}</code>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <Badge variant={typeBadgeVariant(col.collection_type)} size="sm">
                    {col.collection_type}
                  </Badge>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700 dark:text-gray-300">
                  {col.item_count.toLocaleString()}
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <Badge variant={col.is_active ? 'success' : 'secondary'} size="sm">
                    {col.is_active ? 'Active' : 'Inactive'}
                  </Badge>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-right">
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" size="xs" onClick={() => setPopulateTarget(col)} title="Populate">
                      <Upload className="w-3.5 h-3.5 mr-1" />
                      Populate
                    </Button>
                    <Button variant="outline" size="xs" onClick={() => handleClear(col)} title="Clear all chunks">
                      <Eraser className="w-3.5 h-3.5 mr-1" />
                      Clear
                    </Button>
                    <Button variant="destructive" size="xs" onClick={() => handleDelete(col)} title="Delete collection">
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {collections.length === 0 && (
          <div className="text-center py-12">
            <Library className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <p className="text-sm font-medium text-gray-900 dark:text-white mb-1">No collections</p>
            <p className="text-sm text-gray-500 dark:text-gray-400">Create a collection to get started.</p>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Create Collection Form
// ---------------------------------------------------------------------------

function CreateCollectionForm({
  token,
  onCreated,
  onCancel,
  onError,
}: {
  token: string | undefined | null
  onCreated: () => void
  onCancel: () => void
  onError?: (msg: string) => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [collectionType, setCollectionType] = useState('static')
  const [isSaving, setIsSaving] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token || !name.trim()) return

    setIsSaving(true)
    try {
      await collectionsApi.createCollection(token, {
        name: name.trim(),
        description: description.trim() || undefined,
        collection_type: collectionType,
      })
      onCreated()
    } catch (err: any) {
      onError?.(err.message || 'Failed to create collection')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="bg-gray-50 dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Create Collection</h3>
        <button onClick={onCancel} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
          <X className="w-4 h-4" />
        </button>
      </div>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="col-name" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Name <span className="text-red-500">*</span>
          </label>
          <input
            id="col-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Federal Procurement Docs"
            required
            className="w-full max-w-lg px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm"
          />
        </div>
        <div>
          <label htmlFor="col-desc" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Description
          </label>
          <input
            id="col-desc"
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional description"
            className="w-full max-w-lg px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm"
          />
        </div>
        <div>
          <label htmlFor="col-type" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Type
          </label>
          <select
            id="col-type"
            value={collectionType}
            onChange={(e) => setCollectionType(e.target.value)}
            className="w-full max-w-lg px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm"
          >
            <option value="static">Static</option>
            <option value="dynamic">Dynamic</option>
            <option value="source_bound">Source Bound</option>
          </select>
        </div>
        <div className="flex gap-3 pt-2">
          <Button type="submit" size="sm" disabled={isSaving || !name.trim()}>
            {isSaving ? 'Creating...' : 'Create Collection'}
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Populate Modal
// ---------------------------------------------------------------------------

function PopulateModal({
  token,
  collection,
  onDone,
  onCancel,
  onError,
}: {
  token: string | undefined | null
  collection: SearchCollection
  onDone: () => void
  onCancel: () => void
  onError?: (msg: string) => void
}) {
  const [assetIdsText, setAssetIdsText] = useState('')
  const [isPopulating, setIsPopulating] = useState(false)
  const [result, setResult] = useState<{ added: number; skipped: number; total: number } | null>(null)

  const parseAssetIds = (): string[] => {
    return assetIdsText
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter(Boolean)
  }

  const handlePopulate = async () => {
    if (!token) return
    const ids = parseAssetIds()
    if (ids.length === 0) {
      onError?.('Enter at least one asset ID')
      return
    }

    setIsPopulating(true)
    setResult(null)
    try {
      const res = await collectionsApi.populateCollection(token, collection.id, { asset_ids: ids })
      setResult(res)
    } catch (err: any) {
      onError?.(err.message || 'Failed to populate collection')
    } finally {
      setIsPopulating(false)
    }
  }

  return (
    <div className="bg-gray-50 dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
          Populate &ldquo;{collection.name}&rdquo;
        </h3>
        <button onClick={onCancel} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="space-y-4">
        <div>
          <label htmlFor="asset-ids" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Asset IDs (one per line or comma-separated)
          </label>
          <textarea
            id="asset-ids"
            rows={5}
            value={assetIdsText}
            onChange={(e) => setAssetIdsText(e.target.value)}
            placeholder="e.g. a1b2c3d4-e5f6-7890-abcd-ef1234567890"
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm font-mono"
          />
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {parseAssetIds().length} asset ID(s) entered &mdash; copies existing chunks from the core search index
          </p>
        </div>

        {result && (
          <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800/50 rounded-lg p-3">
            <p className="text-sm text-emerald-800 dark:text-emerald-200">
              <strong>{result.added}</strong> chunks added, <strong>{result.skipped}</strong> assets skipped. Total: <strong>{result.total}</strong> chunks.
            </p>
          </div>
        )}

        <div className="flex gap-3">
          <Button size="sm" onClick={handlePopulate} disabled={isPopulating || parseAssetIds().length === 0}>
            {isPopulating ? (
              <>
                <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                Populating...
              </>
            ) : (
              <>
                <Upload className="w-4 h-4 mr-1.5" />
                Copy from Index
              </>
            )}
          </Button>
          <Button variant="outline" size="sm" onClick={result ? onDone : onCancel}>
            {result ? 'Done' : 'Cancel'}
          </Button>
        </div>
      </div>
    </div>
  )
}

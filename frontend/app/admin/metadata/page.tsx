'use client'

import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '@/lib/auth-context'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  Database,
  Tag,
  Filter,
  ChevronDown,
  ChevronRight,
  Loader2,
  BookOpen,
  Hash,
  Calendar,
  ToggleLeft,
  List,
  Type,
  ArrowRight,
  Plus,
  Pencil,
  Trash2,
  X,
  RefreshCw,
  Sparkles,
  Check,
  XCircle,
  Link2,
  Search,
  AlertTriangle,
  Download,
  Upload,
} from 'lucide-react'
import { metadataApi } from '@/lib/api'
import type {
  MetadataCatalog,
  MetadataNamespace,
  FacetDefinition,
  MetadataFieldDefinition,
  MetadataFieldCreateRequest,
  FacetCreateRequest,
  FacetMappingCreateRequest,
  FacetReferenceValue,
  FacetPendingSuggestions,
  FacetDiscoverResult,
} from '@/lib/api'

const dataTypeIcons: Record<string, typeof Type> = {
  string: Type,
  number: Hash,
  boolean: ToggleLeft,
  date: Calendar,
  array: List,
  enum: Tag,
  object: Database,
}

const DATA_TYPES = ['string', 'number', 'boolean', 'date', 'enum', 'array', 'object']
const FACET_DATA_TYPES = ['string', 'number', 'boolean', 'date']
const OPERATOR_OPTIONS = ['eq', 'in', 'gte', 'lte', 'contains']

// =============================================================================
// Add Field Modal
// =============================================================================

function AddFieldModal({
  namespace,
  onClose,
  onSave,
}: {
  namespace: string
  onClose: () => void
  onSave: (data: MetadataFieldCreateRequest) => Promise<void>
}) {
  const [fieldName, setFieldName] = useState('')
  const [dataType, setDataType] = useState('string')
  const [indexed, setIndexed] = useState(true)
  const [facetable, setFacetable] = useState(false)
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      await onSave({
        field_name: fieldName,
        data_type: dataType,
        indexed,
        facetable,
        description: description || undefined,
      })
      onClose()
    } catch (err: any) {
      setError(err.message || 'Failed to create field')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            Add Field to <span className="font-mono text-indigo-600">{namespace}</span>
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        {error && (
          <div className="mb-3 p-2 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 rounded text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Field Name</label>
            <input
              type="text"
              value={fieldName}
              onChange={(e) => setFieldName(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              placeholder="e.g., contract_value"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Data Type</label>
            <select
              value={dataType}
              onChange={(e) => setDataType(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
            >
              {DATA_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>

          <div className="flex space-x-6">
            <label className="flex items-center space-x-2 text-sm">
              <input type="checkbox" checked={indexed} onChange={(e) => setIndexed(e.target.checked)} className="rounded" />
              <span className="text-gray-700 dark:text-gray-300">Indexed</span>
            </label>
            <label className="flex items-center space-x-2 text-sm">
              <input type="checkbox" checked={facetable} onChange={(e) => setFacetable(e.target.checked)} className="rounded" />
              <span className="text-gray-700 dark:text-gray-300">Facetable</span>
            </label>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              rows={2}
              placeholder="Optional description"
            />
          </div>

          <div className="flex justify-end space-x-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-md">
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || !fieldName}
              className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? 'Creating...' : 'Create Field'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// =============================================================================
// Add Facet Modal
// =============================================================================

function AddFacetModal({
  onClose,
  onSave,
}: {
  onClose: () => void
  onSave: (data: FacetCreateRequest) => Promise<void>
}) {
  const [facetName, setFacetName] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [dataType, setDataType] = useState('string')
  const [description, setDescription] = useState('')
  const [operators, setOperators] = useState<string[]>(['eq', 'in'])
  const [mappings, setMappings] = useState<FacetMappingCreateRequest[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const addMapping = () => setMappings([...mappings, { content_type: '', json_path: '' }])
  const removeMapping = (i: number) => setMappings(mappings.filter((_, idx) => idx !== i))
  const updateMapping = (i: number, field: keyof FacetMappingCreateRequest, value: string) => {
    const updated = [...mappings]
    updated[i] = { ...updated[i], [field]: value }
    setMappings(updated)
  }

  const toggleOperator = (op: string) => {
    setOperators((prev) =>
      prev.includes(op) ? prev.filter((o) => o !== op) : [...prev, op]
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      await onSave({
        facet_name: facetName,
        display_name: displayName,
        data_type: dataType,
        description: description || undefined,
        operators,
        mappings: mappings.filter((m) => m.content_type && m.json_path),
      })
      onClose()
    } catch (err: any) {
      setError(err.message || 'Failed to create facet')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Add Facet</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        {error && (
          <div className="mb-3 p-2 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 rounded text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Facet Name</label>
              <input
                type="text"
                value={facetName}
                onChange={(e) => setFacetName(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
                placeholder="e.g., contract_type"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Display Name</label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
                placeholder="e.g., Contract Type"
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Data Type</label>
            <select
              value={dataType}
              onChange={(e) => setDataType(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
            >
              {FACET_DATA_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              rows={2}
              placeholder="Optional description"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Operators</label>
            <div className="flex flex-wrap gap-2">
              {OPERATOR_OPTIONS.map((op) => (
                <button
                  key={op}
                  type="button"
                  onClick={() => toggleOperator(op)}
                  className={`px-3 py-1 text-xs rounded-full border ${
                    operators.includes(op)
                      ? 'bg-indigo-100 dark:bg-indigo-900/30 border-indigo-300 dark:border-indigo-700 text-indigo-700 dark:text-indigo-300'
                      : 'bg-gray-50 dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-gray-500'
                  }`}
                >
                  {op}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Content Type Mappings</label>
              <button type="button" onClick={addMapping} className="text-xs text-indigo-600 hover:text-indigo-700 flex items-center">
                <Plus className="w-3 h-3 mr-1" /> Add Mapping
              </button>
            </div>
            {mappings.map((m, i) => (
              <div key={i} className="flex items-center space-x-2 mb-2">
                <input
                  type="text"
                  value={m.content_type}
                  onChange={(e) => updateMapping(i, 'content_type', e.target.value)}
                  className="flex-1 px-2 py-1.5 border border-gray-300 dark:border-gray-600 rounded text-xs bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
                  placeholder="content_type"
                />
                <ArrowRight className="w-3 h-3 text-gray-400 flex-shrink-0" />
                <input
                  type="text"
                  value={m.json_path}
                  onChange={(e) => updateMapping(i, 'json_path', e.target.value)}
                  className="flex-1 px-2 py-1.5 border border-gray-300 dark:border-gray-600 rounded text-xs bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
                  placeholder="namespace.field"
                />
                <button type="button" onClick={() => removeMapping(i)} className="text-red-400 hover:text-red-600">
                  <X className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>

          <div className="flex justify-end space-x-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-md">
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || !facetName || !displayName}
              className="px-4 py-2 text-sm bg-purple-600 text-white rounded-md hover:bg-purple-700 disabled:opacity-50"
            >
              {saving ? 'Creating...' : 'Create Facet'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// =============================================================================
// Add Reference Value Modal
// =============================================================================

function AddRefValueModal({
  facetName,
  initialCanonicalValue,
  onClose,
  onSave,
}: {
  facetName: string
  initialCanonicalValue?: string
  onClose: () => void
  onSave: (data: { canonical_value: string; display_label?: string; description?: string; aliases?: string[] }) => Promise<void>
}) {
  const [canonicalValue, setCanonicalValue] = useState(initialCanonicalValue || '')
  const [displayLabel, setDisplayLabel] = useState('')
  const [description, setDescription] = useState('')
  const [aliasesText, setAliasesText] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      const aliases = aliasesText
        .split('\n')
        .map(a => a.trim())
        .filter(a => a.length > 0)
      await onSave({
        canonical_value: canonicalValue,
        display_label: displayLabel || undefined,
        description: description || undefined,
        aliases: aliases.length > 0 ? aliases : undefined,
      })
      onClose()
    } catch (err: any) {
      setError(err.message || 'Failed to create reference value')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            Add Reference Value to <span className="font-mono text-indigo-600">{facetName}</span>
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        {error && (
          <div className="mb-3 p-2 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 rounded text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Canonical Value</label>
            <input
              type="text"
              value={canonicalValue}
              onChange={(e) => setCanonicalValue(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              placeholder="e.g., Department of Homeland Security"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Display Label</label>
            <input
              type="text"
              value={displayLabel}
              onChange={(e) => setDisplayLabel(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              placeholder="e.g., DHS (short form)"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              rows={2}
              placeholder="Optional description"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Initial Aliases <span className="font-normal text-gray-400">(one per line)</span>
            </label>
            <textarea
              value={aliasesText}
              onChange={(e) => setAliasesText(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 font-mono"
              rows={3}
              placeholder={"HOMELAND SECURITY, DEPARTMENT OF\nDHS\nDept. of Homeland Security"}
            />
          </div>

          <div className="flex justify-end space-x-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-md">
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || !canonicalValue}
              className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? 'Creating...' : 'Create Value'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// =============================================================================
// Add Alias Modal
// =============================================================================

function AddAliasModal({
  onClose,
  onSave,
}: {
  onClose: () => void
  onSave: (aliasValue: string, sourceHint?: string) => Promise<void>
}) {
  const [aliasValue, setAliasValue] = useState('')
  const [sourceHint, setSourceHint] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      await onSave(aliasValue, sourceHint || undefined)
      onClose()
    } catch (err: any) {
      setError(err.message || 'Failed to add alias')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full max-w-sm p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Add Alias</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        {error && (
          <div className="mb-3 p-2 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 rounded text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Alias Value</label>
            <input
              type="text"
              value={aliasValue}
              onChange={(e) => setAliasValue(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              placeholder="e.g., HOMELAND SECURITY, DEPARTMENT OF"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Source Hint <span className="font-normal text-gray-400">(optional)</span>
            </label>
            <input
              type="text"
              value={sourceHint}
              onChange={(e) => setSourceHint(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              placeholder="e.g., sam_gov, forecast, salesforce"
            />
          </div>

          <div className="flex justify-end space-x-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-md">
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || !aliasValue}
              className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? 'Adding...' : 'Add Alias'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// =============================================================================
// Main Page
// =============================================================================

export default function MetadataCatalogPage() {
  const { token } = useAuth()
  const [catalog, setCatalog] = useState<MetadataCatalog | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expandedNamespaces, setExpandedNamespaces] = useState<Set<string>>(new Set())
  const [expandedFacets, setExpandedFacets] = useState<Set<string>>(new Set())
  const [activeTab, setActiveTab] = useState<'namespaces' | 'facets' | 'reference'>('namespaces')
  const [showAddFieldModal, setShowAddFieldModal] = useState<string | null>(null)
  const [showAddFacetModal, setShowAddFacetModal] = useState(false)
  const [actionMessage, setActionMessage] = useState('')

  // Reference Data tab state
  const [selectedRefFacet, setSelectedRefFacet] = useState<string>('')
  const [refValues, setRefValues] = useState<FacetReferenceValue[]>([])
  const [refLoading, setRefLoading] = useState(false)
  const [refExpandedIds, setRefExpandedIds] = useState<Set<string>>(new Set())
  const [pendingSuggestions, setPendingSuggestions] = useState<FacetPendingSuggestions | null>(null)
  const [discovering, setDiscovering] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncingFacets, setSyncingFacets] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [discoverResults, setDiscoverResults] = useState<FacetDiscoverResult | null>(null)
  const [showAddValueModal, setShowAddValueModal] = useState(false)
  const [addValuePrefill, setAddValuePrefill] = useState<string>('')
  const [showAddAliasModal, setShowAddAliasModal] = useState<string | null>(null)
  const [includeSuggested, setIncludeSuggested] = useState(true)

  const loadCatalog = useCallback(async () => {
    if (!token) return
    setLoading(true)
    setError('')
    try {
      const data = await metadataApi.getCatalog(token)
      setCatalog(data)
    } catch (err: any) {
      setError(err.message || 'Failed to load metadata catalog')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    loadCatalog()
  }, [loadCatalog])

  const toggleNamespace = (ns: string) => {
    setExpandedNamespaces(prev => {
      const next = new Set(prev)
      if (next.has(ns)) next.delete(ns)
      else next.add(ns)
      return next
    })
  }

  const toggleFacet = (facet: string) => {
    setExpandedFacets(prev => {
      const next = new Set(prev)
      if (next.has(facet)) next.delete(facet)
      else next.add(facet)
      return next
    })
  }

  const showMessage = (msg: string) => {
    setActionMessage(msg)
    setTimeout(() => setActionMessage(''), 3000)
  }

  const handleCreateField = async (namespace: string, data: MetadataFieldCreateRequest) => {
    await metadataApi.createField(token ?? undefined, namespace, data)
    showMessage(`Field "${data.field_name}" created in ${namespace}`)
    await loadCatalog()
  }

  const handleDeleteField = async (namespace: string, fieldName: string) => {
    if (!confirm(`Deactivate field "${namespace}.${fieldName}"?`)) return
    try {
      await metadataApi.deleteField(token ?? undefined, namespace, fieldName)
      showMessage(`Field "${fieldName}" deactivated`)
      await loadCatalog()
    } catch (err: any) {
      setError(err.message || 'Failed to deactivate field')
    }
  }

  const handleCreateFacet = async (data: FacetCreateRequest) => {
    await metadataApi.createFacet(token ?? undefined, data)
    showMessage(`Facet "${data.facet_name}" created`)
    await loadCatalog()
  }

  const handleDeleteFacet = async (facetName: string) => {
    if (!confirm(`Deactivate facet "${facetName}"?`)) return
    try {
      await metadataApi.deleteFacet(token ?? undefined, facetName)
      showMessage(`Facet "${facetName}" deactivated`)
      await loadCatalog()
    } catch (err: any) {
      setError(err.message || 'Failed to deactivate facet')
    }
  }

  const handleInvalidateCache = async () => {
    try {
      await metadataApi.invalidateCache(token ?? undefined)
      showMessage('Cache invalidated')
      await loadCatalog()
    } catch (err: any) {
      setError(err.message || 'Failed to invalidate cache')
    }
  }

  // Reference Data facets (those with has_reference_data in their definition)
  // We identify them by facet_name — agency and set_aside are the known ones
  const refFacets = catalog?.facets.filter(f =>
    ['agency', 'set_aside'].includes(f.facet_name)
  ) || []

  const loadRefValues = useCallback(async (facetName: string) => {
    if (!token || !facetName) return
    setRefLoading(true)
    try {
      const values = await metadataApi.getReferenceValues(token, facetName, includeSuggested)
      setRefValues(values)
    } catch (err: any) {
      setError(err.message || 'Failed to load reference values')
    } finally {
      setRefLoading(false)
    }
  }, [token, includeSuggested])

  const loadPendingSuggestions = useCallback(async () => {
    if (!token) return
    try {
      const data = await metadataApi.getPendingSuggestionCount(token)
      setPendingSuggestions(data)
    } catch {
      // Non-critical
    }
  }, [token])

  useEffect(() => {
    if (activeTab === 'reference' && selectedRefFacet) {
      loadRefValues(selectedRefFacet)
    }
  }, [activeTab, selectedRefFacet, loadRefValues])

  useEffect(() => {
    if (activeTab === 'reference') {
      loadPendingSuggestions()
    }
  }, [activeTab, loadPendingSuggestions])

  // Auto-select first ref facet
  useEffect(() => {
    if (activeTab === 'reference' && !selectedRefFacet && refFacets.length > 0) {
      setSelectedRefFacet(refFacets[0].facet_name)
    }
  }, [activeTab, selectedRefFacet, refFacets])

  const toggleRefExpanded = (id: string) => {
    setRefExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleDiscover = async () => {
    if (!token || !selectedRefFacet) return
    setDiscovering(true)
    try {
      const result = await metadataApi.discoverReferenceValues(token, selectedRefFacet)
      setDiscoverResults(result)
      if (result.error) {
        showMessage(`Discovery found ${result.unmapped_count} unmapped values (LLM: ${result.error})`)
      } else {
        showMessage(`Discovery complete: ${result.unmapped_count} unmapped, ${result.suggestions.length} suggestions`)
      }
      await loadRefValues(selectedRefFacet)
      await loadPendingSuggestions()
    } catch (err: any) {
      setError(err.message || 'Discovery failed')
    } finally {
      setDiscovering(false)
    }
  }

  const handleSyncToYaml = async () => {
    if (!token) return
    setSyncing(true)
    try {
      const result = await metadataApi.exportReferenceBaseline(token)
      showMessage(`Synced to YAML: ${result.facets_exported} facets, ${result.values_exported} values, ${result.aliases_exported} aliases`)
    } catch (err: any) {
      setError(err.message || 'Sync to YAML failed')
    } finally {
      setSyncing(false)
    }
  }

  const handleSyncFacetsToYaml = async () => {
    if (!token) return
    setSyncingFacets(true)
    try {
      const result = await metadataApi.exportFacetsBaseline(token)
      showMessage(`Synced to YAML: ${result.facets_exported} facets, ${result.mappings_exported} mappings`)
    } catch (err: any) {
      setError(err.message || 'Sync facets to YAML failed')
    } finally {
      setSyncingFacets(false)
    }
  }

  const handleRebuildFromYaml = async () => {
    if (!token) return
    setRebuilding(true)
    try {
      const result = await metadataApi.rebuildFromYaml(token)
      showMessage(
        `Rebuilt from YAML: ${result.fields_synced} fields, ${result.facets_synced} facets, ` +
        `${result.mappings_synced} mappings, ${result.reference_values_seeded} ref values, ` +
        `${result.reference_aliases_seeded} ref aliases`
      )
      await loadCatalog()
    } catch (err: any) {
      setError(err.message || 'Rebuild from YAML failed')
    } finally {
      setRebuilding(false)
    }
  }

  const handleLinkToExisting = async (unmappedValue: string, existingValueId: string) => {
    if (!token || !selectedRefFacet) return
    try {
      await metadataApi.addReferenceAlias(token, selectedRefFacet, existingValueId, { alias_value: unmappedValue })
      showMessage(`Linked "${unmappedValue}" as alias`)
      // Remove from unmapped list
      if (discoverResults) {
        setDiscoverResults({
          ...discoverResults,
          unmapped_values: discoverResults.unmapped_values.filter(v => v.value !== unmappedValue),
          unmapped_count: discoverResults.unmapped_count - 1,
        })
      }
      await loadRefValues(selectedRefFacet)
    } catch (err: any) {
      setError(err.message || 'Failed to link value')
    }
  }

  const handleAddAsNew = (unmappedValue: string) => {
    setAddValuePrefill(unmappedValue)
    setShowAddValueModal(true)
  }

  const handleApproveSuggestion = async (suggestion: any) => {
    if (!token || !selectedRefFacet) return
    try {
      // Find the DB-stored suggested value by matching canonical_value
      // (suggest_groupings stores them with status='suggested')
      // Reload with suggested included to find it
      const allValues = await metadataApi.getReferenceValues(token, selectedRefFacet, true)
      const dbEntry = allValues.find(
        (v: FacetReferenceValue) => v.status === 'suggested' &&
        v.canonical_value.toLowerCase() === suggestion.canonical_value.toLowerCase()
      )

      if (dbEntry) {
        // Approve the existing suggested entry
        await metadataApi.approveReferenceValue(token, selectedRefFacet, dbEntry.id)
      } else {
        // Fallback: create directly if not found (e.g., existing_canonical_match suggestions)
        await metadataApi.createReferenceValue(token, selectedRefFacet, {
          canonical_value: suggestion.canonical_value,
          display_label: suggestion.display_label || undefined,
          aliases: suggestion.aliases || [],
        })
      }

      showMessage(`Approved "${suggestion.canonical_value}"`)
      // Remove from suggestions list
      if (discoverResults) {
        setDiscoverResults({
          ...discoverResults,
          suggestions: discoverResults.suggestions.filter(s => s.canonical_value !== suggestion.canonical_value),
        })
      }
      await loadRefValues(selectedRefFacet)
      await loadPendingSuggestions()
    } catch (err: any) {
      setError(err.message || 'Failed to approve suggestion')
    }
  }

  const handleRejectSuggestion = async (suggestion: any) => {
    if (!token || !selectedRefFacet) return
    try {
      // Find the DB-stored suggested value to reject it properly
      const allValues = await metadataApi.getReferenceValues(token, selectedRefFacet, true)
      const dbEntry = allValues.find(
        (v: FacetReferenceValue) => v.status === 'suggested' &&
        v.canonical_value.toLowerCase() === suggestion.canonical_value.toLowerCase()
      )

      if (dbEntry) {
        await metadataApi.rejectReferenceValue(token, selectedRefFacet, dbEntry.id)
      }
    } catch {
      // Non-critical — just remove from UI
    }

    if (discoverResults) {
      setDiscoverResults({
        ...discoverResults,
        suggestions: discoverResults.suggestions.filter(s => s.canonical_value !== suggestion.canonical_value),
      })
    }
    await loadRefValues(selectedRefFacet)
  }

  const handleApprove = async (valueId: string) => {
    if (!token || !selectedRefFacet) return
    try {
      await metadataApi.approveReferenceValue(token, selectedRefFacet, valueId)
      showMessage('Value approved')
      await loadRefValues(selectedRefFacet)
      await loadPendingSuggestions()
    } catch (err: any) {
      setError(err.message || 'Failed to approve')
    }
  }

  const handleReject = async (valueId: string) => {
    if (!token || !selectedRefFacet) return
    try {
      await metadataApi.rejectReferenceValue(token, selectedRefFacet, valueId)
      showMessage('Value rejected')
      await loadRefValues(selectedRefFacet)
      await loadPendingSuggestions()
    } catch (err: any) {
      setError(err.message || 'Failed to reject')
    }
  }

  const handleDeleteRefValue = async (valueId: string) => {
    if (!token || !selectedRefFacet) return
    if (!confirm('Deactivate this reference value?')) return
    try {
      await metadataApi.deleteReferenceValue(token, selectedRefFacet, valueId)
      showMessage('Value deactivated')
      await loadRefValues(selectedRefFacet)
    } catch (err: any) {
      setError(err.message || 'Failed to deactivate')
    }
  }

  const handleCreateRefValue = async (data: { canonical_value: string; display_label?: string; description?: string; aliases?: string[] }) => {
    if (!token || !selectedRefFacet) return
    await metadataApi.createReferenceValue(token, selectedRefFacet, data)
    showMessage(`Value "${data.canonical_value}" created`)
    // Remove from unmapped list if it came from discovery
    if (discoverResults) {
      setDiscoverResults({
        ...discoverResults,
        unmapped_values: discoverResults.unmapped_values.filter(v => v.value !== data.canonical_value),
        unmapped_count: Math.max(0, discoverResults.unmapped_count - 1),
      })
    }
    setAddValuePrefill('')
    await loadRefValues(selectedRefFacet)
  }

  const handleAddAlias = async (valueId: string, aliasValue: string, sourceHint?: string) => {
    if (!token || !selectedRefFacet) return
    await metadataApi.addReferenceAlias(token, selectedRefFacet, valueId, { alias_value: aliasValue, source_hint: sourceHint })
    showMessage(`Alias "${aliasValue}" added`)
    await loadRefValues(selectedRefFacet)
  }

  const handleRemoveAlias = async (valueId: string, aliasId: string) => {
    if (!token || !selectedRefFacet) return
    await metadataApi.removeReferenceAlias(token, selectedRefFacet, valueId, aliasId)
    showMessage('Alias removed')
    await loadRefValues(selectedRefFacet)
  }

  return (
    <ProtectedRoute requiredRole="org_admin">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-indigo-100 dark:bg-indigo-900/30 rounded-lg">
              <Database className="w-6 h-6 text-indigo-600 dark:text-indigo-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Metadata Catalog</h1>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Manage namespaces, fields, and facet definitions
                {catalog && ` \u2014 ${catalog.total_indexed_docs.toLocaleString()} indexed documents`}
              </p>
            </div>
          </div>
          <button
            onClick={handleInvalidateCache}
            className="flex items-center space-x-2 px-3 py-2 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-md border border-gray-200 dark:border-gray-700"
          >
            <RefreshCw className="w-4 h-4" />
            <span>Refresh Cache</span>
          </button>
        </div>

        {actionMessage && (
          <div className="mb-4 p-3 bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400 rounded-lg text-sm">
            {actionMessage}
          </div>
        )}

        {error && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 rounded-lg text-sm">
            {error}
          </div>
        )}

        {/* Tabs */}
        <div className="border-b border-gray-200 dark:border-gray-700 mb-6">
          <div className="flex items-center justify-between">
            <nav className="-mb-px flex space-x-8">
              <button
                onClick={() => setActiveTab('namespaces')}
                className={`flex items-center py-3 px-1 border-b-2 font-medium text-sm ${
                  activeTab === 'namespaces'
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'
                }`}
              >
                <BookOpen className="w-4 h-4 mr-2" />
                Namespaces & Fields
                {catalog && <span className="ml-2 text-xs bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-full">{catalog.namespaces.length}</span>}
              </button>
              <button
                onClick={() => setActiveTab('facets')}
                className={`flex items-center py-3 px-1 border-b-2 font-medium text-sm ${
                  activeTab === 'facets'
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'
                }`}
              >
                <Filter className="w-4 h-4 mr-2" />
                Facets
                {catalog && <span className="ml-2 text-xs bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-full">{catalog.facets.length}</span>}
              </button>
              <button
                onClick={() => setActiveTab('reference')}
                className={`flex items-center py-3 px-1 border-b-2 font-medium text-sm ${
                  activeTab === 'reference'
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'
                }`}
              >
                <Link2 className="w-4 h-4 mr-2" />
                Reference Data
                {pendingSuggestions && pendingSuggestions.total > 0 && (
                  <span className="ml-2 text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 px-2 py-0.5 rounded-full">
                    {pendingSuggestions.total} pending
                  </span>
                )}
              </button>
            </nav>
            <button
              onClick={handleRebuildFromYaml}
              disabled={rebuilding}
              className="flex items-center space-x-2 px-3 py-1.5 mb-1 text-sm border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
              title="Flush and rebuild metadata catalog in DB from YAML baseline files"
            >
              {rebuilding ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
              <span>{rebuilding ? 'Rebuilding...' : 'Rebuild from YAML'}</span>
            </button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
          </div>
        ) : catalog && (
          <>
            {/* Namespaces Tab */}
            {activeTab === 'namespaces' && (
              <div className="space-y-3">
                {catalog.namespaces.map((ns) => (
                  <div key={ns.namespace} className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                    <button
                      onClick={() => toggleNamespace(ns.namespace)}
                      className="w-full flex items-center justify-between p-4 hover:bg-gray-50 dark:hover:bg-gray-800/50"
                    >
                      <div className="flex items-center space-x-3">
                        {expandedNamespaces.has(ns.namespace) ? (
                          <ChevronDown className="w-4 h-4 text-gray-400" />
                        ) : (
                          <ChevronRight className="w-4 h-4 text-gray-400" />
                        )}
                        <span className="font-mono text-sm font-semibold text-indigo-600 dark:text-indigo-400">
                          {ns.namespace}
                        </span>
                        <span className="text-sm text-gray-500 dark:text-gray-400">
                          {ns.display_name}
                        </span>
                      </div>
                      <div className="flex items-center space-x-4 text-xs text-gray-500">
                        <span>{ns.fields.length} fields</span>
                        <span>{ns.doc_count.toLocaleString()} docs</span>
                      </div>
                    </button>

                    {expandedNamespaces.has(ns.namespace) && (
                      <div className="border-t border-gray-200 dark:border-gray-700">
                        {ns.description && (
                          <p className="px-4 py-2 text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800/30">
                            {ns.description}
                          </p>
                        )}

                        {/* Add Field button */}
                        <div className="px-4 py-2 bg-gray-50 dark:bg-gray-800/30 border-b border-gray-100 dark:border-gray-800">
                          <button
                            onClick={(e) => { e.stopPropagation(); setShowAddFieldModal(ns.namespace) }}
                            className="flex items-center space-x-1 text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-700"
                          >
                            <Plus className="w-3 h-3" />
                            <span>Add Org Field</span>
                          </button>
                        </div>

                        <table className="w-full text-sm">
                          <thead className="bg-gray-50 dark:bg-gray-800/50">
                            <tr>
                              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Field</th>
                              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                              <th className="px-4 py-2 text-center text-xs font-medium text-gray-500 uppercase">Indexed</th>
                              <th className="px-4 py-2 text-center text-xs font-medium text-gray-500 uppercase">Facetable</th>
                              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Content Types</th>
                              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                              <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase w-16">Actions</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                            {ns.fields.map((field) => {
                              const Icon = dataTypeIcons[field.data_type] || Type
                              return (
                                <tr key={field.field_name} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                                  <td className="px-4 py-2 font-mono text-xs text-gray-900 dark:text-gray-200">
                                    {field.field_name}
                                  </td>
                                  <td className="px-4 py-2">
                                    <span className="inline-flex items-center space-x-1 text-xs text-gray-600 dark:text-gray-400">
                                      <Icon className="w-3 h-3" />
                                      <span>{field.data_type}</span>
                                    </span>
                                  </td>
                                  <td className="px-4 py-2 text-center">
                                    {field.indexed ? (
                                      <span className="text-emerald-500">Y</span>
                                    ) : (
                                      <span className="text-gray-300">-</span>
                                    )}
                                  </td>
                                  <td className="px-4 py-2 text-center">
                                    {field.facetable ? (
                                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400">
                                        <Filter className="w-3 h-3 mr-1" />
                                        Yes
                                      </span>
                                    ) : (
                                      <span className="text-gray-300">-</span>
                                    )}
                                  </td>
                                  <td className="px-4 py-2 text-xs text-gray-500 dark:text-gray-400">
                                    {field.applicable_content_types.join(', ')}
                                  </td>
                                  <td className="px-4 py-2 text-xs text-gray-500 dark:text-gray-400 max-w-xs truncate">
                                    {field.description}
                                  </td>
                                  <td className="px-4 py-2 text-right">
                                    <button
                                      onClick={() => handleDeleteField(ns.namespace, field.field_name)}
                                      className="text-gray-400 hover:text-red-500"
                                      title="Deactivate field"
                                    >
                                      <Trash2 className="w-3.5 h-3.5" />
                                    </button>
                                  </td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Facets Tab */}
            {activeTab === 'facets' && (
              <div className="space-y-3">
                {/* Facets controls bar */}
                <div className="flex justify-end space-x-2">
                  <button
                    onClick={handleSyncFacetsToYaml}
                    disabled={syncingFacets}
                    className="flex items-center space-x-2 px-3 py-2 text-sm bg-gray-600 text-white rounded-md hover:bg-gray-700 disabled:opacity-50"
                    title="Export facet definitions to YAML baseline file"
                  >
                    {syncingFacets ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                    <span>{syncingFacets ? 'Syncing...' : 'Sync to YAML'}</span>
                  </button>
                  <button
                    onClick={() => setShowAddFacetModal(true)}
                    className="flex items-center space-x-2 px-3 py-2 text-sm bg-purple-600 text-white rounded-md hover:bg-purple-700"
                  >
                    <Plus className="w-4 h-4" />
                    <span>Add Org Facet</span>
                  </button>
                </div>

                {catalog.facets.map((facet) => (
                  <div key={facet.facet_name} className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                    <div
                      onClick={() => toggleFacet(facet.facet_name)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleFacet(facet.facet_name); } }}
                      className="w-full flex items-center justify-between p-4 hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer"
                    >
                      <div className="flex items-center space-x-3">
                        {expandedFacets.has(facet.facet_name) ? (
                          <ChevronDown className="w-4 h-4 text-gray-400" />
                        ) : (
                          <ChevronRight className="w-4 h-4 text-gray-400" />
                        )}
                        <Filter className="w-4 h-4 text-purple-500" />
                        <span className="font-mono text-sm font-semibold text-purple-600 dark:text-purple-400">
                          {facet.facet_name}
                        </span>
                        <span className="text-sm text-gray-500 dark:text-gray-400">
                          {facet.display_name}
                        </span>
                      </div>
                      <div className="flex items-center space-x-2 text-xs text-gray-500">
                        <span className="bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded">{facet.data_type}</span>
                        <span>{facet.mappings.length} mappings</span>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeleteFacet(facet.facet_name) }}
                          className="ml-2 text-gray-400 hover:text-red-500"
                          title="Deactivate facet"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>

                    {expandedFacets.has(facet.facet_name) && (
                      <div className="border-t border-gray-200 dark:border-gray-700 p-4 space-y-3">
                        {facet.description && (
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            {facet.description}
                          </p>
                        )}
                        <div className="flex items-center space-x-2 text-xs">
                          <span className="text-gray-500">Operators:</span>
                          {facet.operators.map(op => (
                            <span key={op} className="bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded font-mono">
                              {op}
                            </span>
                          ))}
                        </div>
                        <div>
                          <h4 className="text-xs font-medium text-gray-500 uppercase mb-2">Cross-Domain Mappings</h4>
                          <div className="space-y-1">
                            {facet.mappings.map(m => (
                              <div key={m.content_type} className="flex items-center space-x-2 text-xs">
                                <span className="font-mono bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded min-w-[140px]">
                                  {m.content_type}
                                </span>
                                <ArrowRight className="w-3 h-3 text-gray-400" />
                                <span className="font-mono text-indigo-600 dark:text-indigo-400">
                                  {m.json_path}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Reference Data Tab */}
            {activeTab === 'reference' && (
              <div className="space-y-4">
                {/* Controls bar */}
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center space-x-3">
                    <label className="text-sm text-gray-500 dark:text-gray-400">Facet:</label>
                    <select
                      value={selectedRefFacet}
                      onChange={(e) => { setSelectedRefFacet(e.target.value); setRefExpandedIds(new Set()); setDiscoverResults(null) }}
                      className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
                    >
                      {refFacets.map(f => (
                        <option key={f.facet_name} value={f.facet_name}>
                          {f.display_name} ({f.facet_name})
                          {pendingSuggestions?.facets[f.facet_name] ? ` \u2014 ${pendingSuggestions.facets[f.facet_name]} pending` : ''}
                        </option>
                      ))}
                    </select>
                    <label className="flex items-center space-x-1.5 text-xs text-gray-500">
                      <input
                        type="checkbox"
                        checked={includeSuggested}
                        onChange={(e) => setIncludeSuggested(e.target.checked)}
                        className="rounded"
                      />
                      <span>Show suggested</span>
                    </label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={handleSyncToYaml}
                      disabled={syncing}
                      className="flex items-center space-x-2 px-3 py-1.5 text-sm bg-gray-600 text-white rounded-md hover:bg-gray-700 disabled:opacity-50"
                      title="Export reference data to YAML baseline file"
                    >
                      {syncing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                      <span>{syncing ? 'Syncing...' : 'Sync to YAML'}</span>
                    </button>
                    <button
                      onClick={handleDiscover}
                      disabled={discovering || !selectedRefFacet}
                      className="flex items-center space-x-2 px-3 py-1.5 text-sm bg-amber-600 text-white rounded-md hover:bg-amber-700 disabled:opacity-50"
                    >
                      {discovering ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                      <span>{discovering ? 'Discovering...' : 'Discover Values'}</span>
                    </button>
                    <button
                      onClick={() => setShowAddValueModal(true)}
                      disabled={!selectedRefFacet}
                      className="flex items-center space-x-2 px-3 py-1.5 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
                    >
                      <Plus className="w-4 h-4" />
                      <span>Add Value</span>
                    </button>
                  </div>
                </div>

                {/* Discovery Results Panel */}
                {discoverResults && (discoverResults.suggestions.length > 0 || discoverResults.unmapped_values.length > 0) && (
                  <div className="border border-amber-200 dark:border-amber-800 rounded-lg bg-amber-50 dark:bg-amber-900/20 overflow-hidden">
                    <div className="flex items-center justify-between px-4 py-3 border-b border-amber-200 dark:border-amber-800">
                      <div className="flex items-center space-x-2">
                        <Sparkles className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                        <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-200">
                          {discoverResults.suggestions.length > 0 ? 'Review Suggestions' : 'Unmapped Values'}
                        </h3>
                        <span className="text-xs text-amber-600 dark:text-amber-400">
                          {discoverResults.suggestions.length > 0
                            ? `${discoverResults.suggestions.length} suggestions`
                            : `${discoverResults.unmapped_values.length} unmapped`}
                        </span>
                      </div>
                      <button
                        onClick={() => setDiscoverResults(null)}
                        className="text-amber-400 hover:text-amber-600 dark:hover:text-amber-200"
                        title="Dismiss"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>

                    {discoverResults.error && (
                      <div className="px-4 py-2 bg-amber-100 dark:bg-amber-900/40 flex items-center space-x-2 text-xs text-amber-800 dark:text-amber-300">
                        <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                        <span>{discoverResults.error} — showing raw values for manual review</span>
                      </div>
                    )}

                    <div className="px-4 py-3 space-y-2 max-h-96 overflow-y-auto">
                      {/* Mode A: LLM suggestions */}
                      {discoverResults.suggestions.length > 0 && (
                        <>
                          {discoverResults.suggestions.filter(s => s.confidence >= 0.9).length > 1 && (
                            <div className="flex justify-end mb-2">
                              <button
                                onClick={async () => {
                                  const highConf = discoverResults.suggestions.filter(s => s.confidence >= 0.9)
                                  for (const s of highConf) {
                                    await handleApproveSuggestion(s)
                                  }
                                }}
                                className="text-xs px-2.5 py-1 bg-emerald-600 text-white rounded hover:bg-emerald-700"
                              >
                                Approve All High-Confidence ({discoverResults.suggestions.filter(s => s.confidence >= 0.9).length})
                              </button>
                            </div>
                          )}
                          {discoverResults.suggestions.map((suggestion, idx) => (
                            <div key={idx} className="flex items-center justify-between p-2.5 bg-white dark:bg-gray-800 rounded-md border border-gray-200 dark:border-gray-700">
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center space-x-2">
                                  <span className="text-sm font-medium text-gray-900 dark:text-white truncate">
                                    {suggestion.canonical_value}
                                  </span>
                                  {suggestion.display_label && (
                                    <span className="text-xs bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 px-1.5 py-0.5 rounded flex-shrink-0">
                                      {suggestion.display_label}
                                    </span>
                                  )}
                                  {suggestion.confidence != null && (
                                    <span className={`text-xs px-1.5 py-0.5 rounded flex-shrink-0 ${
                                      suggestion.confidence >= 0.9
                                        ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
                                        : suggestion.confidence >= 0.7
                                        ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400'
                                        : 'bg-gray-100 dark:bg-gray-800 text-gray-500'
                                    }`}>
                                      {Math.round(suggestion.confidence * 100)}%
                                    </span>
                                  )}
                                </div>
                                {suggestion.aliases && suggestion.aliases.length > 0 && (
                                  <div className="mt-1 flex flex-wrap gap-1">
                                    {suggestion.aliases.map((alias: string, aIdx: number) => (
                                      <span key={aIdx} className="text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 px-1.5 py-0.5 rounded font-mono">
                                        {alias}
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>
                              <div className="flex items-center space-x-1.5 ml-3 flex-shrink-0">
                                <button
                                  onClick={() => handleApproveSuggestion(suggestion)}
                                  className="text-emerald-500 hover:text-emerald-700 p-1"
                                  title="Approve"
                                >
                                  <Check className="w-4 h-4" />
                                </button>
                                <button
                                  onClick={() => handleRejectSuggestion(suggestion)}
                                  className="text-red-400 hover:text-red-600 p-1"
                                  title="Reject"
                                >
                                  <XCircle className="w-4 h-4" />
                                </button>
                              </div>
                            </div>
                          ))}
                        </>
                      )}

                      {/* Mode B: Unmapped values (no LLM suggestions) */}
                      {discoverResults.suggestions.length === 0 && discoverResults.unmapped_values.length > 0 && (
                        <>
                          {discoverResults.unmapped_values.map((item, idx) => (
                            <div key={idx} className="flex items-center justify-between p-2.5 bg-white dark:bg-gray-800 rounded-md border border-gray-200 dark:border-gray-700">
                              <div className="flex items-center space-x-2 min-w-0">
                                <span className="text-sm text-gray-900 dark:text-white font-mono truncate">
                                  {item.value}
                                </span>
                                <span className="text-xs bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 px-1.5 py-0.5 rounded flex-shrink-0">
                                  {item.count} docs
                                </span>
                              </div>
                              <div className="flex items-center space-x-1.5 ml-3 flex-shrink-0">
                                <button
                                  onClick={() => handleAddAsNew(item.value)}
                                  className="text-xs px-2 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700"
                                >
                                  Add as New
                                </button>
                                {refValues.length > 0 && (
                                  <select
                                    key={`link-${item.value}`}
                                    value=""
                                    onChange={(e) => {
                                      if (e.target.value) {
                                        handleLinkToExisting(item.value, e.target.value)
                                      }
                                    }}
                                    className="text-xs px-2 py-1 border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300"
                                  >
                                    <option value="">Link to Existing...</option>
                                    {refValues.filter(rv => rv.status === 'active').map(rv => (
                                      <option key={rv.id} value={rv.id}>
                                        {rv.display_label || rv.canonical_value}
                                      </option>
                                    ))}
                                  </select>
                                )}
                              </div>
                            </div>
                          ))}
                        </>
                      )}
                    </div>
                  </div>
                )}

                {/* Reference values list */}
                {refLoading ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
                  </div>
                ) : refValues.length === 0 ? (
                  <div className="text-center py-12 text-gray-500 dark:text-gray-400">
                    <Link2 className="w-8 h-8 mx-auto mb-3 opacity-40" />
                    <p className="text-sm">No reference values for this facet yet.</p>
                    <p className="text-xs mt-1">Click &ldquo;Add Value&rdquo; to create one, or &ldquo;Discover Values&rdquo; to scan indexed data.</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {refValues.map(rv => (
                      <div key={rv.id} className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                        {/* Canonical value row */}
                        <div
                          onClick={() => toggleRefExpanded(rv.id)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleRefExpanded(rv.id); } }}
                          className="w-full flex items-center justify-between p-3 hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer"
                        >
                          <div className="flex items-center space-x-3">
                            {refExpandedIds.has(rv.id) ? (
                              <ChevronDown className="w-4 h-4 text-gray-400" />
                            ) : (
                              <ChevronRight className="w-4 h-4 text-gray-400" />
                            )}
                            <div>
                              <span className="text-sm font-medium text-gray-900 dark:text-white">
                                {rv.canonical_value}
                              </span>
                              {rv.display_label && (
                                <span className="ml-2 text-xs bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 px-1.5 py-0.5 rounded">
                                  {rv.display_label}
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="flex items-center space-x-2">
                            <span className={`text-xs px-2 py-0.5 rounded-full ${
                              rv.status === 'active'
                                ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
                                : rv.status === 'suggested'
                                ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400'
                                : 'bg-gray-100 dark:bg-gray-800 text-gray-500'
                            }`}>
                              {rv.status}
                            </span>
                            <span className="text-xs text-gray-400">{rv.aliases.length} aliases</span>
                            {rv.status === 'suggested' && (
                              <>
                                <button
                                  onClick={(e) => { e.stopPropagation(); handleApprove(rv.id) }}
                                  className="text-emerald-500 hover:text-emerald-700"
                                  title="Approve"
                                >
                                  <Check className="w-4 h-4" />
                                </button>
                                <button
                                  onClick={(e) => { e.stopPropagation(); handleReject(rv.id) }}
                                  className="text-red-400 hover:text-red-600"
                                  title="Reject"
                                >
                                  <XCircle className="w-4 h-4" />
                                </button>
                              </>
                            )}
                            <button
                              onClick={(e) => { e.stopPropagation(); handleDeleteRefValue(rv.id) }}
                              className="text-gray-400 hover:text-red-500"
                              title="Deactivate"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>

                        {/* Expanded aliases */}
                        {refExpandedIds.has(rv.id) && (
                          <div className="border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/30 p-3">
                            {rv.description && (
                              <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">{rv.description}</p>
                            )}
                            <div className="flex items-center justify-between mb-2">
                              <h4 className="text-xs font-medium text-gray-500 uppercase">Aliases</h4>
                              <button
                                onClick={() => setShowAddAliasModal(rv.id)}
                                className="flex items-center text-xs text-indigo-600 hover:text-indigo-700"
                              >
                                <Plus className="w-3 h-3 mr-1" /> Add Alias
                              </button>
                            </div>
                            <div className="space-y-1">
                              {rv.aliases.map(alias => (
                                <div key={alias.id} className="flex items-center justify-between text-xs py-1 px-2 rounded hover:bg-gray-100 dark:hover:bg-gray-700/50">
                                  <div className="flex items-center space-x-2">
                                    <span className="text-gray-900 dark:text-gray-200 font-mono">{alias.alias_value}</span>
                                    {alias.source_hint && (
                                      <span className="text-gray-400 bg-gray-200 dark:bg-gray-700 px-1.5 py-0.5 rounded">
                                        {alias.source_hint}
                                      </span>
                                    )}
                                    {alias.match_method && alias.match_method !== 'baseline' && alias.match_method !== 'manual' && (
                                      <span className={`px-1.5 py-0.5 rounded ${
                                        alias.match_method === 'auto_matched'
                                          ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400'
                                          : 'bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400'
                                      }`}>
                                        {alias.match_method}
                                        {alias.confidence ? ` (${Math.round(alias.confidence * 100)}%)` : ''}
                                      </span>
                                    )}
                                  </div>
                                  <button
                                    onClick={() => handleRemoveAlias(rv.id, alias.id)}
                                    className="text-gray-300 hover:text-red-500"
                                    title="Remove alias"
                                  >
                                    <X className="w-3.5 h-3.5" />
                                  </button>
                                </div>
                              ))}
                              {rv.aliases.length === 0 && (
                                <p className="text-xs text-gray-400 italic">No aliases defined</p>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {/* Modals */}
        {showAddFieldModal && (
          <AddFieldModal
            namespace={showAddFieldModal}
            onClose={() => setShowAddFieldModal(null)}
            onSave={(data) => handleCreateField(showAddFieldModal!, data)}
          />
        )}

        {showAddFacetModal && (
          <AddFacetModal
            onClose={() => setShowAddFacetModal(false)}
            onSave={handleCreateFacet}
          />
        )}

        {showAddValueModal && (
          <AddRefValueModal
            facetName={selectedRefFacet}
            initialCanonicalValue={addValuePrefill}
            onClose={() => { setShowAddValueModal(false); setAddValuePrefill('') }}
            onSave={handleCreateRefValue}
          />
        )}

        {showAddAliasModal && (
          <AddAliasModal
            onClose={() => setShowAddAliasModal(null)}
            onSave={(aliasValue, sourceHint) => handleAddAlias(showAddAliasModal, aliasValue, sourceHint)}
          />
        )}
      </div>
    </ProtectedRoute>
  )
}

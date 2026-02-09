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
// Main Page
// =============================================================================

export default function MetadataCatalogPage() {
  const { token } = useAuth()
  const [catalog, setCatalog] = useState<MetadataCatalog | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expandedNamespaces, setExpandedNamespaces] = useState<Set<string>>(new Set())
  const [expandedFacets, setExpandedFacets] = useState<Set<string>>(new Set())
  const [activeTab, setActiveTab] = useState<'namespaces' | 'facets'>('namespaces')
  const [showAddFieldModal, setShowAddFieldModal] = useState<string | null>(null)
  const [showAddFacetModal, setShowAddFacetModal] = useState(false)
  const [actionMessage, setActionMessage] = useState('')

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
          </nav>
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
                {/* Add Facet button */}
                <div className="flex justify-end">
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
      </div>
    </ProtectedRoute>
  )
}

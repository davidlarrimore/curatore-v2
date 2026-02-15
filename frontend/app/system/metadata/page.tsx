'use client'

/**
 * System-scoped metadata catalog admin page.
 * Manage the global baseline: namespaces, fields, facets, reference data, and admin tools.
 */

import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '@/lib/auth-context'
import {
  systemMetadataApi,
  type MetadataCatalog,
  type MetadataNamespace,
  type MetadataFieldDefinition,
  type FacetDefinition,
  type FacetReferenceValue,
  type OrgOverrideSummary,
  type JsonRecord,
} from '@/lib/api'
import { Button } from '@/components/ui/Button'
import {
  RefreshCw,
  Database,
  Layers,
  Filter,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Loader2,
  Search,
  Tag,
  Hash,
  Type,
  Calendar,
  ToggleLeft,
  FileText,
  Box,
  Plus,
  Trash2,
  Edit3,
  BookOpen,
  Settings,
  Download,
  Upload,
  Shield,
  Building2,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'

// ============================================================================
// Helpers
// ============================================================================

function getTypeIcon(dataType: string) {
  switch (dataType.toLowerCase()) {
    case 'string': case 'text': return Type
    case 'integer': case 'number': case 'float': return Hash
    case 'boolean': return ToggleLeft
    case 'date': case 'datetime': return Calendar
    case 'array': return Layers
    default: return Box
  }
}

function getTypeColor(dataType: string) {
  switch (dataType.toLowerCase()) {
    case 'string': case 'text':
      return 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20'
    case 'integer': case 'number': case 'float':
      return 'text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-900/20'
    case 'boolean':
      return 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20'
    case 'date': case 'datetime':
      return 'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20'
    case 'array':
      return 'text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-900/20'
    default:
      return 'text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-900/50'
  }
}

type ActiveTab = 'namespaces' | 'facets' | 'reference' | 'admin'

export default function SystemMetadataCatalogPage() {
  const { token } = useAuth()

  const [catalog, setCatalog] = useState<MetadataCatalog | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedNamespaces, setExpandedNamespaces] = useState<Set<string>>(new Set())
  const [activeTab, setActiveTab] = useState<ActiveTab>('namespaces')

  // Reference data state
  const [selectedFacetForRef, setSelectedFacetForRef] = useState<string>('')
  const [referenceValues, setReferenceValues] = useState<FacetReferenceValue[]>([])
  const [isLoadingRef, setIsLoadingRef] = useState(false)
  const [expandedValues, setExpandedValues] = useState<Set<string>>(new Set())

  // Admin state
  const [overrideSummary, setOverrideSummary] = useState<OrgOverrideSummary | null>(null)
  const [isLoadingOverrides, setIsLoadingOverrides] = useState(false)

  // Create field modal state
  const [showCreateField, setShowCreateField] = useState(false)
  const [createFieldNs, setCreateFieldNs] = useState('')
  const [newField, setNewField] = useState({ field_name: '', data_type: 'string', description: '', indexed: true, facetable: false })

  // Create facet modal state
  const [showCreateFacet, setShowCreateFacet] = useState(false)
  const [newFacet, setNewFacet] = useState({ facet_name: '', display_name: '', data_type: 'string', description: '' })

  // Create reference value modal state
  const [showCreateRefValue, setShowCreateRefValue] = useState(false)
  const [newRefValue, setNewRefValue] = useState({ canonical_value: '', display_label: '', description: '' })

  // Add alias modal state
  const [showAddAlias, setShowAddAlias] = useState(false)
  const [addAliasValueId, setAddAliasValueId] = useState('')
  const [newAlias, setNewAlias] = useState({ alias_value: '', source_hint: '' })

  const loadData = useCallback(async (silent = false) => {
    if (!token) return
    if (!silent) setIsLoading(true)
    setError('')
    try {
      const data = await systemMetadataApi.getCatalog()
      setCatalog(data)
      if (data.namespaces.length > 0 && expandedNamespaces.size === 0) {
        setExpandedNamespaces(new Set([data.namespaces[0].namespace]))
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load metadata catalog'
      if (!silent) setError(message)
    } finally {
      setIsLoading(false)
    }
  }, [token])

  useEffect(() => { if (token) loadData() }, [token, loadData])

  const loadReferenceValues = useCallback(async (facetName: string) => {
    if (!facetName) return
    setIsLoadingRef(true)
    try {
      const values = await systemMetadataApi.getReferenceValues(facetName, true)
      setReferenceValues(values)
    } catch {
      toast.error('Failed to load reference values')
    } finally {
      setIsLoadingRef(false)
    }
  }, [])

  useEffect(() => {
    if (activeTab === 'reference' && selectedFacetForRef) {
      loadReferenceValues(selectedFacetForRef)
    }
  }, [activeTab, selectedFacetForRef, loadReferenceValues])

  // Auto-select first facet for reference tab
  useEffect(() => {
    if (activeTab === 'reference' && !selectedFacetForRef && catalog?.facets.length) {
      setSelectedFacetForRef(catalog.facets[0].facet_name)
    }
  }, [activeTab, selectedFacetForRef, catalog])

  const loadOverrideSummary = useCallback(async () => {
    setIsLoadingOverrides(true)
    try {
      const summary = await systemMetadataApi.getOrgOverrideSummary()
      setOverrideSummary(summary)
    } catch {
      toast.error('Failed to load override summary')
    } finally {
      setIsLoadingOverrides(false)
    }
  }, [])

  useEffect(() => {
    if (activeTab === 'admin') loadOverrideSummary()
  }, [activeTab, loadOverrideSummary])

  const toggleNamespace = (namespace: string) => {
    const newExpanded = new Set(expandedNamespaces)
    if (newExpanded.has(namespace)) newExpanded.delete(namespace)
    else newExpanded.add(namespace)
    setExpandedNamespaces(newExpanded)
  }

  const toggleValue = (id: string) => {
    const newExpanded = new Set(expandedValues)
    if (newExpanded.has(id)) newExpanded.delete(id)
    else newExpanded.add(id)
    setExpandedValues(newExpanded)
  }

  // Filter helpers
  const filteredNamespaces = catalog?.namespaces.filter((ns) => {
    if (!searchQuery.trim()) return true
    const q = searchQuery.toLowerCase()
    if (ns.namespace.toLowerCase().includes(q)) return true
    if (ns.display_name.toLowerCase().includes(q)) return true
    return ns.fields.some(f => f.field_name.toLowerCase().includes(q) || f.description?.toLowerCase().includes(q))
  }) || []

  const filteredFacets = catalog?.facets.filter((f) => {
    if (!searchQuery.trim()) return true
    const q = searchQuery.toLowerCase()
    return f.facet_name.toLowerCase().includes(q) || f.display_name.toLowerCase().includes(q) || f.description?.toLowerCase().includes(q)
  }) || []

  // ---- CRUD handlers ----

  const handleCreateField = async () => {
    if (!newField.field_name || !createFieldNs) return
    try {
      await systemMetadataApi.createField(createFieldNs, {
        field_name: newField.field_name,
        data_type: newField.data_type,
        description: newField.description || undefined,
        indexed: newField.indexed,
        facetable: newField.facetable,
      })
      toast.success(`Field "${newField.field_name}" created`)
      setShowCreateField(false)
      setNewField({ field_name: '', data_type: 'string', description: '', indexed: true, facetable: false })
      loadData(true)
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Failed to create field')
    }
  }

  const handleDeleteField = async (namespace: string, fieldName: string) => {
    if (!confirm(`Deactivate field "${namespace}.${fieldName}"?`)) return
    try {
      await systemMetadataApi.deleteField(namespace, fieldName)
      toast.success(`Field "${fieldName}" deactivated`)
      loadData(true)
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Failed to deactivate field')
    }
  }

  const handleCreateFacet = async () => {
    if (!newFacet.facet_name || !newFacet.display_name) return
    try {
      await systemMetadataApi.createFacet({
        facet_name: newFacet.facet_name,
        display_name: newFacet.display_name,
        data_type: newFacet.data_type,
        description: newFacet.description || undefined,
      })
      toast.success(`Facet "${newFacet.facet_name}" created`)
      setShowCreateFacet(false)
      setNewFacet({ facet_name: '', display_name: '', data_type: 'string', description: '' })
      loadData(true)
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Failed to create facet')
    }
  }

  const handleDeleteFacet = async (facetName: string) => {
    if (!confirm(`Deactivate facet "${facetName}"?`)) return
    try {
      await systemMetadataApi.deleteFacet(facetName)
      toast.success(`Facet "${facetName}" deactivated`)
      loadData(true)
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Failed to deactivate facet')
    }
  }

  const handleCreateRefValue = async () => {
    if (!newRefValue.canonical_value || !selectedFacetForRef) return
    try {
      await systemMetadataApi.createReferenceValue(selectedFacetForRef, {
        canonical_value: newRefValue.canonical_value,
        display_label: newRefValue.display_label || undefined,
        description: newRefValue.description || undefined,
      })
      toast.success(`Reference value "${newRefValue.canonical_value}" created`)
      setShowCreateRefValue(false)
      setNewRefValue({ canonical_value: '', display_label: '', description: '' })
      loadReferenceValues(selectedFacetForRef)
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Failed to create reference value')
    }
  }

  const handleDeleteRefValue = async (valueId: string) => {
    if (!confirm('Deactivate this reference value?')) return
    try {
      await systemMetadataApi.deleteReferenceValue(selectedFacetForRef, valueId)
      toast.success('Reference value deactivated')
      loadReferenceValues(selectedFacetForRef)
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Failed to deactivate')
    }
  }

  const handleAddAlias = async () => {
    if (!newAlias.alias_value || !addAliasValueId) return
    try {
      await systemMetadataApi.addReferenceAlias(selectedFacetForRef, addAliasValueId, {
        alias_value: newAlias.alias_value,
        source_hint: newAlias.source_hint || undefined,
      })
      toast.success(`Alias "${newAlias.alias_value}" added`)
      setShowAddAlias(false)
      setNewAlias({ alias_value: '', source_hint: '' })
      loadReferenceValues(selectedFacetForRef)
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Failed to add alias')
    }
  }

  const handleRemoveAlias = async (valueId: string, aliasId: string) => {
    if (!confirm('Remove this alias?')) return
    try {
      await systemMetadataApi.removeReferenceAlias(selectedFacetForRef, valueId, aliasId)
      toast.success('Alias removed')
      loadReferenceValues(selectedFacetForRef)
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Failed to remove alias')
    }
  }

  // Admin actions
  const handleExportFacets = async () => {
    try {
      const result = await systemMetadataApi.exportFacetsBaseline()
      toast.success(`Exported ${result.facets_exported} facets, ${result.mappings_exported} mappings`)
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Export failed')
    }
  }

  const handleExportRefData = async () => {
    try {
      const result = await systemMetadataApi.exportReferenceBaseline()
      toast.success(`Exported ${result.values_exported} values, ${result.aliases_exported} aliases`)
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Export failed')
    }
  }

  const handleRebuild = async () => {
    if (!confirm('This will rebuild the entire metadata catalog from YAML. Org-level overrides are preserved. Continue?')) return
    try {
      const result = await systemMetadataApi.rebuildFromYaml()
      toast.success(`Rebuilt: ${result.fields_synced} fields, ${result.facets_synced} facets, ${result.reference_values_seeded} ref values`)
      loadData(true)
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Rebuild failed')
    }
  }

  const handleInvalidateCache = async () => {
    try {
      await systemMetadataApi.invalidateCache()
      toast.success('Cache invalidated')
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Cache invalidation failed')
    }
  }

  // ---- Render ----

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin" />
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading master metadata catalog...</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-start gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-amber-500 to-orange-600 text-white shadow-lg shadow-amber-500/25 flex-shrink-0">
                <Database className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  Master Metadata Catalog
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  System-wide metadata governance — global baseline definitions
                </p>
              </div>
            </div>
            <Button variant="secondary" onClick={() => loadData()} className="gap-2">
              <RefreshCw className="w-4 h-4" />
              Refresh
            </Button>
          </div>

          {error && (
            <div className="mt-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
              <div className="flex items-center gap-3">
                <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
                <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
              </div>
            </div>
          )}
        </div>

        {/* Stats */}
        {catalog && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center">
                  <Layers className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Namespaces</p>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">{catalog.namespaces.length}</p>
                </div>
              </div>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
                  <Tag className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Total Fields</p>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">
                    {catalog.namespaces.reduce((sum, ns) => sum + ns.fields.length, 0)}
                  </p>
                </div>
              </div>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-purple-50 dark:bg-purple-900/20 flex items-center justify-center">
                  <Filter className="w-5 h-5 text-purple-600 dark:text-purple-400" />
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Facets</p>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">{catalog.facets.length}</p>
                </div>
              </div>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center">
                  <Shield className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Scope</p>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">Global</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="mb-6 flex flex-wrap gap-2">
          {([
            { key: 'namespaces' as ActiveTab, label: 'Namespaces & Fields', icon: Layers, count: catalog?.namespaces.length },
            { key: 'facets' as ActiveTab, label: 'Facets', icon: Filter, count: catalog?.facets.length },
            { key: 'reference' as ActiveTab, label: 'Reference Data', icon: BookOpen },
            { key: 'admin' as ActiveTab, label: 'Admin', icon: Settings },
          ]).map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                activeTab === tab.key
                  ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400'
                  : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 border border-gray-200 dark:border-gray-700'
              }`}
            >
              <tab.icon className="w-4 h-4" />
              {tab.label}
              {tab.count !== undefined && (
                <span className={`px-1.5 py-0.5 rounded-full text-xs ${activeTab === tab.key ? 'bg-indigo-200 dark:bg-indigo-800' : 'bg-gray-100 dark:bg-gray-700'}`}>
                  {tab.count}
                </span>
              )}
            </button>
          ))}

          {/* Search (namespaces/facets tabs only) */}
          {(activeTab === 'namespaces' || activeTab === 'facets') && (
            <div className="relative flex-1 max-w-md ml-auto">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="Search fields and facets..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          )}
        </div>

        {/* ============= TAB: NAMESPACES & FIELDS ============= */}
        {activeTab === 'namespaces' && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Metadata Namespaces</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">{filteredNamespaces.length} namespaces (global baseline)</p>
              </div>
            </div>

            {filteredNamespaces.length === 0 ? (
              <div className="p-12 text-center">
                <Layers className="w-12 h-12 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
                <p className="text-gray-500 dark:text-gray-400">No namespaces found</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-200 dark:divide-gray-700">
                {filteredNamespaces.map((ns) => (
                  <div key={ns.namespace}>
                    <button
                      onClick={() => toggleNamespace(ns.namespace)}
                      className="w-full px-6 py-4 flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        {expandedNamespaces.has(ns.namespace) ? <ChevronDown className="w-5 h-5 text-gray-400" /> : <ChevronRight className="w-5 h-5 text-gray-400" />}
                        <div className="text-left">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-gray-900 dark:text-white">{ns.display_name}</span>
                            <span className="text-xs font-mono text-gray-500 dark:text-gray-400 px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700">{ns.namespace}</span>
                          </div>
                          {ns.description && <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{ns.description}</p>}
                        </div>
                      </div>
                      <div className="flex items-center gap-4">
                        <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400">
                          {ns.fields.length} fields
                        </span>
                      </div>
                    </button>

                    {expandedNamespaces.has(ns.namespace) && (
                      <div className="px-6 pb-4 border-t border-gray-100 dark:border-gray-700/50">
                        <div className="mt-3 flex justify-end">
                          <button
                            onClick={() => { setCreateFieldNs(ns.namespace); setShowCreateField(true) }}
                            className="flex items-center gap-1.5 text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300"
                          >
                            <Plus className="w-3.5 h-3.5" /> Add Field
                          </button>
                        </div>
                        <div className="mt-2 space-y-2">
                          {ns.fields.map((field) => {
                            const TypeIcon = getTypeIcon(field.data_type)
                            const typeColor = getTypeColor(field.data_type)
                            return (
                              <div key={field.field_name} className="flex items-start justify-between p-3 rounded-lg bg-gray-50 dark:bg-gray-900/50">
                                <div className="flex items-start gap-3">
                                  <div className={`p-1.5 rounded ${typeColor}`}><TypeIcon className="w-4 h-4" /></div>
                                  <div>
                                    <div className="flex items-center gap-2">
                                      <span className="font-mono text-sm font-medium text-gray-900 dark:text-white">{field.field_name}</span>
                                      <span className={`text-xs px-1.5 py-0.5 rounded ${typeColor}`}>{field.data_type}</span>
                                      {field.source === 'global' && (
                                        <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">Master</span>
                                      )}
                                    </div>
                                    {field.description && <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{field.description}</p>}
                                  </div>
                                </div>
                                <div className="flex items-center gap-2">
                                  {field.indexed && <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">Indexed</span>}
                                  {field.facetable && <span className="text-xs px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400">Facetable</span>}
                                  <button
                                    onClick={() => handleDeleteField(ns.namespace, field.field_name)}
                                    className="p-1 text-gray-400 hover:text-red-500 transition-colors"
                                    title="Deactivate field"
                                  >
                                    <Trash2 className="w-3.5 h-3.5" />
                                  </button>
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ============= TAB: FACETS ============= */}
        {activeTab === 'facets' && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Search Facets</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Cross-domain filters for search queries (global baseline)</p>
              </div>
              <button
                onClick={() => setShowCreateFacet(true)}
                className="flex items-center gap-1.5 text-sm text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300"
              >
                <Plus className="w-4 h-4" /> Add Facet
              </button>
            </div>

            {filteredFacets.length === 0 ? (
              <div className="p-12 text-center">
                <Filter className="w-12 h-12 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
                <p className="text-gray-500 dark:text-gray-400">No facets found</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-200 dark:divide-gray-700">
                {filteredFacets.map((facet) => {
                  const TypeIcon = getTypeIcon(facet.data_type)
                  const typeColor = getTypeColor(facet.data_type)
                  return (
                    <div key={facet.facet_name} className="px-6 py-4">
                      <div className="flex items-start justify-between">
                        <div className="flex items-start gap-3">
                          <div className={`p-2 rounded-lg ${typeColor}`}><TypeIcon className="w-5 h-5" /></div>
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-gray-900 dark:text-white">{facet.display_name}</span>
                              <span className="text-xs font-mono text-gray-500 dark:text-gray-400 px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700">{facet.facet_name}</span>
                              {facet.source === 'global' && (
                                <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">Master</span>
                              )}
                            </div>
                            {facet.description && <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{facet.description}</p>}
                            {facet.operators.length > 0 && (
                              <div className="flex items-center gap-1 mt-2">
                                <span className="text-xs text-gray-400">Operators:</span>
                                {facet.operators.map((op) => (
                                  <span key={op} className="text-xs font-mono px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">{op}</span>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className={`text-xs px-2 py-1 rounded ${typeColor}`}>{facet.data_type}</span>
                          <button
                            onClick={() => handleDeleteFacet(facet.facet_name)}
                            className="p-1 text-gray-400 hover:text-red-500 transition-colors"
                            title="Deactivate facet"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                      {facet.mappings.length > 0 && (
                        <div className="mt-3 ml-11">
                          <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Mappings:</p>
                          <div className="flex flex-wrap gap-2">
                            {facet.mappings.map((mapping) => (
                              <div key={mapping.content_type} className="text-xs px-2 py-1 rounded bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-400">
                                <span className="font-medium">{mapping.content_type}</span>
                                <span className="text-indigo-500 dark:text-indigo-500"> → </span>
                                <span className="font-mono">{mapping.json_path}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* ============= TAB: REFERENCE DATA ============= */}
        {activeTab === 'reference' && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div>
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Facet Reference Data</h2>
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">Canonical values and alias resolution</p>
                </div>
                <select
                  value={selectedFacetForRef}
                  onChange={(e) => setSelectedFacetForRef(e.target.value)}
                  className="text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  {catalog?.facets.map(f => (
                    <option key={f.facet_name} value={f.facet_name}>{f.display_name} ({f.facet_name})</option>
                  ))}
                </select>
              </div>
              <button
                onClick={() => setShowCreateRefValue(true)}
                className="flex items-center gap-1.5 text-sm text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300"
              >
                <Plus className="w-4 h-4" /> Add Value
              </button>
            </div>

            {isLoadingRef ? (
              <div className="p-12 text-center">
                <Loader2 className="w-8 h-8 mx-auto mb-4 text-indigo-500 animate-spin" />
                <p className="text-gray-500 dark:text-gray-400">Loading reference values...</p>
              </div>
            ) : referenceValues.length === 0 ? (
              <div className="p-12 text-center">
                <BookOpen className="w-12 h-12 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
                <p className="text-gray-500 dark:text-gray-400">No reference values for this facet</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-200 dark:divide-gray-700">
                {referenceValues.map((rv) => (
                  <div key={rv.id}>
                    <button
                      onClick={() => toggleValue(rv.id)}
                      className="w-full px-6 py-3 flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        {expandedValues.has(rv.id) ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
                        <div className="text-left">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-gray-900 dark:text-white">{rv.canonical_value}</span>
                            {rv.display_label && <span className="text-xs text-gray-500 dark:text-gray-400">({rv.display_label})</span>}
                            <span className={`text-xs px-1.5 py-0.5 rounded ${rv.status === 'active' ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400' : rv.status === 'suggested' ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400' : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400'}`}>
                              {rv.status}
                            </span>
                          </div>
                          {rv.description && <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{rv.description}</p>}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-400">{rv.aliases?.length || 0} aliases</span>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeleteRefValue(rv.id) }}
                          className="p-1 text-gray-400 hover:text-red-500 transition-colors"
                          title="Deactivate"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </button>

                    {expandedValues.has(rv.id) && rv.aliases && (
                      <div className="px-6 pb-4 border-t border-gray-100 dark:border-gray-700/50">
                        <div className="mt-3 flex justify-between items-center">
                          <p className="text-xs font-medium text-gray-500 dark:text-gray-400">Aliases</p>
                          <button
                            onClick={() => { setAddAliasValueId(rv.id); setShowAddAlias(true) }}
                            className="flex items-center gap-1 text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-800"
                          >
                            <Plus className="w-3 h-3" /> Add Alias
                          </button>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {rv.aliases.map((alias) => (
                            <div key={alias.id} className="flex items-center gap-1.5 text-xs px-2 py-1 rounded bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 group">
                              <span>{alias.alias_value}</span>
                              {alias.source_hint && <span className="text-gray-400">({alias.source_hint})</span>}
                              {alias.match_method && alias.match_method !== 'manual' && alias.match_method !== 'baseline' && (
                                <span className="text-gray-400 text-[10px]">[{alias.match_method}]</span>
                              )}
                              <button
                                onClick={() => handleRemoveAlias(rv.id, alias.id)}
                                className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition-all"
                              >
                                <X className="w-3 h-3" />
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ============= TAB: ADMIN ============= */}
        {activeTab === 'admin' && (
          <div className="space-y-6">
            {/* Actions */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Admin Actions</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Export, rebuild, and cache management</p>
              </div>
              <div className="p-6 grid grid-cols-1 sm:grid-cols-2 gap-4">
                <button onClick={handleExportFacets} className="flex items-center gap-3 p-4 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors text-left">
                  <Download className="w-5 h-5 text-indigo-500" />
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">Export Facets to YAML</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Write facet definitions to registry/facets.yaml</p>
                  </div>
                </button>
                <button onClick={handleExportRefData} className="flex items-center gap-3 p-4 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors text-left">
                  <Download className="w-5 h-5 text-indigo-500" />
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">Export Reference Data to YAML</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Write reference values and aliases to reference_data.yaml</p>
                  </div>
                </button>
                <button onClick={handleRebuild} className="flex items-center gap-3 p-4 rounded-lg border border-amber-200 dark:border-amber-800 hover:bg-amber-50 dark:hover:bg-amber-900/20 transition-colors text-left">
                  <Upload className="w-5 h-5 text-amber-500" />
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">Rebuild from YAML</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Flush and re-seed global baseline from YAML files</p>
                  </div>
                </button>
                <button onClick={handleInvalidateCache} className="flex items-center gap-3 p-4 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors text-left">
                  <RefreshCw className="w-5 h-5 text-gray-500" />
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">Invalidate Cache</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Clear all metadata registry caches</p>
                  </div>
                </button>
              </div>
            </div>

            {/* Org Override Summary */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Org Override Summary</h2>
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Which organizations have custom metadata overrides</p>
                </div>
                <button onClick={loadOverrideSummary} className="text-sm text-indigo-600 dark:text-indigo-400 hover:text-indigo-800">
                  <RefreshCw className={`w-4 h-4 ${isLoadingOverrides ? 'animate-spin' : ''}`} />
                </button>
              </div>

              {isLoadingOverrides ? (
                <div className="p-8 text-center">
                  <Loader2 className="w-6 h-6 mx-auto text-indigo-500 animate-spin" />
                </div>
              ) : overrideSummary ? (
                <div className="p-6">
                  <div className="mb-4">
                    <span className="text-2xl font-bold text-gray-900 dark:text-white">{overrideSummary.total_overrides}</span>
                    <span className="ml-2 text-sm text-gray-500 dark:text-gray-400">total override(s)</span>
                  </div>

                  {overrideSummary.total_overrides === 0 ? (
                    <p className="text-sm text-gray-500 dark:text-gray-400">No organizations have custom overrides.</p>
                  ) : (
                    <div className="space-y-4">
                      {Object.keys(overrideSummary.fields).length > 0 && (
                        <div>
                          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Field Overrides</h3>
                          <div className="space-y-2">
                            {Object.entries(overrideSummary.fields).map(([key, orgs]) => (
                              <div key={key} className="flex items-center justify-between p-2 rounded bg-gray-50 dark:bg-gray-900/50">
                                <span className="font-mono text-sm text-gray-900 dark:text-white">{key}</span>
                                <div className="flex gap-1.5">
                                  {orgs.map((org) => (
                                    <span key={org.org_id} className="text-xs px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 flex items-center gap-1">
                                      <Building2 className="w-3 h-3" />{org.org_name}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {Object.keys(overrideSummary.facets).length > 0 && (
                        <div>
                          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Facet Overrides</h3>
                          <div className="space-y-2">
                            {Object.entries(overrideSummary.facets).map(([key, orgs]) => (
                              <div key={key} className="flex items-center justify-between p-2 rounded bg-gray-50 dark:bg-gray-900/50">
                                <span className="font-mono text-sm text-gray-900 dark:text-white">{key}</span>
                                <div className="flex gap-1.5">
                                  {orgs.map((org) => (
                                    <span key={org.org_id} className="text-xs px-2 py-0.5 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400 flex items-center gap-1">
                                      <Building2 className="w-3 h-3" />{org.org_name}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          </div>
        )}

        {/* ============= MODALS ============= */}

        {/* Create Field Modal */}
        {showCreateField && (
          <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={() => setShowCreateField(false)}>
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Create Global Field in <span className="font-mono text-indigo-600 dark:text-indigo-400">{createFieldNs}</span>
              </h3>
              <div className="space-y-3">
                <div>
                  <label className="text-xs font-medium text-gray-500 dark:text-gray-400">Field Name</label>
                  <input type="text" value={newField.field_name} onChange={e => setNewField({...newField, field_name: e.target.value})}
                    className="w-full mt-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    placeholder="e.g., agency_code" />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 dark:text-gray-400">Data Type</label>
                  <select value={newField.data_type} onChange={e => setNewField({...newField, data_type: e.target.value})}
                    className="w-full mt-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500">
                    {['string', 'number', 'boolean', 'date', 'enum', 'array', 'object'].map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 dark:text-gray-400">Description</label>
                  <input type="text" value={newField.description} onChange={e => setNewField({...newField, description: e.target.value})}
                    className="w-full mt-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    placeholder="Optional description" />
                </div>
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                    <input type="checkbox" checked={newField.indexed} onChange={e => setNewField({...newField, indexed: e.target.checked})} className="rounded border-gray-300" /> Indexed
                  </label>
                  <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                    <input type="checkbox" checked={newField.facetable} onChange={e => setNewField({...newField, facetable: e.target.checked})} className="rounded border-gray-300" /> Facetable
                  </label>
                </div>
              </div>
              <div className="mt-6 flex justify-end gap-3">
                <Button variant="secondary" onClick={() => setShowCreateField(false)}>Cancel</Button>
                <Button onClick={handleCreateField} disabled={!newField.field_name}>Create</Button>
              </div>
            </div>
          </div>
        )}

        {/* Create Facet Modal */}
        {showCreateFacet && (
          <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={() => setShowCreateFacet(false)}>
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Create Global Facet</h3>
              <div className="space-y-3">
                <div>
                  <label className="text-xs font-medium text-gray-500 dark:text-gray-400">Facet Name</label>
                  <input type="text" value={newFacet.facet_name} onChange={e => setNewFacet({...newFacet, facet_name: e.target.value})}
                    className="w-full mt-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    placeholder="e.g., agency" />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 dark:text-gray-400">Display Name</label>
                  <input type="text" value={newFacet.display_name} onChange={e => setNewFacet({...newFacet, display_name: e.target.value})}
                    className="w-full mt-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    placeholder="e.g., Agency" />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 dark:text-gray-400">Data Type</label>
                  <select value={newFacet.data_type} onChange={e => setNewFacet({...newFacet, data_type: e.target.value})}
                    className="w-full mt-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500">
                    {['string', 'number', 'boolean', 'date'].map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 dark:text-gray-400">Description</label>
                  <input type="text" value={newFacet.description} onChange={e => setNewFacet({...newFacet, description: e.target.value})}
                    className="w-full mt-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    placeholder="Optional description" />
                </div>
              </div>
              <div className="mt-6 flex justify-end gap-3">
                <Button variant="secondary" onClick={() => setShowCreateFacet(false)}>Cancel</Button>
                <Button onClick={handleCreateFacet} disabled={!newFacet.facet_name || !newFacet.display_name}>Create</Button>
              </div>
            </div>
          </div>
        )}

        {/* Create Reference Value Modal */}
        {showCreateRefValue && (
          <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={() => setShowCreateRefValue(false)}>
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Add Reference Value for <span className="font-mono text-indigo-600 dark:text-indigo-400">{selectedFacetForRef}</span>
              </h3>
              <div className="space-y-3">
                <div>
                  <label className="text-xs font-medium text-gray-500 dark:text-gray-400">Canonical Value</label>
                  <input type="text" value={newRefValue.canonical_value} onChange={e => setNewRefValue({...newRefValue, canonical_value: e.target.value})}
                    className="w-full mt-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    placeholder="e.g., DEPARTMENT OF DEFENSE" />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 dark:text-gray-400">Display Label</label>
                  <input type="text" value={newRefValue.display_label} onChange={e => setNewRefValue({...newRefValue, display_label: e.target.value})}
                    className="w-full mt-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    placeholder="e.g., DoD" />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 dark:text-gray-400">Description</label>
                  <input type="text" value={newRefValue.description} onChange={e => setNewRefValue({...newRefValue, description: e.target.value})}
                    className="w-full mt-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    placeholder="Optional description" />
                </div>
              </div>
              <div className="mt-6 flex justify-end gap-3">
                <Button variant="secondary" onClick={() => setShowCreateRefValue(false)}>Cancel</Button>
                <Button onClick={handleCreateRefValue} disabled={!newRefValue.canonical_value}>Create</Button>
              </div>
            </div>
          </div>
        )}

        {/* Add Alias Modal */}
        {showAddAlias && (
          <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={() => setShowAddAlias(false)}>
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Add Alias</h3>
              <div className="space-y-3">
                <div>
                  <label className="text-xs font-medium text-gray-500 dark:text-gray-400">Alias Value</label>
                  <input type="text" value={newAlias.alias_value} onChange={e => setNewAlias({...newAlias, alias_value: e.target.value})}
                    className="w-full mt-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    placeholder="e.g., Pentagon" />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 dark:text-gray-400">Source Hint</label>
                  <input type="text" value={newAlias.source_hint} onChange={e => setNewAlias({...newAlias, source_hint: e.target.value})}
                    className="w-full mt-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    placeholder="e.g., SAM.gov" />
                </div>
              </div>
              <div className="mt-6 flex justify-end gap-3">
                <Button variant="secondary" onClick={() => setShowAddAlias(false)}>Cancel</Button>
                <Button onClick={handleAddAlias} disabled={!newAlias.alias_value}>Add</Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

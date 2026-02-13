'use client'

/**
 * Organization-scoped metadata catalog page.
 * View namespaces, fields, and facets for metadata governance.
 */

import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '@/lib/auth-context'
import { useOrgUrl } from '@/lib/org-url-context'
import {
  metadataApi,
  type MetadataCatalog,
  type MetadataNamespace,
  type MetadataFieldDefinition,
  type FacetDefinition,
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
  Sparkles,
} from 'lucide-react'

function getTypeIcon(dataType: string) {
  switch (dataType.toLowerCase()) {
    case 'string':
    case 'text':
      return Type
    case 'integer':
    case 'number':
    case 'float':
      return Hash
    case 'boolean':
      return ToggleLeft
    case 'date':
    case 'datetime':
      return Calendar
    case 'array':
      return Layers
    default:
      return Box
  }
}

function getTypeColor(dataType: string) {
  switch (dataType.toLowerCase()) {
    case 'string':
    case 'text':
      return 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20'
    case 'integer':
    case 'number':
    case 'float':
      return 'text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-900/20'
    case 'boolean':
      return 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20'
    case 'date':
    case 'datetime':
      return 'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20'
    case 'array':
      return 'text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-900/20'
    default:
      return 'text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-900/50'
  }
}

export default function MetadataCatalogPage() {
  const { token } = useAuth()
  const { orgSlug } = useOrgUrl()

  const [catalog, setCatalog] = useState<MetadataCatalog | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedNamespaces, setExpandedNamespaces] = useState<Set<string>>(new Set())
  const [activeTab, setActiveTab] = useState<'namespaces' | 'facets'>('namespaces')

  const loadData = useCallback(async (silent = false) => {
    if (!token) return

    if (!silent) setIsLoading(true)
    setError('')

    try {
      const data = await metadataApi.getCatalog(token)
      setCatalog(data)
      // Auto-expand first namespace
      if (data.namespaces.length > 0 && expandedNamespaces.size === 0) {
        setExpandedNamespaces(new Set([data.namespaces[0].namespace]))
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load metadata catalog'
      if (!silent) setError(message)
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [token])

  useEffect(() => {
    if (token) {
      loadData()
    }
  }, [token, loadData])

  const handleRefresh = () => {
    setIsRefreshing(true)
    loadData()
  }

  const toggleNamespace = (namespace: string) => {
    const newExpanded = new Set(expandedNamespaces)
    if (newExpanded.has(namespace)) {
      newExpanded.delete(namespace)
    } else {
      newExpanded.add(namespace)
    }
    setExpandedNamespaces(newExpanded)
  }

  // Filter namespaces and fields by search query
  const filteredNamespaces = catalog?.namespaces.filter((ns) => {
    if (!searchQuery.trim()) return true
    const query = searchQuery.toLowerCase()
    if (ns.namespace.toLowerCase().includes(query)) return true
    if (ns.display_name.toLowerCase().includes(query)) return true
    return ns.fields.some(
      (f) =>
        f.field_name.toLowerCase().includes(query) ||
        f.description?.toLowerCase().includes(query)
    )
  }) || []

  const filteredFacets = catalog?.facets.filter((f) => {
    if (!searchQuery.trim()) return true
    const query = searchQuery.toLowerCase()
    return (
      f.facet_name.toLowerCase().includes(query) ||
      f.display_name.toLowerCase().includes(query) ||
      f.description?.toLowerCase().includes(query)
    )
  }) || []

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin" />
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading metadata catalog...</p>
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
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-lg shadow-emerald-500/25 flex-shrink-0">
                <Database className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  Metadata Catalog
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  Browse metadata namespaces, fields, and facets
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                onClick={handleRefresh}
                disabled={isRefreshing}
                className="gap-2"
              >
                <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
            </div>
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
                <div className="w-10 h-10 rounded-lg bg-indigo-50 dark:bg-indigo-900/20 flex items-center justify-center">
                  <FileText className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Indexed Docs</p>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">
                    {catalog.total_indexed_docs.toLocaleString()}
                  </p>
                </div>
              </div>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center">
                  <Layers className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Namespaces</p>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">
                    {catalog.namespaces.length}
                  </p>
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
                  <p className="text-xl font-bold text-gray-900 dark:text-white">
                    {catalog.facets.length}
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="mb-6 flex flex-wrap gap-2">
          <button
            onClick={() => setActiveTab('namespaces')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === 'namespaces'
                ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400'
                : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 border border-gray-200 dark:border-gray-700'
            }`}
          >
            <Layers className="w-4 h-4" />
            Namespaces
            <span className={`px-1.5 py-0.5 rounded-full text-xs ${activeTab === 'namespaces' ? 'bg-indigo-200 dark:bg-indigo-800' : 'bg-gray-100 dark:bg-gray-700'}`}>
              {catalog?.namespaces.length || 0}
            </span>
          </button>
          <button
            onClick={() => setActiveTab('facets')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === 'facets'
                ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400'
                : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 border border-gray-200 dark:border-gray-700'
            }`}
          >
            <Filter className="w-4 h-4" />
            Facets
            <span className={`px-1.5 py-0.5 rounded-full text-xs ${activeTab === 'facets' ? 'bg-indigo-200 dark:bg-indigo-800' : 'bg-gray-100 dark:bg-gray-700'}`}>
              {catalog?.facets.length || 0}
            </span>
          </button>

          {/* Search */}
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
        </div>

        {/* Content */}
        {activeTab === 'namespaces' ? (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                Metadata Namespaces
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                {filteredNamespaces.length} namespace{filteredNamespaces.length !== 1 ? 's' : ''}
              </p>
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
                        {expandedNamespaces.has(ns.namespace) ? (
                          <ChevronDown className="w-5 h-5 text-gray-400" />
                        ) : (
                          <ChevronRight className="w-5 h-5 text-gray-400" />
                        )}
                        <div className="text-left">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-gray-900 dark:text-white">
                              {ns.display_name}
                            </span>
                            <span className="text-xs font-mono text-gray-500 dark:text-gray-400 px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700">
                              {ns.namespace}
                            </span>
                          </div>
                          {ns.description && (
                            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                              {ns.description}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-4">
                        <span className="text-sm text-gray-500 dark:text-gray-400">
                          {ns.doc_count.toLocaleString()} docs
                        </span>
                        <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400">
                          {ns.fields.length} fields
                        </span>
                      </div>
                    </button>

                    {expandedNamespaces.has(ns.namespace) && (
                      <div className="px-6 pb-4 border-t border-gray-100 dark:border-gray-700/50">
                        <div className="mt-4 space-y-2">
                          {ns.fields.map((field) => {
                            const TypeIcon = getTypeIcon(field.data_type)
                            const typeColor = getTypeColor(field.data_type)
                            return (
                              <div
                                key={field.field_name}
                                className="flex items-start justify-between p-3 rounded-lg bg-gray-50 dark:bg-gray-900/50"
                              >
                                <div className="flex items-start gap-3">
                                  <div className={`p-1.5 rounded ${typeColor}`}>
                                    <TypeIcon className="w-4 h-4" />
                                  </div>
                                  <div>
                                    <div className="flex items-center gap-2">
                                      <span className="font-mono text-sm font-medium text-gray-900 dark:text-white">
                                        {field.field_name}
                                      </span>
                                      <span className={`text-xs px-1.5 py-0.5 rounded ${typeColor}`}>
                                        {field.data_type}
                                      </span>
                                    </div>
                                    {field.description && (
                                      <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                                        {field.description}
                                      </p>
                                    )}
                                  </div>
                                </div>
                                <div className="flex items-center gap-2">
                                  {field.indexed && (
                                    <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">
                                      Indexed
                                    </span>
                                  )}
                                  {field.facetable && (
                                    <span className="text-xs px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400">
                                      Facetable
                                    </span>
                                  )}
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
        ) : (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                Search Facets
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Cross-domain filters for search queries
              </p>
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
                          <div className={`p-2 rounded-lg ${typeColor}`}>
                            <TypeIcon className="w-5 h-5" />
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-gray-900 dark:text-white">
                                {facet.display_name}
                              </span>
                              <span className="text-xs font-mono text-gray-500 dark:text-gray-400 px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700">
                                {facet.facet_name}
                              </span>
                            </div>
                            {facet.description && (
                              <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                                {facet.description}
                              </p>
                            )}
                            {facet.operators.length > 0 && (
                              <div className="flex items-center gap-1 mt-2">
                                <span className="text-xs text-gray-400">Operators:</span>
                                {facet.operators.map((op) => (
                                  <span
                                    key={op}
                                    className="text-xs font-mono px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                                  >
                                    {op}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                        <span className={`text-xs px-2 py-1 rounded ${typeColor}`}>
                          {facet.data_type}
                        </span>
                      </div>

                      {facet.mappings.length > 0 && (
                        <div className="mt-3 ml-11">
                          <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Mappings:</p>
                          <div className="flex flex-wrap gap-2">
                            {facet.mappings.map((mapping) => (
                              <div
                                key={mapping.content_type}
                                className="text-xs px-2 py-1 rounded bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-400"
                              >
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
      </div>
    </div>
  )
}

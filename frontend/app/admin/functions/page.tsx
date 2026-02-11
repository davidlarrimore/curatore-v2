'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { functionsApi, type FunctionMeta, getParametersFromSchema } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  RefreshCw,
  Code,
  Search,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Brain,
  Database,
  Send,
  Sparkles,
  Box,
  FlaskConical,
  GitBranch,
} from 'lucide-react'

export default function FunctionsPage() {
  return (
    <ProtectedRoute>
      <FunctionsContent />
    </ProtectedRoute>
  )
}

// Category icons mapping
const CATEGORY_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  llm: Brain,
  logic: GitBranch,
  search: Search,
  output: Send,
  notify: Send,
  compound: Sparkles,
  enrich: Database,
}

function getCategoryIcon(category: string): React.ComponentType<{ className?: string }> {
  return CATEGORY_ICONS[category] || Box
}

function getCategoryColor(category: string): string {
  switch (category) {
    case 'llm': return 'purple'
    case 'logic': return 'orange'
    case 'search': return 'blue'
    case 'output': return 'emerald'
    case 'notify': return 'amber'
    case 'compound': return 'indigo'
    case 'enrich': return 'teal'
    default: return 'gray'
  }
}

function FunctionsContent() {
  const { token } = useAuth()

  const [functions, setFunctions] = useState<FunctionMeta[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState('')

  // Filters
  const [selectedCategory, setSelectedCategory] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState('')

  // Expanded function details
  const [expandedFunctions, setExpandedFunctions] = useState<Set<string>>(new Set())

  // Load functions
  const loadData = useCallback(async (silent = false) => {
    if (!token) return

    if (!silent) {
      setIsLoading(true)
    }
    setError('')

    try {
      const [functionsData, categoriesData] = await Promise.all([
        functionsApi.listFunctions(token),
        functionsApi.getCategories(token),
      ])

      setFunctions(functionsData.functions)
      // Categories API returns { categories: { categoryName: [functionNames] } }
      // Extract just the category names as an array
      const categoryNames = Object.keys(categoriesData.categories || {})
      setCategories(categoryNames)
    } catch (err: any) {
      if (!silent) {
        setError(err.message || 'Failed to load functions')
      }
    } finally {
      if (!silent) {
        setIsLoading(false)
      }
      setIsRefreshing(false)
    }
  }, [token])

  // Initial load
  useEffect(() => {
    if (token) {
      loadData()
    }
  }, [token, loadData])

  // Manual refresh
  const handleRefresh = async () => {
    setIsRefreshing(true)
    await loadData()
  }

  // Toggle function expansion
  const toggleExpand = (name: string) => {
    const newExpanded = new Set(expandedFunctions)
    if (newExpanded.has(name)) {
      newExpanded.delete(name)
    } else {
      newExpanded.add(name)
    }
    setExpandedFunctions(newExpanded)
  }

  // Filter functions
  const filteredFunctions = useMemo(() => {
    let result = [...functions]

    // Filter by category
    if (selectedCategory !== 'all') {
      result = result.filter(fn => fn.category === selectedCategory)
    }

    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase()
      result = result.filter(fn =>
        fn.name.toLowerCase().includes(query) ||
        fn.description.toLowerCase().includes(query) ||
        fn.category.toLowerCase().includes(query)
      )
    }

    return result
  }, [functions, selectedCategory, searchQuery])

  // Group functions by category for display
  const groupedFunctions = useMemo(() => {
    const groups: Record<string, FunctionMeta[]> = {}
    for (const fn of filteredFunctions) {
      if (!groups[fn.category]) {
        groups[fn.category] = []
      }
      groups[fn.category].push(fn)
    }
    return groups
  }, [filteredFunctions])

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin"></div>
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading functions...</p>
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
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-purple-500 to-indigo-600 text-white shadow-lg shadow-purple-500/25 flex-shrink-0">
                <Code className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  Functions
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  Browse available functions and open them in the Lab for testing
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

          {/* Error Message */}
          {error && (
            <div className="mt-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
              <div className="flex items-center gap-3">
                <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
                <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
              </div>
            </div>
          )}
        </div>

        {/* Filters */}
        <div className="mb-6 flex flex-col sm:flex-row gap-4">
          {/* Category Filter */}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setSelectedCategory('all')}
              className={`
                flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors
                ${selectedCategory === 'all'
                  ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400'
                  : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 border border-gray-200 dark:border-gray-700'
                }
              `}
            >
              <Box className="w-4 h-4" />
              All
              <span className={`px-1.5 py-0.5 rounded-full text-xs ${selectedCategory === 'all' ? 'bg-indigo-200 dark:bg-indigo-800' : 'bg-gray-100 dark:bg-gray-700'}`}>
                {functions.length}
              </span>
            </button>
            {categories.map(category => {
              const Icon = getCategoryIcon(category)
              const count = functions.filter(fn => fn.category === category).length
              return (
                <button
                  key={category}
                  onClick={() => setSelectedCategory(category)}
                  className={`
                    flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors capitalize
                    ${selectedCategory === category
                      ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400'
                      : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 border border-gray-200 dark:border-gray-700'
                    }
                  `}
                >
                  <Icon className="w-4 h-4" />
                  {category}
                  <span className={`px-1.5 py-0.5 rounded-full text-xs ${selectedCategory === category ? 'bg-indigo-200 dark:bg-indigo-800' : 'bg-gray-100 dark:bg-gray-700'}`}>
                    {count}
                  </span>
                </button>
              )
            })}
          </div>

          {/* Search */}
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search functions..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
        </div>

        {/* Functions List */}
        <div className="space-y-6">
          {Object.entries(groupedFunctions).map(([category, categoryFunctions]) => {
            const Icon = getCategoryIcon(category)
            const color = getCategoryColor(category)

            return (
              <div key={category} className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                  <div className="flex items-center gap-3">
                    <div className={`w-8 h-8 rounded-lg bg-${color}-50 dark:bg-${color}-900/20 flex items-center justify-center`}>
                      <Icon className={`w-4 h-4 text-${color}-600 dark:text-${color}-400`} />
                    </div>
                    <h2 className="text-lg font-semibold text-gray-900 dark:text-white capitalize">
                      {category}
                    </h2>
                    <span className="text-sm text-gray-500 dark:text-gray-400">
                      {categoryFunctions.length} function{categoryFunctions.length !== 1 ? 's' : ''}
                    </span>
                  </div>
                </div>

                <div className="divide-y divide-gray-200 dark:divide-gray-700">
                  {categoryFunctions.map((fn) => (
                    <div key={fn.name} className="px-6 py-4">
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <button
                            onClick={() => toggleExpand(fn.name)}
                            className="flex items-center gap-2 text-left group"
                          >
                            {expandedFunctions.has(fn.name) ? (
                              <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0" />
                            ) : (
                              <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />
                            )}
                            <span className="text-sm font-mono font-medium text-gray-900 dark:text-white group-hover:text-indigo-600 dark:group-hover:text-indigo-400">
                              {fn.name}
                            </span>
                          </button>
                          <p className="mt-1 ml-6 text-sm text-gray-500 dark:text-gray-400">
                            {fn.description}
                          </p>
                        </div>
                        <Link
                          href={`/admin/functions/${encodeURIComponent(fn.name)}`}
                          className="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-100 dark:hover:bg-indigo-900/30 transition-colors flex-shrink-0"
                        >
                          <FlaskConical className="w-4 h-4" />
                          Open in Lab
                        </Link>
                      </div>

                      {/* Expanded Details */}
                      {expandedFunctions.has(fn.name) && (
                        <div className="mt-4 ml-6 space-y-4">
                          {/* Parameters */}
                          {(() => { const params = getParametersFromSchema(fn); return params.length > 0 && (
                            <div>
                              <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                                Parameters ({params.length})
                              </h4>
                              <div className="space-y-2">
                                {params.map((param) => (
                                  <div key={param.name} className="p-3 rounded-lg bg-gray-50 dark:bg-gray-900/50">
                                    <div className="flex items-center gap-2">
                                      <span className="text-sm font-mono font-medium text-gray-900 dark:text-white">
                                        {param.name}
                                      </span>
                                      <span className="text-xs px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                                        {param.type}
                                      </span>
                                      {param.required && (
                                        <span className="text-xs px-1.5 py-0.5 rounded bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400">
                                          required
                                        </span>
                                      )}
                                      {param.default !== undefined && (
                                        <span className="text-xs text-gray-500 dark:text-gray-400">
                                          = {JSON.stringify(param.default)}
                                        </span>
                                      )}
                                    </div>
                                    {param.description && (
                                      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                                        {param.description}
                                      </p>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </div>
                          ); })()}

                          {/* Output Schema */}
                          {fn.output_schema && fn.output_schema.type && (
                            <div>
                              <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                                Returns
                              </h4>
                              <div className="p-3 rounded-lg bg-gray-50 dark:bg-gray-900/50 space-y-3">
                                <div className="flex items-center gap-2">
                                  <span className="text-sm font-mono font-medium text-gray-900 dark:text-white">
                                    {fn.output_schema.type}
                                  </span>
                                </div>
                                {fn.output_schema.description && (
                                  <p className="text-sm text-gray-600 dark:text-gray-400">
                                    {fn.output_schema.description}
                                  </p>
                                )}
                                {/* Properties from JSON Schema */}
                                {fn.output_schema.properties && Object.keys(fn.output_schema.properties).length > 0 && (
                                  <div className="mt-2 space-y-1.5">
                                    {Object.entries(fn.output_schema.properties).map(([name, prop]: [string, any]) => (
                                      <div key={name} className="flex items-start gap-2 text-sm">
                                        <span className="font-mono text-indigo-600 dark:text-indigo-400">
                                          {name}
                                        </span>
                                        <span className="text-xs px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                                          {prop.type}
                                        </span>
                                        {prop.nullable && (
                                          <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-500">
                                            nullable
                                          </span>
                                        )}
                                        <span className="text-gray-500 dark:text-gray-400 flex-1">
                                          {prop.description}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                )}
                                {/* Array items properties */}
                                {fn.output_schema.items?.properties && Object.keys(fn.output_schema.items.properties).length > 0 && (
                                  <div className="mt-2 space-y-1.5">
                                    {Object.entries(fn.output_schema.items.properties).map(([name, prop]: [string, any]) => (
                                      <div key={name} className="flex items-start gap-2 text-sm">
                                        <span className="font-mono text-indigo-600 dark:text-indigo-400">
                                          {name}
                                        </span>
                                        <span className="text-xs px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                                          {prop.type}
                                        </span>
                                        {prop.nullable && (
                                          <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-500">
                                            nullable
                                          </span>
                                        )}
                                        <span className="text-gray-500 dark:text-gray-400 flex-1">
                                          {prop.description}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>

                              {/* Output Variants */}
                              {fn.output_schema.variants && fn.output_schema.variants.length > 0 && (
                                <div className="mt-3 space-y-2">
                                  {fn.output_schema.variants.map((variant: any, idx: number) => (
                                    <div key={idx} className="p-3 rounded-lg bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-100 dark:border-indigo-900/50">
                                      <div className="flex items-center gap-2 mb-2">
                                        <span className="text-xs font-semibold text-indigo-700 dark:text-indigo-300 uppercase">
                                          {variant.type}
                                        </span>
                                        <span className="text-xs text-indigo-600 dark:text-indigo-400">
                                          {variant.description}
                                        </span>
                                      </div>
                                      {variant.properties && Object.keys(variant.properties).length > 0 && (
                                        <div className="mt-2 space-y-1">
                                          {Object.entries(variant.properties).map(([name, prop]: [string, any]) => (
                                            <div key={name} className="flex items-start gap-2 text-xs">
                                              <span className="font-mono text-indigo-600 dark:text-indigo-400">
                                                {name}
                                              </span>
                                              <span className="text-gray-500 dark:text-gray-400">
                                                ({prop.type})
                                              </span>
                                            </div>
                                          ))}
                                        </div>
                                      )}
                                      {variant.items?.properties && Object.keys(variant.items.properties).length > 0 && (
                                        <div className="mt-2 space-y-1">
                                          {Object.entries(variant.items.properties).map(([name, prop]: [string, any]) => (
                                            <div key={name} className="flex items-start gap-2 text-xs">
                                              <span className="font-mono text-indigo-600 dark:text-indigo-400">
                                                {name}
                                              </span>
                                              <span className="text-gray-500 dark:text-gray-400">
                                                ({prop.type})
                                              </span>
                                            </div>
                                          ))}
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          )}

                          {/* Tags */}
                          {fn.tags && fn.tags.length > 0 && (
                            <div className="flex flex-wrap gap-2 pt-2">
                              {fn.tags.map((tag) => (
                                <span
                                  key={tag}
                                  className="text-xs px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                                >
                                  {tag}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )
          })}

          {filteredFunctions.length === 0 && (
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-12 text-center">
              <Code className="w-12 h-12 mx-auto mb-4 text-gray-300 dark:text-gray-600" />
              <p className="text-gray-500 dark:text-gray-400">No functions found</p>
              <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">
                {searchQuery ? 'Try adjusting your search' : 'No functions are registered'}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

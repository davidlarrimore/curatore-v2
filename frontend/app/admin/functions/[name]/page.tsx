'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { functionsApi, contractsApi, systemApi, type FunctionMeta, type FunctionExecuteResult, type ToolContract } from '@/lib/api'
import type { LLMConnectionStatus } from '@/types'
import { generateFunctionJson } from '@/lib/yaml-generator'
import { FunctionInput } from '@/components/functions/inputs'
import { ParameterTooltip } from '@/components/functions/ParameterTooltip'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  ArrowLeft,
  Play,
  FlaskConical,
  Copy,
  Check,
  CheckCircle,
  XCircle,
  Loader2,
  Brain,
  Tag,
  Clock,
  Code,
  BookOpen,
  FileJson,
  AlertTriangle,
  Zap,
  Eye,
  ChevronRight,
  ChevronDown,
  Shield,
  Server,
  Layers,
  Info,
  ExternalLink,
} from 'lucide-react'

export default function FunctionLabPage() {
  return (
    <ProtectedRoute>
      <FunctionLabContent />
    </ProtectedRoute>
  )
}

// ============================================================================
// Smart Output Viewer Component
// ============================================================================

type OutputViewMode = 'code' | 'formatted' | 'tree'

interface OutputViewerProps {
  data: any
  className?: string
}

function OutputViewer({ data, className = '' }: OutputViewerProps) {
  const [viewMode, setViewMode] = useState<OutputViewMode>('tree')

  // Detect content type
  const contentType = useMemo(() => {
    if (data === null || data === undefined) return 'empty'
    if (typeof data === 'string') {
      if (data.trim().startsWith('<') && (data.includes('</') || data.includes('/>'))) {
        return 'html'
      }
      if (data.includes('# ') || data.includes('**') || data.includes('- ') || data.includes('```')) {
        return 'markdown'
      }
      return 'text'
    }
    if (typeof data === 'object') {
      return 'json'
    }
    return 'text'
  }, [data])

  useEffect(() => {
    if (contentType === 'json') {
      setViewMode('tree')
    } else if (contentType === 'html' || contentType === 'markdown') {
      setViewMode('formatted')
    } else {
      setViewMode('code')
    }
  }, [contentType])

  const showViewToggle = contentType === 'html' || contentType === 'markdown' || contentType === 'json'

  return (
    <div className={`flex flex-col h-full ${className}`}>
      {showViewToggle && (
        <div className="flex items-center gap-1 mb-3">
          {contentType === 'json' && (
            <>
              <button
                onClick={() => setViewMode('tree')}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                  viewMode === 'tree'
                    ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'
                }`}
              >
                <ChevronRight className="w-3 h-3" />
                Tree
              </button>
              <button
                onClick={() => setViewMode('code')}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                  viewMode === 'code'
                    ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'
                }`}
              >
                <Code className="w-3 h-3" />
                Code
              </button>
            </>
          )}
          {(contentType === 'html' || contentType === 'markdown') && (
            <>
              <button
                onClick={() => setViewMode('formatted')}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                  viewMode === 'formatted'
                    ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'
                }`}
              >
                <Eye className="w-3 h-3" />
                Preview
              </button>
              <button
                onClick={() => setViewMode('code')}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                  viewMode === 'code'
                    ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'
                }`}
              >
                <Code className="w-3 h-3" />
                Code
              </button>
            </>
          )}
        </div>
      )}

      <div className="flex-1 overflow-auto">
        {contentType === 'empty' && (
          <p className="text-sm text-gray-500 dark:text-gray-400 italic">No data returned</p>
        )}

        {contentType === 'json' && viewMode === 'tree' && (
          <JsonTreeView data={data} />
        )}

        {contentType === 'json' && viewMode === 'code' && (
          <pre className="text-xs font-mono bg-gray-900 dark:bg-gray-950 text-emerald-400 dark:text-emerald-300 p-3 rounded-lg overflow-auto">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}

        {contentType === 'html' && viewMode === 'formatted' && (
          <div
            className="prose prose-sm dark:prose-invert max-w-none p-3 bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700"
            dangerouslySetInnerHTML={{ __html: data }}
          />
        )}

        {contentType === 'html' && viewMode === 'code' && (
          <pre className="text-xs font-mono bg-gray-900 dark:bg-gray-950 text-emerald-400 dark:text-emerald-300 p-3 rounded-lg overflow-auto whitespace-pre-wrap">
            {data}
          </pre>
        )}

        {contentType === 'markdown' && viewMode === 'formatted' && (
          <div className="prose prose-sm dark:prose-invert max-w-none p-3 bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700">
            <MarkdownRenderer content={data} />
          </div>
        )}

        {contentType === 'markdown' && viewMode === 'code' && (
          <pre className="text-xs font-mono bg-gray-900 dark:bg-gray-950 text-emerald-400 dark:text-emerald-300 p-3 rounded-lg overflow-auto whitespace-pre-wrap">
            {data}
          </pre>
        )}

        {contentType === 'text' && (
          <pre className="text-sm font-mono text-gray-800 dark:text-gray-200 bg-gray-50 dark:bg-gray-900/50 p-3 rounded-lg overflow-auto whitespace-pre-wrap">
            {String(data)}
          </pre>
        )}
      </div>
    </div>
  )
}

// ============================================================================
// JSON Tree View Component
// ============================================================================

interface JsonTreeViewProps {
  data: any
  depth?: number
}

function JsonTreeView({ data, depth = 0 }: JsonTreeViewProps) {
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (depth === 0) {
      const keys = new Set<string>()
      const addKeys = (obj: any, prefix: string, currentDepth: number) => {
        if (currentDepth > 1) return
        if (Array.isArray(obj)) {
          obj.forEach((_, i) => {
            const key = `${prefix}[${i}]`
            keys.add(key)
            if (typeof obj[i] === 'object' && obj[i] !== null) {
              addKeys(obj[i], key, currentDepth + 1)
            }
          })
        } else if (typeof obj === 'object' && obj !== null) {
          Object.keys(obj).forEach(k => {
            const key = `${prefix}.${k}`
            keys.add(key)
            if (typeof obj[k] === 'object' && obj[k] !== null) {
              addKeys(obj[k], key, currentDepth + 1)
            }
          })
        }
      }
      addKeys(data, 'root', 0)
      setExpandedKeys(keys)
    }
  }, [data, depth])

  const toggleExpand = (key: string) => {
    setExpandedKeys(prev => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  const renderValue = (value: any, key: string, name: string) => {
    if (value === null) {
      return <span className="text-gray-400 italic">null</span>
    }
    if (value === undefined) {
      return <span className="text-gray-400 italic">undefined</span>
    }
    if (typeof value === 'boolean') {
      return <span className="text-amber-600 dark:text-amber-400">{value.toString()}</span>
    }
    if (typeof value === 'number') {
      return <span className="text-blue-600 dark:text-blue-400">{value}</span>
    }
    if (typeof value === 'string') {
      const displayValue = value.length > 100 ? value.slice(0, 100) + '...' : value
      return <span className="text-emerald-600 dark:text-emerald-400">&quot;{displayValue}&quot;</span>
    }
    if (Array.isArray(value)) {
      const isExpanded = expandedKeys.has(key)
      return (
        <div>
          <button
            onClick={() => toggleExpand(key)}
            className="flex items-center gap-1 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
          >
            {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            <span className="text-purple-600 dark:text-purple-400">Array</span>
            <span className="text-gray-400">({value.length})</span>
          </button>
          {isExpanded && (
            <div className="ml-4 border-l border-gray-200 dark:border-gray-700 pl-3 mt-1">
              {value.map((item, i) => (
                <div key={i} className="py-0.5">
                  <span className="text-gray-500 dark:text-gray-500 text-xs mr-2">{i}:</span>
                  {renderValue(item, `${key}[${i}]`, String(i))}
                </div>
              ))}
            </div>
          )}
        </div>
      )
    }
    if (typeof value === 'object') {
      const isExpanded = expandedKeys.has(key)
      const keys = Object.keys(value)
      return (
        <div>
          <button
            onClick={() => toggleExpand(key)}
            className="flex items-center gap-1 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
          >
            {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            <span className="text-indigo-600 dark:text-indigo-400">Object</span>
            <span className="text-gray-400">({keys.length} keys)</span>
          </button>
          {isExpanded && (
            <div className="ml-4 border-l border-gray-200 dark:border-gray-700 pl-3 mt-1">
              {keys.map(k => (
                <div key={k} className="py-0.5">
                  <span className="text-gray-700 dark:text-gray-300 text-sm mr-2">{k}:</span>
                  {renderValue(value[k], `${key}.${k}`, k)}
                </div>
              ))}
            </div>
          )}
        </div>
      )
    }
    return <span className="text-gray-600 dark:text-gray-400">{String(value)}</span>
  }

  if (Array.isArray(data)) {
    return (
      <div className="text-sm font-mono">
        <span className="text-purple-600 dark:text-purple-400">Array</span>
        <span className="text-gray-400 ml-1">({data.length} items)</span>
        <div className="ml-2 border-l border-gray-200 dark:border-gray-700 pl-3 mt-1">
          {data.map((item, i) => (
            <div key={i} className="py-0.5">
              <span className="text-gray-500 dark:text-gray-500 text-xs mr-2">{i}:</span>
              {renderValue(item, `root[${i}]`, String(i))}
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (typeof data === 'object' && data !== null) {
    const keys = Object.keys(data)
    return (
      <div className="text-sm font-mono">
        {keys.map(k => (
          <div key={k} className="py-0.5">
            <span className="text-gray-700 dark:text-gray-300 mr-2">{k}:</span>
            {renderValue(data[k], `root.${k}`, k)}
          </div>
        ))}
      </div>
    )
  }

  return <span className="text-sm font-mono">{renderValue(data, 'root', 'root')}</span>
}

// ============================================================================
// Simple Markdown Renderer
// ============================================================================

function MarkdownRenderer({ content }: { content: string }) {
  const html = useMemo(() => {
    let result = content
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/^### (.*$)/gm, '<h3>$1</h3>')
      .replace(/^## (.*$)/gm, '<h2>$1</h2>')
      .replace(/^# (.*$)/gm, '<h1>$1</h1>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/^\s*-\s+(.*)$/gm, '<li>$1</li>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" class="text-indigo-600 hover:underline">$1</a>')
      .replace(/\n\n/g, '</p><p>')

    result = result.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>')

    return `<p>${result}</p>`
  }, [content])

  return <div dangerouslySetInnerHTML={{ __html: html }} />
}

// ============================================================================
// JSON Schema Viewer Component
// ============================================================================

function SchemaViewer({ schema, title }: { schema: Record<string, any>; title: string }) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (!schema || Object.keys(schema).length === 0) return null

  return (
    <div>
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-2 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
      >
        {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {title}
      </button>
      {isExpanded && (
        <pre className="mt-2 text-xs font-mono bg-gray-900 dark:bg-gray-950 text-emerald-400 dark:text-emerald-300 p-3 rounded-lg overflow-auto max-h-64">
          {JSON.stringify(schema, null, 2)}
        </pre>
      )}
    </div>
  )
}

// ============================================================================
// Main Content Component
// ============================================================================

function FunctionLabContent() {
  const params = useParams()
  const router = useRouter()
  const { token } = useAuth()
  const functionName = params.name as string

  const [func, setFunc] = useState<FunctionMeta | null>(null)
  const [contract, setContract] = useState<ToolContract | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  // LLM connection status
  const [llmStatus, setLlmStatus] = useState<LLMConnectionStatus | null>(null)
  const [isLoadingLlm, setIsLoadingLlm] = useState(false)

  // Parameter values
  const [paramValues, setParamValues] = useState<Record<string, any>>({})

  // Execution state
  const [isExecuting, setIsExecuting] = useState(false)
  const [isDryRun, setIsDryRun] = useState(false)
  const [result, setResult] = useState<FunctionExecuteResult | null>(null)

  // JSON copy state
  const [copied, setCopied] = useState(false)

  // Load LLM status
  const loadLlmStatus = useCallback(async () => {
    setIsLoadingLlm(true)
    try {
      const status = await systemApi.getLLMStatus()
      setLlmStatus(status)
      if (status.connected && status.model) {
        setParamValues((prev) => ({ ...prev, model: status.model }))
      }
    } catch (err) {
      console.error('Failed to load LLM status:', err)
    } finally {
      setIsLoadingLlm(false)
    }
  }, [])

  // Load function metadata and contract
  const loadFunction = useCallback(async () => {
    if (!token || !functionName) return

    setIsLoading(true)
    setError('')

    try {
      const [data, contractData] = await Promise.all([
        functionsApi.getFunction(token, functionName),
        contractsApi.getContract(token, functionName).catch(() => null),
      ])
      setFunc(data)
      setContract(contractData)

      const defaults: Record<string, any> = {}
      for (const param of data.parameters || []) {
        if (param.default !== undefined) {
          defaults[param.name] = param.default
        }
      }
      setParamValues(defaults)

      if (data.requires_llm) {
        loadLlmStatus()
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load function')
    } finally {
      setIsLoading(false)
    }
  }, [token, functionName, loadLlmStatus])

  useEffect(() => {
    loadFunction()
  }, [loadFunction])

  const handleParamChange = (name: string, value: any) => {
    setParamValues((prev) => ({ ...prev, [name]: value }))
  }

  const handleExecute = async (dryRun: boolean) => {
    if (!token || !func) return

    setIsExecuting(true)
    setIsDryRun(dryRun)
    setResult(null)

    try {
      const execResult = await functionsApi.executeFunction(
        token,
        func.name,
        paramValues,
        dryRun
      )
      setResult(execResult)
    } catch (err: any) {
      setResult({
        status: 'error',
        error: err.message || 'Execution failed',
      })
    } finally {
      setIsExecuting(false)
    }
  }

  const jsonOutput = useMemo(() => {
    if (!func) return ''
    return generateFunctionJson(func.name, paramValues)
  }, [func, paramValues])

  const handleCopyJson = async () => {
    try {
      await navigator.clipboard.writeText(jsonOutput)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  const canExecute = useMemo(() => {
    if (!func) return false
    if (func.requires_llm && (!llmStatus || !llmStatus.connected)) {
      return false
    }
    const requiredParams = func.parameters?.filter((p) => p.required) || []
    return requiredParams.every((p) => {
      const val = paramValues[p.name]
      if (val === undefined || val === null) return false
      if (val === '') return false
      if (Array.isArray(val) && val.length === 0) return false
      return true
    })
  }, [func, paramValues, llmStatus])

  // Loading state
  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="flex items-center justify-center h-screen">
          <div className="flex flex-col items-center">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin"></div>
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading function...</p>
          </div>
        </div>
      </div>
    )
  }

  // Error state
  if (error || !func) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="flex items-center justify-center h-screen">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-12 text-center max-w-md">
            <AlertTriangle className="w-12 h-12 mx-auto mb-4 text-red-400" />
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
              Function Not Found
            </h2>
            <p className="text-gray-500 dark:text-gray-400 mb-6">
              {error || `The function "${functionName}" could not be loaded.`}
            </p>
            <Button onClick={() => router.push('/admin/functions')}>
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Functions
            </Button>
          </div>
        </div>
      </div>
    )
  }

  const hasLlmWarning = func.requires_llm && llmStatus && !llmStatus.connected

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      {/* Header - Fixed */}
      <div className="flex-shrink-0 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
        <div className="max-w-[1800px] mx-auto px-4 sm:px-6 lg:px-8 py-3">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.push('/admin/functions')}
              className="p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
            <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-gradient-to-br from-purple-500 to-indigo-600 text-white shadow-lg shadow-purple-500/25">
              <FlaskConical className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900 dark:text-white font-mono">
                {func.name}
              </h1>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Function Lab
              </p>
            </div>

            {/* Category & Governance Badges in header */}
            <div className="flex items-center gap-2 ml-4 flex-wrap">
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 capitalize">
                <Code className="w-3 h-3" />
                {func.category}
              </span>
              {func.requires_llm && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300">
                  <Brain className="w-3 h-3" />
                  LLM
                </span>
              )}
              {func.side_effects ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300">
                  <Zap className="w-3 h-3" />
                  Side Effects
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300">
                  <Zap className="w-3 h-3" />
                  No Side Effects
                </span>
              )}
              {func.payload_profile && (
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                  func.payload_profile === 'thin'
                    ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                    : func.payload_profile === 'summary'
                    ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300'
                    : 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300'
                }`}>
                  <Layers className="w-3 h-3" />
                  {func.payload_profile}
                </span>
              )}
              {func.is_primitive === false && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                  Compound
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* LLM Warning Banner - Fixed */}
      {hasLlmWarning && (
        <div className="flex-shrink-0 bg-amber-50 dark:bg-amber-900/20 border-b border-amber-100 dark:border-amber-900/50 px-4 py-2">
          <div className="max-w-[1800px] mx-auto flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 flex-shrink-0" />
            <p className="text-sm text-amber-700 dark:text-amber-300">
              This function requires an LLM connection. Configure one in{' '}
              <a href="/connections" className="underline font-medium hover:text-amber-900 dark:hover:text-amber-100">
                Connections
              </a>{' '}
              to execute.
            </p>
          </div>
        </div>
      )}

      {/* Main Content: Documentation (30%) + Lab Panel (70%) */}
      <div className="flex-1 min-h-0 overflow-hidden">
        <div className="max-w-[1800px] mx-auto px-4 sm:px-6 lg:px-8 py-4 h-full">
          <div className="flex gap-4 h-full">

            {/* Documentation Panel (30%) */}
            <div className="w-[30%] flex-shrink-0 flex flex-col bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="flex-shrink-0 h-11 px-4 flex items-center gap-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                <BookOpen className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                  Documentation
                </h2>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-6">
                {/* Description */}
                <div>
                  <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
                    {func.description}
                  </p>
                </div>

                {/* Tags */}
                {func.tags && func.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {func.tags.map((tag) => (
                      <span
                        key={tag}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                      >
                        <Tag className="w-2.5 h-2.5" />
                        {tag}
                      </span>
                    ))}
                  </div>
                )}

                {/* Governance & Contract Details */}
                <div>
                  <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
                    Governance
                  </h3>
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 text-xs">
                      <Shield className="w-3.5 h-3.5 text-gray-400" />
                      <span className="text-gray-600 dark:text-gray-400">Version:</span>
                      <span className="font-mono text-gray-800 dark:text-gray-200">{func.version || '1.0.0'}</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <Layers className="w-3.5 h-3.5 text-gray-400" />
                      <span className="text-gray-600 dark:text-gray-400">Payload:</span>
                      <span className={`font-medium ${
                        func.payload_profile === 'thin' ? 'text-blue-600 dark:text-blue-400' :
                        func.payload_profile === 'summary' ? 'text-amber-600 dark:text-amber-400' :
                        'text-emerald-600 dark:text-emerald-400'
                      }`}>
                        {func.payload_profile || 'full'}
                      </span>
                      {func.payload_profile === 'thin' && (
                        <span className="text-gray-400 text-[10px]">(IDs, titles, scores only)</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <Zap className="w-3.5 h-3.5 text-gray-400" />
                      <span className="text-gray-600 dark:text-gray-400">Side Effects:</span>
                      <span className={func.side_effects ? 'text-red-600 dark:text-red-400 font-medium' : 'text-emerald-600 dark:text-emerald-400'}>
                        {func.side_effects ? 'Yes' : 'None'}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <Info className="w-3.5 h-3.5 text-gray-400" />
                      <span className="text-gray-600 dark:text-gray-400">Type:</span>
                      <span className="text-gray-800 dark:text-gray-200">
                        {func.is_primitive === false ? 'Compound (multi-step)' : 'Primitive'}
                      </span>
                    </div>
                    {func.exposure_profile && (
                      <div className="flex items-center gap-2 text-xs">
                        <ExternalLink className="w-3.5 h-3.5 text-gray-400" />
                        <span className="text-gray-600 dark:text-gray-400">Exposure:</span>
                        <div className="flex gap-1.5">
                          {func.exposure_profile.procedure && (
                            <span className="px-1.5 py-0.5 rounded bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 text-[10px] font-medium">
                              Procedure
                            </span>
                          )}
                          {func.exposure_profile.agent && (
                            <span className="px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 text-[10px] font-medium">
                              MCP / Agent
                            </span>
                          )}
                        </div>
                      </div>
                    )}
                    {func.requires_llm && (
                      <div className="flex items-center gap-2 text-xs">
                        <Brain className="w-3.5 h-3.5 text-gray-400" />
                        <span className="text-gray-600 dark:text-gray-400">LLM Required:</span>
                        <span className="text-purple-600 dark:text-purple-400 font-medium">Yes</span>
                      </div>
                    )}
                    {func.is_async && (
                      <div className="flex items-center gap-2 text-xs">
                        <Server className="w-3.5 h-3.5 text-gray-400" />
                        <span className="text-gray-600 dark:text-gray-400">Async:</span>
                        <span className="text-gray-800 dark:text-gray-200">Yes</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Parameters Documentation */}
                {func.parameters && func.parameters.length > 0 && (
                  <div>
                    <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
                      Parameters
                    </h3>
                    <div className="space-y-3">
                      {func.parameters.map((param) => (
                        <div key={param.name} className="text-sm">
                          <div className="flex items-center gap-2 mb-1">
                            <code className="text-xs font-mono font-medium text-indigo-600 dark:text-indigo-400">
                              {param.name}
                            </code>
                            <span className="text-xs text-gray-400">{param.type}</span>
                            {param.required && (
                              <span className="text-xs text-red-500">*</span>
                            )}
                            {param.default !== undefined && param.default !== null && (
                              <span className="text-[10px] text-gray-400">
                                = {JSON.stringify(param.default)}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
                            {param.description}
                          </p>
                          {param.enum_values && param.enum_values.length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1">
                              {param.enum_values.map((v) => {
                                const label = v.includes('|') ? v.split('|')[1] : v
                                return (
                                  <span key={v} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 font-mono">
                                    {label}
                                  </span>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Output Schema */}
                {func.output_schema && (
                  <div>
                    <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
                      Returns
                    </h3>
                    <div className="text-sm">
                      <code className="text-xs font-mono font-medium text-emerald-600 dark:text-emerald-400">
                        {func.output_schema.type}
                      </code>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 leading-relaxed">
                        {func.output_schema.description}
                      </p>
                      {func.output_schema.fields && func.output_schema.fields.length > 0 && (
                        <div className="mt-3 space-y-2">
                          {func.output_schema.fields.map((field) => (
                            <div key={field.name} className="flex items-start gap-2 text-xs">
                              <code className="font-mono text-indigo-600 dark:text-indigo-400 flex-shrink-0">
                                .{field.name}
                              </code>
                              <span className="text-gray-400">{field.type}</span>
                              {field.nullable && (
                                <span className="text-amber-500 text-[10px]">?</span>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Output Variants */}
                    {func.output_variants && func.output_variants.length > 0 && (
                      <div className="mt-4 space-y-3">
                        {func.output_variants.map((variant, idx) => (
                          <div key={idx} className="p-2 rounded-lg bg-gray-50 dark:bg-gray-900/50 border border-gray-100 dark:border-gray-700">
                            <div className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                              {variant.mode} mode
                            </div>
                            <div className="text-[10px] text-gray-400 mb-2">
                              {variant.condition}
                            </div>
                            <code className="text-xs font-mono text-emerald-600 dark:text-emerald-400">
                              {variant.schema.type}
                            </code>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Contract JSON Schemas */}
                {contract && (
                  <div className="space-y-4">
                    <SchemaViewer
                      schema={contract.input_schema}
                      title="Input JSON Schema"
                    />
                    <SchemaViewer
                      schema={contract.output_schema}
                      title="Output JSON Schema"
                    />
                  </div>
                )}

                {/* Examples */}
                {func.examples && func.examples.length > 0 && (
                  <div>
                    <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
                      Examples ({func.examples.length})
                    </h3>
                    <div className="space-y-2">
                      {func.examples.map((example, idx) => (
                        <pre
                          key={idx}
                          className="text-xs font-mono bg-gray-900 dark:bg-gray-950 text-emerald-400 dark:text-emerald-300 p-3 rounded-lg overflow-auto max-h-40"
                        >
                          {JSON.stringify(example, null, 2)}
                        </pre>
                      ))}
                    </div>
                  </div>
                )}

                {/* LLM Connection */}
                {func.requires_llm && llmStatus && llmStatus.connected && (
                  <div>
                    <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                      LLM Connection
                    </h3>
                    <div className="flex items-center gap-2 text-xs">
                      <Zap className="w-3 h-3 text-emerald-500" />
                      <span className="text-gray-600 dark:text-gray-400">
                        {llmStatus.model}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Lab Panel (70%) */}
            <div className="flex-1 min-w-0 flex flex-col bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="flex-1 min-h-0 flex">

                {/* Left Side: Parameters + JSON */}
                <div className="w-1/2 border-r border-gray-200 dark:border-gray-700 flex flex-col min-h-0">
                  {/* Parameters Header */}
                  <div className="flex-shrink-0 h-11 px-4 flex items-center border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                    <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                      Parameters
                    </h2>
                  </div>
                  {/* Parameters Content */}
                  <div className="flex-1 overflow-y-auto p-4">
                    {!func.parameters || func.parameters.length === 0 ? (
                      <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-8">
                        This function has no parameters.
                      </p>
                    ) : (
                      <div className="space-y-4">
                        {func.parameters.map((param) => {
                          const isLlmModelParam = param.name === 'model' && func.requires_llm
                          const isDisabled = isExecuting || isLlmModelParam

                          return (
                            <div key={param.name} className="space-y-1.5">
                              <div className="flex items-center gap-2">
                                <label className="text-sm font-medium text-gray-900 dark:text-white font-mono">
                                  {param.name}
                                </label>
                                <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400">
                                  {param.type}
                                </span>
                                {param.required && (
                                  <span className="text-xs px-1.5 py-0.5 rounded bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400">
                                    required
                                  </span>
                                )}
                                {isLlmModelParam && (
                                  <span className="text-xs px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
                                    auto
                                  </span>
                                )}
                                <ParameterTooltip param={param} />
                              </div>
                              <FunctionInput
                                param={param}
                                value={paramValues[param.name]}
                                onChange={(value) => handleParamChange(param.name, value)}
                                disabled={isDisabled}
                              />
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>

                  {/* JSON Output Section */}
                  <div className="flex-shrink-0 max-h-52 flex flex-col border-t border-gray-200 dark:border-gray-700 overflow-hidden">
                    <div className="flex-shrink-0 h-9 px-4 flex items-center justify-between bg-gray-50 dark:bg-gray-900/50">
                      <div className="flex items-center gap-2">
                        <FileJson className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                          Step JSON
                        </h2>
                      </div>
                      <button
                        onClick={handleCopyJson}
                        className="flex items-center gap-1 px-2 py-1 text-xs font-medium rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
                      >
                        {copied ? (
                          <>
                            <Check className="w-3 h-3 text-emerald-500" />
                            Copied
                          </>
                        ) : (
                          <>
                            <Copy className="w-3 h-3" />
                            Copy
                          </>
                        )}
                      </button>
                    </div>
                    <div className="flex-1 overflow-y-auto p-3">
                      <pre className="text-xs font-mono bg-gray-900 dark:bg-gray-950 text-emerald-400 dark:text-emerald-300 p-3 rounded-lg overflow-x-auto">
                        {jsonOutput}
                      </pre>
                    </div>
                  </div>
                </div>

                {/* Right Side: Controls + Output */}
                <div className="w-1/2 flex flex-col min-h-0">
                  {/* Control Bar */}
                  <div className="flex-shrink-0 h-11 px-4 flex items-center justify-between border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                    <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                      Output
                    </h2>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => handleExecute(true)}
                        disabled={isExecuting || !canExecute}
                        className="gap-1.5 text-xs"
                      >
                        {isExecuting && isDryRun ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <FlaskConical className="w-3 h-3" />
                        )}
                        Dry Run
                      </Button>
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => handleExecute(false)}
                        disabled={isExecuting || !canExecute}
                        className="gap-1.5 text-xs"
                      >
                        {isExecuting && !isDryRun ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <Play className="w-3 h-3" />
                        )}
                        Run
                      </Button>
                    </div>
                  </div>

                  {/* Output Panel */}
                  <div className="flex-1 overflow-y-auto p-4">
                  {!result && !isExecuting && (
                    <div className="flex flex-col items-center justify-center h-full text-center">
                      <FlaskConical className="w-12 h-12 text-gray-200 dark:text-gray-700 mb-4" />
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        Configure parameters and click Run to execute
                      </p>
                    </div>
                  )}

                  {isExecuting && (
                    <div className="flex flex-col items-center justify-center h-full">
                      <Loader2 className="w-8 h-8 text-indigo-500 animate-spin mb-4" />
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        {isDryRun ? 'Running dry run...' : 'Executing function...'}
                      </p>
                    </div>
                  )}

                  {result && !isExecuting && (
                    <div className="space-y-4 h-full flex flex-col">
                      {/* Status Header */}
                      <div
                        className={`px-4 py-3 rounded-lg flex items-center justify-between ${
                          result.status === 'success' || result.status === 'completed'
                            ? 'bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-100 dark:border-emerald-900/50'
                            : result.status === 'partial'
                            ? 'bg-amber-50 dark:bg-amber-900/20 border border-amber-100 dark:border-amber-900/50'
                            : 'bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          {result.status === 'success' || result.status === 'completed' ? (
                            <CheckCircle className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                          ) : result.status === 'partial' ? (
                            <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                          ) : (
                            <XCircle className="w-4 h-4 text-red-600 dark:text-red-400" />
                          )}
                          <span
                            className={`text-sm font-medium ${
                              result.status === 'success' || result.status === 'completed'
                                ? 'text-emerald-700 dark:text-emerald-300'
                                : result.status === 'partial'
                                ? 'text-amber-700 dark:text-amber-300'
                                : 'text-red-700 dark:text-red-300'
                            }`}
                          >
                            {result.status === 'success' || result.status === 'completed'
                              ? 'Success'
                              : result.status === 'partial'
                              ? 'Partial'
                              : 'Failed'}
                            {isDryRun && ' (Dry Run)'}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
                          {result.duration_ms && (
                            <span className="flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              {result.duration_ms}ms
                            </span>
                          )}
                          {result.items_processed !== undefined && (
                            <span>{result.items_processed} processed</span>
                          )}
                          {result.items_failed !== undefined && result.items_failed > 0 && (
                            <span className="text-red-500">{result.items_failed} failed</span>
                          )}
                        </div>
                      </div>

                      {/* Message */}
                      {result.message && (
                        <p className="text-sm text-gray-700 dark:text-gray-300">
                          {result.message}
                        </p>
                      )}

                      {/* Error */}
                      {result.error && (
                        <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50">
                          <p className="text-sm text-red-600 dark:text-red-400 font-mono">
                            {result.error}
                          </p>
                        </div>
                      )}

                      {/* Data Output */}
                      {result.data !== undefined && (
                        <div className="flex-1 min-h-0">
                          <div className="flex items-center gap-2 mb-2">
                            <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                              Result Data
                            </h4>
                            {Array.isArray(result.data) && (
                              <span className="text-xs text-gray-400">
                                ({result.data.length} item{result.data.length !== 1 ? 's' : ''})
                              </span>
                            )}
                          </div>
                          <OutputViewer data={result.data} className="h-[calc(100%-24px)]" />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    </div>
  )
}

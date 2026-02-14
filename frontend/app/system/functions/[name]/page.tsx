'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { systemCwrApi, contractsApi, type FunctionMeta, type ToolContract, getParametersFromSchema } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import { Button } from '@/components/ui/Button'
import {
  ArrowLeft,
  Brain,
  Tag,
  Code,
  BookOpen,
  AlertTriangle,
  Zap,
  ChevronRight,
  ChevronDown,
  Shield,
  Layers,
  Info,
  ExternalLink,
  Server,
  Loader2,
} from 'lucide-react'

// ============================================================================
// JSON Schema Viewer Component
// ============================================================================

function SchemaViewer({ schema, title }: { schema: Record<string, unknown>; title: string }) {
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

export default function SystemFunctionDetailPage() {
  const params = useParams()
  const router = useRouter()
  const { token } = useAuth()
  const functionName = params.name as string

  const [func, setFunc] = useState<FunctionMeta | null>(null)
  const [contract, setContract] = useState<ToolContract | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  // Load function metadata and contract
  const loadFunction = useCallback(async () => {
    if (!functionName) return

    setIsLoading(true)
    setError('')

    try {
      const [data, contractData] = await Promise.all([
        systemCwrApi.getFunction(functionName),
        contractsApi.getContract(token ?? undefined, functionName).catch(() => null),
      ])
      setFunc(data)
      setContract(contractData)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load function'
      setError(message)
    } finally {
      setIsLoading(false)
    }
  }, [token, functionName])

  useEffect(() => {
    loadFunction()
  }, [loadFunction])

  // Loading state
  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="flex items-center justify-center h-screen">
          <div className="flex flex-col items-center">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-amber-500 animate-spin"></div>
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
            <Button onClick={() => router.push('/system/functions')}>
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Functions
            </Button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      {/* Header */}
      <div className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
        <div className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-3">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.push('/system/functions')}
              className="p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
            <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 text-white shadow-lg shadow-amber-500/25">
              <BookOpen className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900 dark:text-white font-mono">
                {func.name}
              </h1>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Function Detail (Read-only)
              </p>
            </div>

            {/* Category & Governance Badges in header */}
            <div className="flex items-center gap-2 ml-4 flex-wrap">
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 capitalize">
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

      {/* Main Content */}
      <div className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Left Column: Description & Governance */}
          <div className="space-y-6">
            {/* Description */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                <div className="flex items-center gap-2">
                  <BookOpen className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                  <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                    Description
                  </h2>
                </div>
              </div>
              <div className="p-4 space-y-4">
                <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
                  {func.description}
                </p>

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
              </div>
            </div>

            {/* Governance */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                <div className="flex items-center gap-2">
                  <Shield className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                  <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                    Governance
                  </h2>
                </div>
              </div>
              <div className="p-4 space-y-2">
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
                        <span className="px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 text-[10px] font-medium">
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

            {/* Contract JSON Schemas */}
            {contract && (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                  <div className="flex items-center gap-2">
                    <Code className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                    <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                      Contract Schemas
                    </h2>
                  </div>
                </div>
                <div className="p-4 space-y-4">
                  <SchemaViewer
                    schema={contract.input_schema}
                    title="Input JSON Schema"
                  />
                  <SchemaViewer
                    schema={contract.output_schema}
                    title="Output JSON Schema"
                  />
                </div>
              </div>
            )}
          </div>

          {/* Right Column: Parameters, Output, Examples */}
          <div className="space-y-6">
            {/* Parameters */}
            {(() => { const paramList = getParametersFromSchema(func); return paramList.length > 0 && (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                  <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                    Parameters ({paramList.length})
                  </h2>
                </div>
                <div className="p-4 space-y-3">
                  {paramList.map((param) => (
                    <div key={param.name} className="text-sm">
                      <div className="flex items-center gap-2 mb-1">
                        <code className="text-xs font-mono font-medium text-amber-600 dark:text-amber-400">
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
            ); })()}

            {/* Output Schema */}
            {func.output_schema && (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                  <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                    Returns
                  </h2>
                </div>
                <div className="p-4">
                  <div className="text-sm">
                    <code className="text-xs font-mono font-medium text-emerald-600 dark:text-emerald-400">
                      {func.output_schema.type}
                    </code>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 leading-relaxed">
                      {func.output_schema.description}
                    </p>
                    {func.output_schema.fields && func.output_schema.fields.length > 0 && (
                      <div className="mt-3 space-y-2">
                        {(func.output_schema.fields as Array<{ name: string; type: string; nullable?: boolean }>).map((field) => (
                          <div key={field.name} className="flex items-start gap-2 text-xs">
                            <code className="font-mono text-amber-600 dark:text-amber-400 flex-shrink-0">
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
                      {(func.output_variants as Array<{ mode: string; condition: string; schema: { type: string } }>).map((variant, idx) => (
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
              </div>
            )}

            {/* Examples */}
            {func.examples && func.examples.length > 0 && (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                  <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                    Examples ({func.examples.length})
                  </h2>
                </div>
                <div className="p-4 space-y-2">
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
          </div>
        </div>
      </div>
    </div>
  )
}

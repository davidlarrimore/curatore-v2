'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { functionsApi, systemApi, type FunctionMeta, type FunctionExecuteResult } from '@/lib/api'
import type { LLMConnectionStatus } from '@/types'
import { generateFunctionYaml } from '@/lib/yaml-generator'
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
  Settings2,
  FileCode,
  AlertTriangle,
  Zap,
  Server,
} from 'lucide-react'

export default function FunctionLabPage() {
  return (
    <ProtectedRoute>
      <FunctionLabContent />
    </ProtectedRoute>
  )
}

function FunctionLabContent() {
  const params = useParams()
  const router = useRouter()
  const { token } = useAuth()
  const functionName = params.name as string

  const [func, setFunc] = useState<FunctionMeta | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  // LLM connection status (for functions that require LLM)
  const [llmStatus, setLlmStatus] = useState<LLMConnectionStatus | null>(null)
  const [isLoadingLlm, setIsLoadingLlm] = useState(false)

  // Parameter values
  const [paramValues, setParamValues] = useState<Record<string, any>>({})

  // Execution state
  const [isExecuting, setIsExecuting] = useState(false)
  const [isDryRun, setIsDryRun] = useState(false)
  const [result, setResult] = useState<FunctionExecuteResult | null>(null)
  const [executionKey, setExecutionKey] = useState(0)

  // YAML copy state
  const [copied, setCopied] = useState(false)

  // Load LLM status
  const loadLlmStatus = useCallback(async () => {
    setIsLoadingLlm(true)
    try {
      const status = await systemApi.getLLMStatus()
      setLlmStatus(status)

      // Pre-populate the model parameter with the default LLM model
      if (status.connected && status.model) {
        setParamValues((prev) => ({ ...prev, model: status.model }))
      }
    } catch (err) {
      console.error('Failed to load LLM status:', err)
      // Don't show error to user - LLM status is optional info
    } finally {
      setIsLoadingLlm(false)
    }
  }, [])

  // Load function metadata
  const loadFunction = useCallback(async () => {
    if (!token || !functionName) return

    setIsLoading(true)
    setError('')

    try {
      const data = await functionsApi.getFunction(token, functionName)
      setFunc(data)

      // Initialize default values
      const defaults: Record<string, any> = {}
      for (const param of data.parameters || []) {
        if (param.default !== undefined) {
          defaults[param.name] = param.default
        }
      }
      setParamValues(defaults)

      // Load LLM status if function requires LLM
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

  // Update a parameter value
  const handleParamChange = (name: string, value: any) => {
    setParamValues((prev) => ({ ...prev, [name]: value }))
  }

  // Execute the function
  const handleExecute = async (dryRun: boolean) => {
    if (!token || !func) return

    setIsExecuting(true)
    setIsDryRun(dryRun)
    setResult(null)
    setExecutionKey((k) => k + 1)

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

  // Generate YAML output
  const yamlOutput = useMemo(() => {
    if (!func) return ''
    return generateFunctionYaml(func.name, paramValues)
  }, [func, paramValues])

  // Copy YAML to clipboard
  const handleCopyYaml = async () => {
    try {
      await navigator.clipboard.writeText(yamlOutput)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  // Check if required params are filled
  const canExecute = useMemo(() => {
    if (!func) return false

    // Check LLM connection if required
    if (func.requires_llm && (!llmStatus || !llmStatus.connected)) {
      return false
    }

    // Check required params are filled
    const requiredParams = func.parameters?.filter((p) => p.required) || []
    return requiredParams.every((p) => {
      const val = paramValues[p.name]
      if (val === undefined || val === null) return false
      if (val === '') return false
      if (Array.isArray(val) && val.length === 0) return false
      return true
    })
  }, [func, paramValues, llmStatus])

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin"></div>
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading function...</p>
          </div>
        </div>
      </div>
    )
  }

  if (error || !func) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-12 text-center">
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

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-start gap-4">
              <button
                onClick={() => router.push('/admin/functions')}
                className="mt-1 p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
              >
                <ArrowLeft className="w-5 h-5" />
              </button>
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-purple-500 to-indigo-600 text-white shadow-lg shadow-purple-500/25 flex-shrink-0">
                <FlaskConical className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white font-mono">
                  {func.name}
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  Functions Lab - Test and generate YAML
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                onClick={() => handleExecute(true)}
                disabled={isExecuting || !canExecute}
                className="gap-2"
              >
                {isExecuting && isDryRun ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <FlaskConical className="w-4 h-4" />
                )}
                Dry Run
              </Button>
              <Button
                variant="primary"
                onClick={() => handleExecute(false)}
                disabled={isExecuting || !canExecute}
                className="gap-2"
              >
                {isExecuting && !isDryRun ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Play className="w-4 h-4" />
                )}
                Run
              </Button>
            </div>
          </div>
        </div>

        {/* LLM Not Connected Warning */}
        {func.requires_llm && llmStatus && !llmStatus.connected && (
          <div className="mb-6 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-100 dark:border-amber-900/50 p-4">
            <div className="flex items-center gap-3">
              <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 flex-shrink-0" />
              <div>
                <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
                  LLM Connection Required
                </p>
                <p className="text-sm text-amber-700 dark:text-amber-300 mt-0.5">
                  This function requires an LLM connection. Configure one in{' '}
                  <a href="/connections" className="underline hover:text-amber-900 dark:hover:text-amber-100">
                    Connections
                  </a>{' '}
                  to execute this function.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Main Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left Column: Documentation */}
          <div className="space-y-6">
            {/* Description Card */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                <div className="flex items-center gap-2">
                  <BookOpen className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                  <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                    Documentation
                  </h2>
                </div>
              </div>
              <div className="p-6 space-y-4">
                <p className="text-sm text-gray-700 dark:text-gray-300">{func.description}</p>

                {/* Metadata */}
                <div className="flex flex-wrap gap-2">
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 capitalize">
                    <Code className="w-3 h-3" />
                    {func.category}
                  </span>
                  {func.requires_llm && (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300">
                      <Brain className="w-3 h-3" />
                      Requires LLM
                    </span>
                  )}
                  {func.version && (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                      v{func.version}
                    </span>
                  )}
                </div>

                {/* Tags */}
                {func.tags && func.tags.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {func.tags.map((tag) => (
                      <span
                        key={tag}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                      >
                        <Tag className="w-3 h-3" />
                        {tag}
                      </span>
                    ))}
                  </div>
                )}

                {/* Returns */}
                {func.returns && (
                  <div className="pt-3 border-t border-gray-200 dark:border-gray-700">
                    <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                      Returns
                    </h4>
                    <p className="text-sm font-mono text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/50 px-3 py-2 rounded-lg">
                      {func.returns}
                    </p>
                  </div>
                )}

                {/* LLM Connection Info */}
                {func.requires_llm && (
                  <div className="pt-3 border-t border-gray-200 dark:border-gray-700">
                    <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                      LLM Connection
                    </h4>
                    {isLoadingLlm ? (
                      <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Loading LLM status...
                      </div>
                    ) : llmStatus ? (
                      <div className={`p-3 rounded-lg ${llmStatus.connected ? 'bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-100 dark:border-emerald-900/50' : 'bg-amber-50 dark:bg-amber-900/20 border border-amber-100 dark:border-amber-900/50'}`}>
                        <div className="flex items-center gap-2 mb-2">
                          {llmStatus.connected ? (
                            <Zap className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                          ) : (
                            <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                          )}
                          <span className={`text-sm font-medium ${llmStatus.connected ? 'text-emerald-700 dark:text-emerald-300' : 'text-amber-700 dark:text-amber-300'}`}>
                            {llmStatus.connected ? 'Connected' : 'Not Connected'}
                          </span>
                        </div>
                        {llmStatus.connected && (
                          <div className="space-y-1.5">
                            <div className="flex items-center gap-2 text-sm">
                              <Brain className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" />
                              <span className="text-gray-600 dark:text-gray-400">Model:</span>
                              <span className="font-mono font-medium text-gray-900 dark:text-white">
                                {llmStatus.model}
                              </span>
                            </div>
                            {llmStatus.endpoint && (
                              <div className="flex items-center gap-2 text-sm">
                                <Server className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" />
                                <span className="text-gray-600 dark:text-gray-400">Endpoint:</span>
                                <span className="font-mono text-xs text-gray-700 dark:text-gray-300 truncate max-w-[200px]" title={llmStatus.endpoint}>
                                  {llmStatus.endpoint}
                                </span>
                              </div>
                            )}
                          </div>
                        )}
                        {!llmStatus.connected && llmStatus.error && (
                          <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">
                            {llmStatus.error}
                          </p>
                        )}
                      </div>
                    ) : (
                      <div className="p-3 rounded-lg bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-700">
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                          Unable to load LLM connection status
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* YAML Output Card */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <FileCode className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                    <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                      YAML Output
                    </h2>
                  </div>
                  <button
                    onClick={handleCopyYaml}
                    className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
                  >
                    {copied ? (
                      <>
                        <Check className="w-3 h-3 text-emerald-500" />
                        Copied!
                      </>
                    ) : (
                      <>
                        <Copy className="w-3 h-3" />
                        Copy
                      </>
                    )}
                  </button>
                </div>
              </div>
              <div className="p-4">
                <pre className="text-sm font-mono bg-gray-900 dark:bg-gray-950 text-emerald-300 p-4 rounded-lg overflow-x-auto">
                  {yamlOutput}
                </pre>
                <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
                  Use this YAML in your procedure or pipeline definitions.
                </p>
              </div>
            </div>
          </div>

          {/* Right Column: Parameters & Results */}
          <div className="space-y-6">
            {/* Parameters Card */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                <div className="flex items-center gap-2">
                  <Settings2 className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                  <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                    Parameters
                  </h2>
                </div>
              </div>
              <div className="p-6">
                {!func.parameters || func.parameters.length === 0 ? (
                  <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-4">
                    This function has no parameters.
                  </p>
                ) : (
                  <div className="space-y-5">
                    {func.parameters.map((param) => {
                      // Check if this is the model param for an LLM function
                      const isLlmModelParam = param.name === 'model' && func.requires_llm
                      const isDisabled = isExecuting || isLlmModelParam

                      return (
                        <div key={param.name} className="space-y-2">
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
                                from LLM connection
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
            </div>

            {/* Execution Result Card */}
            {result && (
              <div key={executionKey} className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
                <div
                  className={`px-6 py-4 border-b ${
                    result.status === 'success' || result.status === 'completed'
                      ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-100 dark:border-emerald-900/50'
                      : result.status === 'partial'
                      ? 'bg-amber-50 dark:bg-amber-900/20 border-amber-100 dark:border-amber-900/50'
                      : 'bg-red-50 dark:bg-red-900/20 border-red-100 dark:border-red-900/50'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      {result.status === 'success' || result.status === 'completed' ? (
                        <CheckCircle className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                      ) : result.status === 'partial' ? (
                        <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                      ) : (
                        <XCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
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
                          ? 'Partial Success'
                          : 'Failed'}
                        {isDryRun && ' (Dry Run)'}
                      </span>
                    </div>
                    {result.duration_ms && (
                      <span className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
                        <Clock className="w-3 h-3" />
                        {result.duration_ms}ms
                      </span>
                    )}
                  </div>
                </div>
                <div className="p-4 space-y-3">
                  {result.message && (
                    <p className="text-sm text-gray-700 dark:text-gray-300">{result.message}</p>
                  )}
                  {result.error && (
                    <p className="text-sm text-red-600 dark:text-red-400">{result.error}</p>
                  )}
                  {result.data !== undefined && (
                    <div>
                      <h4 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                        Result Data
                        {Array.isArray(result.data) && (
                          <span className="ml-2 text-gray-400 normal-case font-normal">
                            ({result.data.length} item{result.data.length !== 1 ? 's' : ''})
                          </span>
                        )}
                      </h4>
                      <pre className="text-xs font-mono text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/50 p-3 rounded-lg overflow-auto max-h-64">
                        {JSON.stringify(result.data, null, 2)}
                      </pre>
                    </div>
                  )}
                  {(result.items_processed !== undefined || result.items_failed !== undefined) && (
                    <div className="flex gap-4 text-xs text-gray-500 dark:text-gray-400 pt-2 border-t border-gray-200 dark:border-gray-700">
                      {result.items_processed !== undefined && (
                        <span>Processed: {result.items_processed}</span>
                      )}
                      {result.items_failed !== undefined && result.items_failed > 0 && (
                        <span className="text-red-500">Failed: {result.items_failed}</span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

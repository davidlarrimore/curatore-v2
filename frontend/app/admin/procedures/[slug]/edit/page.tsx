'use client'

import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useRouter, useParams } from 'next/navigation'
import YAML from 'yaml'
import { useAuth } from '@/lib/auth-context'
import { useActiveJobs } from '@/lib/context-shims'
import {
  proceduresApi,
  functionsApi,
  type UpdateProcedureRequest,
  type ValidationError,
  type FunctionMeta,
  type Procedure,
} from '@/lib/api'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  Save,
  Play,
  RotateCcw,
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Search,
  Code,
  Loader2,
  ArrowLeft,
  X,
  Copy,
  Trash2,
  Settings,
  Sparkles,
} from 'lucide-react'
import { AIGeneratorPanel, type AIGeneratorPanelHandle } from '@/components/procedures/AIGeneratorPanel'

export default function EditProcedurePage() {
  return (
    <ProtectedRoute>
      <ProcedureEditor />
    </ProtectedRoute>
  )
}

function ProcedureEditor() {
  const router = useRouter()
  const params = useParams()
  const slug = params.slug as string
  const { token } = useAuth()
  const { addJob } = useActiveJobs()

  // Procedure state
  const [procedure, setProcedure] = useState<Procedure | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  // Editor state
  const [yamlContent, setYamlContent] = useState('')
  const [savedYaml, setSavedYaml] = useState('')
  const [isDirty, setIsDirty] = useState(false)

  // UI state
  const [isSaving, setIsSaving] = useState(false)
  const [isRunning, setIsRunning] = useState(false)
  const [isValidating, setIsValidating] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [successMessage, setSuccessMessage] = useState('')
  const [errorMessage, setErrorMessage] = useState('')

  // Validation state
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([])
  const [validationWarnings, setValidationWarnings] = useState<ValidationError[]>([])
  const [validationPassed, setValidationPassed] = useState(false)

  // Function catalog state
  const [functions, setFunctions] = useState<FunctionMeta[]>([])
  const [loadingFunctions, setLoadingFunctions] = useState(true)

  // Ref to AI Generator panel for programmatic control
  const aiGeneratorRef = useRef<AIGeneratorPanelHandle>(null)
  const [functionSearch, setFunctionSearch] = useState('')
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(['llm', 'output', 'search']))
  const [expandedFunctions, setExpandedFunctions] = useState<Set<string>>(new Set())

  // Load procedure
  useEffect(() => {
    if (!token || !slug) return

    const loadProcedure = async () => {
      try {
        const proc = await proceduresApi.getProcedure(token, slug)
        setProcedure(proc)

        // Convert definition to YAML
        const yaml = YAML.stringify(proc.definition)
        setYamlContent(yaml)
        setSavedYaml(yaml)
      } catch (err: any) {
        setLoadError(err.message || 'Failed to load procedure')
      } finally {
        setIsLoading(false)
      }
    }

    loadProcedure()
  }, [token, slug])

  // Load functions
  useEffect(() => {
    if (!token) return

    const loadFunctions = async () => {
      try {
        const funcsData = await functionsApi.listFunctions(token)
        setFunctions(funcsData.functions)
      } catch (err: any) {
        console.error('Failed to load functions:', err)
      } finally {
        setLoadingFunctions(false)
      }
    }

    loadFunctions()
  }, [token])

  // Track dirty state
  useEffect(() => {
    setIsDirty(yamlContent !== savedYaml)
  }, [yamlContent, savedYaml])

  // Parse name and slug from YAML for display
  const parsedInfo = useMemo(() => {
    try {
      const data = YAML.parse(yamlContent)
      return {
        name: data.name || '',
        slug: data.slug || '',
        description: data.description || '',
      }
    } catch {
      return { name: '', slug: '', description: '' }
    }
  }, [yamlContent])

  // Parse YAML to get procedure data
  const parseProcedure = useCallback((): UpdateProcedureRequest | null => {
    try {
      const data = YAML.parse(yamlContent)
      return {
        name: data.name || '',
        description: data.description || '',
        parameters: data.parameters || [],
        steps: data.steps || [],
        on_error: data.on_error || 'fail',
        tags: data.tags || [],
      }
    } catch (err) {
      return null
    }
  }, [yamlContent])

  // Validate procedure
  const handleValidate = useCallback(async () => {
    if (!token) return

    const data = parseProcedure()
    if (!data) {
      setValidationErrors([{
        code: 'INVALID_YAML',
        message: 'Invalid YAML syntax',
        path: '',
        details: {},
      }])
      return false
    }

    // Build full procedure for validation
    const fullProc = {
      name: data.name || procedure?.name || '',
      slug: procedure?.slug || '',
      description: data.description,
      parameters: data.parameters,
      steps: data.steps || [],
      on_error: data.on_error,
      tags: data.tags,
    }

    setIsValidating(true)
    setValidationPassed(false)
    try {
      const result = await proceduresApi.validateProcedure(token, fullProc as any)
      setValidationErrors(result.errors)
      setValidationWarnings(result.warnings)
      // Show success indicator if valid (even with warnings)
      if (result.valid) {
        setValidationPassed(true)
        // Auto-hide success after 5 seconds if no warnings
        if (result.warnings.length === 0) {
          setTimeout(() => setValidationPassed(false), 5000)
        }
      }
      return result.valid
    } catch (err: any) {
      setErrorMessage(err.message || 'Validation failed')
      setTimeout(() => setErrorMessage(''), 5000)
      return false
    } finally {
      setIsValidating(false)
    }
  }, [token, parseProcedure, procedure])

  // Save procedure
  const handleSave = async () => {
    if (!token || !procedure) return

    const data = parseProcedure()
    if (!data) {
      setValidationErrors([{
        code: 'INVALID_YAML',
        message: 'Invalid YAML syntax',
        path: '',
        details: {},
      }])
      return
    }

    setIsSaving(true)
    setValidationErrors([])
    setValidationWarnings([])
    setValidationPassed(false)

    try {
      const saved = await proceduresApi.updateProcedure(token, procedure.slug, data)
      setProcedure(saved)

      // Update saved YAML
      const yaml = YAML.stringify(saved.definition)
      setSavedYaml(yaml)
      setYamlContent(yaml)

      setSuccessMessage(`Procedure saved (v${saved.version})!`)
      setTimeout(() => setSuccessMessage(''), 3000)
    } catch (err: any) {
      if (err.validation) {
        setValidationErrors(err.validation.errors || [])
        setValidationWarnings(err.validation.warnings || [])
        setErrorMessage('Validation failed. See errors below.')
      } else {
        setErrorMessage(err.message || 'Failed to save procedure')
      }
      setTimeout(() => setErrorMessage(''), 5000)
    } finally {
      setIsSaving(false)
    }
  }

  // Run procedure
  const handleRun = async () => {
    if (!token || !procedure) return

    setIsRunning(true)
    try {
      const result = await proceduresApi.runProcedure(token, procedure.slug, {}, false, true)
      if (result.run_id) {
        addJob({
          runId: result.run_id,
          jobType: 'procedure',
          displayName: procedure.name,
          resourceId: procedure.slug,
          resourceType: 'procedure',
        })
      }
      setSuccessMessage(`Procedure started! Run ID: ${result.run_id}`)
      setTimeout(() => setSuccessMessage(''), 5000)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to run procedure')
      setTimeout(() => setErrorMessage(''), 5000)
    } finally {
      setIsRunning(false)
    }
  }

  // Delete procedure
  const handleDelete = async () => {
    if (!token || !procedure) return

    setIsDeleting(true)
    try {
      await proceduresApi.deleteProcedure(token, procedure.slug)
      setSuccessMessage('Procedure deleted')
      router.push('/admin/procedures')
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to delete procedure')
      setTimeout(() => setErrorMessage(''), 5000)
    } finally {
      setIsDeleting(false)
      setShowDeleteConfirm(false)
    }
  }

  // Reset to saved version
  const handleReset = () => {
    setYamlContent(savedYaml)
    setValidationErrors([])
    setValidationWarnings([])
  }

  // Toggle category expansion
  const toggleCategory = (category: string) => {
    const newExpanded = new Set(expandedCategories)
    if (newExpanded.has(category)) {
      newExpanded.delete(category)
    } else {
      newExpanded.add(category)
    }
    setExpandedCategories(newExpanded)
  }

  // Toggle function expansion
  const toggleFunction = (funcName: string) => {
    const newExpanded = new Set(expandedFunctions)
    if (newExpanded.has(funcName)) {
      newExpanded.delete(funcName)
    } else {
      newExpanded.add(funcName)
    }
    setExpandedFunctions(newExpanded)
  }

  // Copy function snippet
  const copyFunctionSnippet = (func: FunctionMeta) => {
    const params: Record<string, any> = {}
    func.parameters.forEach(p => {
      if (p.required) {
        params[p.name] = p.example || p.default || `<${p.type}>`
      }
    })

    const snippet = YAML.stringify({
      name: func.name.replace('llm_', '').replace('_', '-'),
      function: func.name,
      params,
    })

    navigator.clipboard.writeText(snippet)
    setSuccessMessage(`Copied ${func.name} snippet to clipboard`)
    setTimeout(() => setSuccessMessage(''), 2000)
  }

  // Filter functions by search
  const filteredFunctions = useMemo(() => {
    if (!functionSearch.trim()) return functions

    const query = functionSearch.toLowerCase()
    return functions.filter(fn =>
      fn.name.toLowerCase().includes(query) ||
      fn.description.toLowerCase().includes(query) ||
      fn.category.toLowerCase().includes(query)
    )
  }, [functions, functionSearch])

  // Group filtered functions by category
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

  // Loading state
  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950 flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-8 h-8 animate-spin mx-auto text-indigo-500" />
          <p className="mt-4 text-gray-500 dark:text-gray-400">Loading procedure...</p>
        </div>
      </div>
    )
  }

  // Error state
  if (loadError) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950 flex items-center justify-center">
        <div className="text-center">
          <AlertTriangle className="w-12 h-12 mx-auto text-red-500" />
          <h2 className="mt-4 text-xl font-bold text-gray-900 dark:text-white">Failed to load procedure</h2>
          <p className="mt-2 text-gray-500 dark:text-gray-400">{loadError}</p>
          <Button
            variant="secondary"
            onClick={() => router.push('/admin/procedures')}
            className="mt-6"
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to Procedures
          </Button>
        </div>
      </div>
    )
  }

  const isSystemProcedure = procedure?.source_type !== 'user'

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      {/* Header */}
      <div className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
        <div className="max-w-[1800px] mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <button
                onClick={() => router.push('/admin/procedures')}
                className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
              >
                <ArrowLeft className="w-5 h-5" />
              </button>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-xl font-bold text-gray-900 dark:text-white">
                    {parsedInfo.name || procedure?.name || 'Procedure'}
                  </h1>
                  {isSystemProcedure && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                      <Settings className="w-3 h-3" />
                      System
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  v{procedure?.version} - <span className="font-mono">{parsedInfo.slug || procedure?.slug}</span>
                </p>
              </div>
              {isDirty && (
                <span className="px-2 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                  Unsaved changes
                </span>
              )}
            </div>

            {/* Control buttons */}
            <div className="flex items-center gap-3">
              {!isSystemProcedure && (
                <Button
                  variant="secondary"
                  onClick={() => setShowDeleteConfirm(true)}
                  disabled={isDeleting}
                  className="gap-2 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
                >
                  <Trash2 className="w-4 h-4" />
                  Delete
                </Button>
              )}
              <Button
                variant="secondary"
                onClick={handleReset}
                disabled={!isDirty}
                className="gap-2"
              >
                <RotateCcw className="w-4 h-4" />
                Reset
              </Button>
              <Button
                variant="secondary"
                onClick={handleRun}
                disabled={isRunning || isDirty}
                className="gap-2"
                title={isDirty ? 'Save changes before running' : undefined}
              >
                {isRunning ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Play className="w-4 h-4" />
                )}
                Run
              </Button>
              {!isSystemProcedure && (
                <Button
                  variant="primary"
                  onClick={handleSave}
                  disabled={isSaving}
                  className="gap-2"
                >
                  {isSaving ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Save className="w-4 h-4" />
                  )}
                  Save
                </Button>
              )}
            </div>
          </div>

          {/* System procedure notice */}
          {isSystemProcedure && (
            <div className="mt-4 rounded-lg bg-purple-50 dark:bg-purple-900/20 border border-purple-100 dark:border-purple-900/50 p-3">
              <div className="flex items-center gap-2">
                <Settings className="w-4 h-4 text-purple-600 dark:text-purple-400" />
                <p className="text-sm text-purple-800 dark:text-purple-200">
                  This is a system procedure. To edit it, modify the YAML file at{' '}
                  <code className="text-xs bg-purple-100 dark:bg-purple-800/30 px-1 py-0.5 rounded">
                    {procedure?.source_type === 'yaml' ? 'backend/app/procedures/definitions/' : ''}
                  </code>{' '}
                  and call the reload endpoint.
                </p>
              </div>
            </div>
          )}

          {/* Success/Error messages */}
          {successMessage && (
            <div className="mt-4 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-100 dark:border-emerald-900/50 p-3">
              <div className="flex items-center gap-2">
                <CheckCircle className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                <p className="text-sm text-emerald-800 dark:text-emerald-200">{successMessage}</p>
              </div>
            </div>
          )}

          {errorMessage && (
            <div className="mt-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-3">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-red-600 dark:text-red-400" />
                <p className="text-sm text-red-800 dark:text-red-200">{errorMessage}</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Delete confirmation modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 max-w-md mx-4 shadow-xl">
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">Delete Procedure?</h3>
            <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
              Are you sure you want to delete "{procedure?.name}"? This action cannot be undone.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <Button
                variant="secondary"
                onClick={() => setShowDeleteConfirm(false)}
                disabled={isDeleting}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleDelete}
                disabled={isDeleting}
                className="bg-red-600 hover:bg-red-700"
              >
                {isDeleting ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  'Delete'
                )}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Main content - two panels */}
      <div className="max-w-[1800px] mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left panel - Editor */}
          <div className="lg:col-span-2 space-y-4">
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-gray-900 dark:text-white">
                    Procedure Definition (YAML)
                  </h2>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(yamlContent)
                        setSuccessMessage('YAML copied to clipboard')
                        setTimeout(() => setSuccessMessage(''), 2000)
                      }}
                      className="p-1.5 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
                      title="Copy YAML"
                    >
                      <Copy className="w-4 h-4" />
                    </button>
                    <button
                      onClick={handleValidate}
                      disabled={isValidating}
                      className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-lg bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-100 dark:hover:bg-indigo-900/30 transition-colors"
                    >
                      {isValidating ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <CheckCircle className="w-3 h-3" />
                      )}
                      Validate
                    </button>
                  </div>
                </div>
              </div>
              <textarea
                value={yamlContent}
                onChange={(e) => setYamlContent(e.target.value)}
                className="w-full h-[700px] p-4 font-mono text-sm bg-gray-900 text-gray-100 focus:outline-none resize-none"
                placeholder="Enter procedure YAML..."
                spellCheck={false}
                readOnly={isSystemProcedure}
              />
            </div>

            {/* Validation success panel */}
            {validationPassed && validationErrors.length === 0 && validationWarnings.length === 0 && (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-emerald-200 dark:border-emerald-700 overflow-hidden">
                <div className="px-4 py-3 bg-emerald-50 dark:bg-emerald-900/20">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <CheckCircle className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                      <h2 className="text-sm font-semibold text-emerald-800 dark:text-emerald-200">
                        Validation Passed
                      </h2>
                      <span className="text-xs text-emerald-600 dark:text-emerald-400">
                        No errors or warnings found
                      </span>
                    </div>
                    <button
                      onClick={() => setValidationPassed(false)}
                      className="p-1 rounded hover:bg-emerald-100 dark:hover:bg-emerald-900/30"
                    >
                      <X className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Validation with warnings panel (valid but has warnings) */}
            {validationPassed && validationErrors.length === 0 && validationWarnings.length > 0 && (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-amber-200 dark:border-amber-700 overflow-hidden">
                <div className="px-4 py-3 border-b border-amber-200 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <CheckCircle className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                      <h2 className="text-sm font-semibold text-amber-800 dark:text-amber-200">
                        Valid with Warnings ({validationWarnings.length})
                      </h2>
                    </div>
                    <div className="flex items-center gap-2">
                      {!isSystemProcedure && (
                        <button
                          onClick={() => {
                            aiGeneratorRef.current?.fixValidationErrors([], validationWarnings)
                          }}
                          disabled={aiGeneratorRef.current?.isGenerating}
                          className="group inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200"
                          title="Use AI to fix these warnings"
                        >
                          <Sparkles className="w-3 h-3" />
                          Fix with AI
                        </button>
                      )}
                      <button
                        onClick={() => {
                          setValidationPassed(false)
                          setValidationWarnings([])
                        }}
                        className="p-1 rounded hover:bg-amber-100 dark:hover:bg-amber-900/30"
                      >
                        <X className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                      </button>
                    </div>
                  </div>
                </div>
                <div className="divide-y divide-amber-200 dark:divide-amber-700">
                  {validationWarnings.map((warning, idx) => (
                    <div key={`warn-${idx}`} className="px-4 py-3">
                      <div className="flex items-start gap-3">
                        <div className="w-6 h-6 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center flex-shrink-0">
                          <AlertTriangle className="w-3 h-3 text-amber-600 dark:text-amber-400" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-gray-900 dark:text-white">
                            {warning.message}
                          </p>
                          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 font-mono">
                            Path: {warning.path || '(root)'} | Code: {warning.code}
                          </p>
                          {warning.details && Object.keys(warning.details).length > 0 && (
                            <details className="mt-2">
                              <summary className="text-xs text-amber-600 dark:text-amber-400 cursor-pointer hover:text-amber-700 dark:hover:text-amber-300">
                                Show suggestion
                              </summary>
                              <div className="mt-1 text-xs text-gray-600 dark:text-gray-400 bg-amber-50 dark:bg-amber-900/20 p-2 rounded">
                                {warning.details.suggestion || JSON.stringify(warning.details, null, 2)}
                              </div>
                            </details>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Validation errors panel */}
            {validationErrors.length > 0 && (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-red-200 dark:border-red-700 overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-red-50 dark:bg-red-900/20">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 text-red-600 dark:text-red-400" />
                      <h2 className="text-sm font-semibold text-red-800 dark:text-red-200">
                        Validation Errors ({validationErrors.length})
                      </h2>
                    </div>
                    <div className="flex items-center gap-2">
                      {!isSystemProcedure && (
                        <button
                          onClick={() => {
                            aiGeneratorRef.current?.fixValidationErrors(validationErrors, validationWarnings)
                          }}
                          disabled={aiGeneratorRef.current?.isGenerating}
                          className="group inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-gradient-to-r from-indigo-500 to-purple-500 hover:from-indigo-600 hover:to-purple-600 text-white shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200"
                          title="Use AI to automatically fix these errors"
                        >
                          <Sparkles className="w-3 h-3" />
                          Fix with AI
                        </button>
                      )}
                      <button
                        onClick={() => {
                          setValidationErrors([])
                          setValidationWarnings([])
                          setValidationPassed(false)
                        }}
                        className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/30"
                      >
                        <X className="w-4 h-4 text-red-600 dark:text-red-400" />
                      </button>
                    </div>
                  </div>
                </div>
                <div className="divide-y divide-gray-200 dark:divide-gray-700">
                  {validationErrors.map((error, idx) => (
                    <div key={idx} className="px-4 py-3">
                      <div className="flex items-start gap-3">
                        <div className="w-6 h-6 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center flex-shrink-0">
                          <X className="w-3 h-3 text-red-600 dark:text-red-400" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-gray-900 dark:text-white">
                            {error.message}
                          </p>
                          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 font-mono">
                            Path: {error.path || '(root)'} | Code: {error.code}
                          </p>
                          {error.details && Object.keys(error.details).length > 0 && (
                            <details className="mt-2">
                              <summary className="text-xs text-gray-500 dark:text-gray-400 cursor-pointer hover:text-gray-700 dark:hover:text-gray-300">
                                Show details
                              </summary>
                              <pre className="mt-1 text-xs font-mono text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-900/50 p-2 rounded overflow-x-auto">
                                {JSON.stringify(error.details, null, 2)}
                              </pre>
                            </details>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                  {validationWarnings.map((warning, idx) => (
                    <div key={`warn-${idx}`} className="px-4 py-3 bg-amber-50/50 dark:bg-amber-900/10">
                      <div className="flex items-start gap-3">
                        <div className="w-6 h-6 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center flex-shrink-0">
                          <AlertTriangle className="w-3 h-3 text-amber-600 dark:text-amber-400" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-gray-900 dark:text-white">
                            {warning.message}
                          </p>
                          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 font-mono">
                            Path: {warning.path || '(root)'} | Code: {warning.code}
                          </p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Right panel - AI Generator + Function catalog */}
          <div className="lg:col-span-1 space-y-4">
            {/* AI Generator Panel */}
            <AIGeneratorPanel
              ref={aiGeneratorRef}
              currentYaml={yamlContent}
              onYamlGenerated={(yaml) => setYamlContent(yaml)}
              onSuccess={(msg) => {
                setSuccessMessage(msg)
                setValidationErrors([])
                setValidationWarnings([])
                setTimeout(() => setSuccessMessage(''), 5000)
              }}
              onError={(msg) => {
                setErrorMessage(msg)
                setTimeout(() => setErrorMessage(''), 5000)
              }}
            />

            {/* Function catalog */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden sticky top-6">
              <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
                <h2 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">
                  Function Catalog
                </h2>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Search functions..."
                    value={functionSearch}
                    onChange={(e) => setFunctionSearch(e.target.value)}
                    className="w-full pl-9 pr-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>

              <div className="max-h-[600px] overflow-y-auto">
                {loadingFunctions ? (
                  <div className="p-8 text-center">
                    <Loader2 className="w-6 h-6 animate-spin mx-auto text-gray-400" />
                    <p className="mt-2 text-sm text-gray-500">Loading functions...</p>
                  </div>
                ) : Object.keys(groupedFunctions).length === 0 ? (
                  <div className="p-8 text-center">
                    <Code className="w-8 h-8 mx-auto text-gray-300 dark:text-gray-600" />
                    <p className="mt-2 text-sm text-gray-500">No functions found</p>
                  </div>
                ) : (
                  <div className="divide-y divide-gray-200 dark:divide-gray-700">
                    {Object.entries(groupedFunctions).map(([category, funcs]) => (
                      <div key={category}>
                        <button
                          onClick={() => toggleCategory(category)}
                          className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700/50"
                        >
                          <span className="text-sm font-medium text-gray-900 dark:text-white capitalize">
                            {category}
                          </span>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-gray-500 dark:text-gray-400">
                              {funcs.length}
                            </span>
                            {expandedCategories.has(category) ? (
                              <ChevronDown className="w-4 h-4 text-gray-400" />
                            ) : (
                              <ChevronRight className="w-4 h-4 text-gray-400" />
                            )}
                          </div>
                        </button>

                        {expandedCategories.has(category) && (
                          <div className="bg-gray-50 dark:bg-gray-900/30">
                            {funcs.map((func) => (
                              <div key={func.name} className="border-t border-gray-100 dark:border-gray-800">
                                <div className="px-4 py-2">
                                  <div className="flex items-center justify-between">
                                    <button
                                      onClick={() => toggleFunction(func.name)}
                                      className="flex items-center gap-2 text-left group flex-1"
                                    >
                                      {expandedFunctions.has(func.name) ? (
                                        <ChevronDown className="w-3 h-3 text-gray-400 flex-shrink-0" />
                                      ) : (
                                        <ChevronRight className="w-3 h-3 text-gray-400 flex-shrink-0" />
                                      )}
                                      <span className="text-xs font-mono font-medium text-gray-700 dark:text-gray-300 group-hover:text-indigo-600 dark:group-hover:text-indigo-400">
                                        {func.name}
                                      </span>
                                    </button>
                                    <button
                                      onClick={() => copyFunctionSnippet(func)}
                                      className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700"
                                      title="Copy YAML snippet"
                                    >
                                      <Copy className="w-3 h-3 text-gray-400" />
                                    </button>
                                  </div>
                                  <p className="ml-5 text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
                                    {func.description}
                                  </p>

                                  {expandedFunctions.has(func.name) && (
                                    <div className="mt-2 ml-5 space-y-2">
                                      {func.parameters.length > 0 && (
                                        <div>
                                          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                                            Parameters
                                          </p>
                                          <div className="space-y-1">
                                            {func.parameters.map((param) => (
                                              <div key={param.name} className="flex items-start gap-2 text-xs">
                                                <span className="font-mono text-gray-700 dark:text-gray-300">
                                                  {param.name}
                                                </span>
                                                <span className="text-gray-400">:</span>
                                                <span className="text-gray-500">{param.type}</span>
                                                {param.required && (
                                                  <span className="px-1 py-0.5 rounded bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 text-[10px]">
                                                    required
                                                  </span>
                                                )}
                                              </div>
                                            ))}
                                          </div>
                                        </div>
                                      )}
                                      {func.returns && (
                                        <div>
                                          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                                            Returns
                                          </p>
                                          <p className="text-xs font-mono text-gray-600 dark:text-gray-400">
                                            {func.returns}
                                          </p>
                                        </div>
                                      )}
                                    </div>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

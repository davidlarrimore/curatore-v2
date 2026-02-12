'use client'

import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useRouter } from 'next/navigation'
import YAML from 'yaml'
import { useAuth } from '@/lib/auth-context'
import { useActiveJobs } from '@/lib/context-shims'
import {
  proceduresApi,
  functionsApi,
  type CreateProcedureRequest,
  type ValidationError,
  type ValidationResult,
  type FunctionMeta,
  type Procedure,
  getParametersFromSchema,
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
  Box,
  Sparkles,
  Zap,
  Brain,
  Shield,
  Tag,
} from 'lucide-react'
import { AIGeneratorPanel, type AIGeneratorPanelHandle } from '@/components/procedures/AIGeneratorPanel'

// Default procedure template
const DEFAULT_PROCEDURE_YAML = `name: My Procedure
slug: my_procedure
description: A new procedure

parameters:
  - name: example_param
    type: str
    description: An example parameter
    required: false
    default: "default value"

steps:
  - name: log_start
    function: log
    params:
      message: "Starting procedure with param: {{ params.example_param }}"
      level: INFO
      label: start

on_error: fail
tags:
  - custom
`

export default function NewProcedurePage() {
  return (
    <ProtectedRoute>
      <ProcedureEditor />
    </ProtectedRoute>
  )
}

function ProcedureEditor() {
  const router = useRouter()
  const { token } = useAuth()
  const { addJob } = useActiveJobs()

  // Editor state
  const [yamlContent, setYamlContent] = useState(DEFAULT_PROCEDURE_YAML)
  const [savedYaml, setSavedYaml] = useState(DEFAULT_PROCEDURE_YAML)
  const [isDirty, setIsDirty] = useState(false)

  // UI state
  const [isSaving, setIsSaving] = useState(false)
  const [isRunning, setIsRunning] = useState(false)
  const [isValidating, setIsValidating] = useState(false)
  const [successMessage, setSuccessMessage] = useState('')
  const [errorMessage, setErrorMessage] = useState('')

  // Validation state
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([])
  const [validationWarnings, setValidationWarnings] = useState<ValidationError[]>([])
  const [validationPassed, setValidationPassed] = useState(false)

  // Right panel tab state
  const [activeTab, setActiveTab] = useState<'generator' | 'catalog'>('generator')

  // Function catalog state
  const [functions, setFunctions] = useState<FunctionMeta[]>([])
  const [categories, setCategories] = useState<Record<string, string[]>>({})
  const [loadingFunctions, setLoadingFunctions] = useState(true)
  const [functionSearch, setFunctionSearch] = useState('')
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(['llm', 'output', 'search']))
  const [expandedFunctions, setExpandedFunctions] = useState<Set<string>>(new Set())

  // Saved procedure (after first save)
  const [savedProcedure, setSavedProcedure] = useState<Procedure | null>(null)

  // Ref to AI Generator panel for programmatic control
  const aiGeneratorRef = useRef<AIGeneratorPanelHandle>(null)

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

  // Track dirty state
  useEffect(() => {
    setIsDirty(yamlContent !== savedYaml)
  }, [yamlContent, savedYaml])

  // Load functions
  useEffect(() => {
    if (!token) return

    const loadFunctions = async () => {
      try {
        const [funcsData, catsData] = await Promise.all([
          functionsApi.listFunctions(token),
          functionsApi.getCategories(token),
        ])
        setFunctions(funcsData.functions)
        setCategories(catsData.categories || {})
      } catch (err: any) {
        console.error('Failed to load functions:', err)
      } finally {
        setLoadingFunctions(false)
      }
    }

    loadFunctions()
  }, [token])

  // Parse YAML to get procedure data
  const parseProcedure = useCallback((): CreateProcedureRequest | null => {
    try {
      const data = YAML.parse(yamlContent)
      return {
        name: data.name || '',
        slug: data.slug || '',
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

    const procedure = parseProcedure()
    if (!procedure) {
      setValidationErrors([{
        code: 'INVALID_YAML',
        message: 'Invalid YAML syntax',
        path: '',
        details: {},
      }])
      return false
    }

    setIsValidating(true)
    setValidationPassed(false)
    try {
      const result = await proceduresApi.validateProcedure(token, procedure)
      setValidationErrors(result.errors)
      setValidationWarnings(result.warnings)
      if (result.valid) {
        setValidationPassed(true)
        if (result.warnings.length === 0) {
          setSuccessMessage('Validation passed — no errors or warnings')
          setTimeout(() => setSuccessMessage(''), 5000)
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
  }, [token, parseProcedure])

  // Save procedure
  const handleSave = async () => {
    if (!token) return

    const procedure = parseProcedure()
    if (!procedure) {
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
      let saved: Procedure

      if (savedProcedure) {
        // Update existing procedure
        saved = await proceduresApi.updateProcedure(token, savedProcedure.slug, {
          name: procedure.name,
          description: procedure.description,
          parameters: procedure.parameters,
          steps: procedure.steps,
          on_error: procedure.on_error,
          tags: procedure.tags,
        })
      } else {
        // Create new procedure
        saved = await proceduresApi.createProcedure(token, procedure)
      }

      setSavedProcedure(saved)
      setSavedYaml(yamlContent)
      setSuccessMessage(`Procedure "${saved.name}" saved successfully!`)
      setTimeout(() => setSuccessMessage(''), 3000)

      // If this was a new procedure, update the URL
      if (!savedProcedure) {
        router.replace(`/admin/procedures/${saved.slug}/edit`)
      }
    } catch (err: any) {
      if (err.validation) {
        setValidationErrors(err.validation.errors || [])
        setValidationWarnings(err.validation.warnings || [])
        setErrorMessage('Validation failed. See errors below.')
      } else if (err.message?.includes('already exists')) {
        // Duplicate slug error
        setValidationErrors([{
          code: 'DUPLICATE_SLUG',
          message: err.message,
          path: 'slug',
          details: { slug: procedure.slug },
        }])
        setErrorMessage('A procedure with this slug already exists. Please use a unique slug.')
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
    if (!token || !savedProcedure) return

    setIsRunning(true)
    try {
      const result = await proceduresApi.runProcedure(token, savedProcedure.slug, {}, false, true)
      if (result.run_id) {
        addJob({
          runId: result.run_id,
          jobType: 'procedure',
          displayName: savedProcedure.name,
          resourceId: savedProcedure.slug,
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
    getParametersFromSchema(func).forEach(p => {
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
                <h1 className="text-xl font-bold text-gray-900 dark:text-white">
                  {savedProcedure
                    ? savedProcedure.name
                    : parsedInfo.name || 'New Procedure'}
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  {savedProcedure
                    ? `v${savedProcedure.version} - ${savedProcedure.slug}`
                    : parsedInfo.slug
                      ? <span className="font-mono">{parsedInfo.slug}</span>
                      : 'Create a new procedure'}
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
                disabled={!savedProcedure || isRunning || isDirty}
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
            </div>
          </div>

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

      {/* Main content - two panels */}
      <div className="max-w-[1800px] mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left panel - Editor */}
          <div className="space-y-4">
            <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
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
                className="w-full h-[500px] p-4 font-mono text-sm bg-gray-900 text-gray-100 focus:outline-none resize-none"
                placeholder="Enter procedure YAML..."
                spellCheck={false}
              />
            </div>

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

          {/* Right panel - Tabbed: AI Generator / Function Catalog */}
          <div className="sticky top-6">
            {/* Tab bar */}
            <div className="flex border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 rounded-t-lg overflow-hidden">
              <button
                onClick={() => setActiveTab('generator')}
                className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
                  activeTab === 'generator'
                    ? 'text-indigo-600 dark:text-indigo-400 border-b-2 border-indigo-600 dark:border-indigo-400 bg-indigo-50/50 dark:bg-indigo-950/20'
                    : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50'
                }`}
              >
                <span className="inline-flex items-center gap-1.5">
                  <Sparkles className="w-4 h-4" />
                  AI Generator
                </span>
              </button>
              <button
                onClick={() => setActiveTab('catalog')}
                className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
                  activeTab === 'catalog'
                    ? 'text-indigo-600 dark:text-indigo-400 border-b-2 border-indigo-600 dark:border-indigo-400 bg-indigo-50/50 dark:bg-indigo-950/20'
                    : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50'
                }`}
              >
                <span className="inline-flex items-center gap-1.5">
                  <Box className="w-4 h-4" />
                  Function Catalog
                </span>
              </button>
            </div>

            {/* Tab content */}
            {activeTab === 'generator' && (
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
            )}

            {activeTab === 'catalog' && (
              <div className="bg-white dark:bg-gray-800 rounded-b-lg border border-t-0 border-gray-200 dark:border-gray-700 overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
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

                <div className="max-h-[700px] overflow-y-auto">
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
                                      {/* Governance badges */}
                                      <div className="flex flex-wrap gap-1.5">
                                        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                          func.side_effects
                                            ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400'
                                            : 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
                                        }`}>
                                          <Zap className="w-2.5 h-2.5" />
                                          {func.side_effects ? 'Side Effects' : 'No Side Effects'}
                                        </span>
                                        {func.requires_llm && (
                                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400">
                                            <Brain className="w-2.5 h-2.5" />
                                            LLM Required
                                          </span>
                                        )}
                                        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                          func.payload_profile === 'thin'
                                            ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400'
                                            : func.payload_profile === 'summary'
                                              ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400'
                                              : 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
                                        }`}>
                                          Payload: {func.payload_profile || 'full'}
                                        </span>
                                        {!func.is_primitive && (
                                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                                            Compound
                                          </span>
                                        )}
                                      </div>

                                      {/* Tags */}
                                      {func.tags && func.tags.length > 0 && (
                                        <div className="flex flex-wrap gap-1">
                                          {func.tags.map((tag) => (
                                            <span key={tag} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[10px] bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400">
                                              <Tag className="w-2 h-2" />
                                              {tag}
                                            </span>
                                          ))}
                                        </div>
                                      )}

                                      {/* Parameters */}
                                      {(() => { const params = getParametersFromSchema(func); return params.length > 0 && (
                                        <div>
                                          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                                            Parameters
                                          </p>
                                          <div className="space-y-1">
                                            {params.map((param) => (
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
                                      ); })()}

                                      {/* Output Schema */}
                                      {func.output_schema && func.output_schema.type && (
                                        <div>
                                          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                                            Output
                                          </p>
                                          <p className="text-xs font-mono text-indigo-600 dark:text-indigo-400">
                                            {func.output_schema.type}
                                          </p>
                                          {func.output_schema.description && (
                                            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                                              {func.output_schema.description}
                                            </p>
                                          )}
                                          {func.output_schema.properties && Object.keys(func.output_schema.properties).length > 0 && (
                                            <div className="mt-1 space-y-0.5">
                                              {Object.entries(func.output_schema.properties).map(([name, prop]: [string, any]) => (
                                                <div key={name} className="flex items-start gap-1.5 text-[10px]">
                                                  <span className="font-mono text-gray-600 dark:text-gray-400">.{name}</span>
                                                  <span className="text-gray-400">({prop.type})</span>
                                                  <span className="text-gray-500 truncate">{prop.description}</span>
                                                </div>
                                              ))}
                                            </div>
                                          )}
                                          {func.output_schema.items?.properties && Object.keys(func.output_schema.items.properties).length > 0 && (
                                            <div className="mt-1 space-y-0.5">
                                              {Object.entries(func.output_schema.items.properties).map(([name, prop]: [string, any]) => (
                                                <div key={name} className="flex items-start gap-1.5 text-[10px]">
                                                  <span className="font-mono text-gray-600 dark:text-gray-400">.{name}</span>
                                                  <span className="text-gray-400">({prop.type})</span>
                                                  <span className="text-gray-500 truncate">{prop.description}</span>
                                                </div>
                                              ))}
                                            </div>
                                          )}
                                          {/* Output variants */}
                                          {func.output_schema.variants && func.output_schema.variants.length > 0 && (
                                            <div className="mt-1.5">
                                              {func.output_schema.variants.map((variant: any, idx: number) => (
                                                <div key={idx} className="text-[10px] text-gray-500 dark:text-gray-400 italic">
                                                  {variant.description}
                                                </div>
                                              ))}
                                            </div>
                                          )}
                                        </div>
                                      )}

                                      {/* Examples (collapsible) */}
                                      {func.examples && func.examples.length > 0 && (
                                        <details className="group">
                                          <summary className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider cursor-pointer hover:text-indigo-600 dark:hover:text-indigo-400">
                                            Examples ({func.examples.length})
                                          </summary>
                                          <div className="mt-1 space-y-2">
                                            {func.examples.map((ex, i) => (
                                              <div key={i} className="text-[10px]">
                                                {ex.description && (
                                                  <p className="text-gray-500 dark:text-gray-400 mb-0.5">{ex.description}</p>
                                                )}
                                                <pre className="bg-gray-900 text-gray-200 p-2 rounded text-[10px] overflow-x-auto leading-relaxed">
{`function: ${func.name}
params:
${Object.entries(ex.params || {}).map(([k, v]) =>
  `  ${k}: ${typeof v === 'string' ? `"${v}"` : JSON.stringify(v)}`
).join('\n')}`}
                                                </pre>
                                              </div>
                                            ))}
                                          </div>
                                        </details>
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
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

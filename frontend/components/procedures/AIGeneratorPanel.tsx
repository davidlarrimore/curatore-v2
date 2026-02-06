'use client'

import { useState, useRef, useEffect, forwardRef, useImperativeHandle } from 'react'
import { useAuth } from '@/lib/auth-context'
import { proceduresApi, type ValidationError } from '@/lib/api'
import { Sparkles, Loader2, Send, Wand2, ArrowLeftRight } from 'lucide-react'

interface AIGeneratorPanelProps {
  currentYaml: string
  onYamlGenerated: (yaml: string) => void
  onSuccess?: (message: string) => void
  onError?: (message: string) => void
}

export interface AIGeneratorPanelHandle {
  /** Trigger AI to fix validation errors */
  fixValidationErrors: (errors: ValidationError[], warnings?: ValidationError[]) => Promise<void>
  /** Set prompt and optionally trigger generation */
  setPromptAndGenerate: (prompt: string, autoGenerate?: boolean) => Promise<void>
  /** Check if currently generating */
  isGenerating: boolean
}

/**
 * AI Generator Panel for creating or refining procedure definitions.
 *
 * - If currentYaml is empty/default, generates a new procedure from scratch
 * - If currentYaml has content, refines the existing procedure based on the prompt
 * - Users can click on the mode badge to manually toggle between modes
 * - Exposes imperative handle for programmatic control (e.g., Fix with AI)
 */
export const AIGeneratorPanel = forwardRef<AIGeneratorPanelHandle, AIGeneratorPanelProps>(function AIGeneratorPanel({
  currentYaml,
  onYamlGenerated,
  onSuccess,
  onError,
}, ref) {
  const { token } = useAuth()
  const [prompt, setPrompt] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [manualModeOverride, setManualModeOverride] = useState<'generate' | 'refine' | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-resize textarea as content grows
  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      // Reset height to auto to get the correct scrollHeight
      textarea.style.height = 'auto'
      // Set height to scrollHeight (with a minimum)
      const minHeight = 80 // minimum height in pixels
      textarea.style.height = `${Math.max(minHeight, textarea.scrollHeight)}px`
    }
  }, [prompt])

  // Check if we have meaningful content (not just the default template)
  const hasExistingContent = currentYaml.trim().length > 0 &&
    !currentYaml.includes('name: My Procedure') &&
    currentYaml.includes('steps:')

  // Determine mode: use manual override if set, otherwise auto-detect
  const isRefineMode = manualModeOverride !== null
    ? manualModeOverride === 'refine'
    : hasExistingContent

  // Toggle between modes when user clicks the badge
  const handleModeToggle = () => {
    if (manualModeOverride === null) {
      // First click: switch to opposite of auto-detected mode
      setManualModeOverride(hasExistingContent ? 'generate' : 'refine')
    } else {
      // Subsequent clicks: toggle between modes
      setManualModeOverride(manualModeOverride === 'refine' ? 'generate' : 'refine')
    }
  }

  // Reset manual override when YAML content changes significantly
  useEffect(() => {
    setManualModeOverride(null)
  }, [hasExistingContent])

  // Build a fix prompt from validation errors
  const buildFixPrompt = (errors: ValidationError[], warnings: ValidationError[] = []): string => {
    const lines: string[] = ['Fix the following validation issues in this procedure:\n']

    if (errors.length > 0) {
      lines.push('ERRORS (must fix):')
      errors.forEach((err, i) => {
        lines.push(`${i + 1}. [${err.code}] ${err.message}`)
        if (err.path) lines.push(`   Location: ${err.path}`)
        if (err.details?.suggestion) lines.push(`   Suggestion: ${err.details.suggestion}`)
      })
    }

    if (warnings.length > 0) {
      if (errors.length > 0) lines.push('')
      lines.push('WARNINGS (should fix):')
      warnings.forEach((warn, i) => {
        lines.push(`${i + 1}. [${warn.code}] ${warn.message}`)
        if (warn.path) lines.push(`   Location: ${warn.path}`)
        if (warn.details?.suggestion) lines.push(`   Suggestion: ${warn.details.suggestion}`)
      })
    }

    return lines.join('\n')
  }

  // Core generation logic (can be called internally or via ref)
  const doGenerate = async (promptText: string, forceRefine: boolean = false) => {
    if (!token || !promptText.trim()) return

    setIsGenerating(true)
    // Force refine mode when fixing errors
    if (forceRefine) {
      setManualModeOverride('refine')
    }

    try {
      const useRefineMode = forceRefine || isRefineMode
      const result = await proceduresApi.generateProcedure(
        token,
        promptText.trim(),
        useRefineMode ? currentYaml : undefined
      )

      if (result.success && result.yaml) {
        onYamlGenerated(result.yaml)
        setPrompt('')
        onSuccess?.(
          useRefineMode
            ? `Procedure updated successfully (${result.attempts} attempt${result.attempts > 1 ? 's' : ''})`
            : `Procedure generated successfully (${result.attempts} attempt${result.attempts > 1 ? 's' : ''})`
        )
      } else {
        const errorMsg = result.error || 'Failed to generate procedure'
        const validationInfo = result.validation_errors?.length
          ? ` - ${result.validation_errors.map(e => e.message).join(', ')}`
          : ''
        onError?.(errorMsg + validationInfo)
      }
    } catch (err: any) {
      onError?.(err.message || 'Failed to generate procedure')
    } finally {
      setIsGenerating(false)
    }
  }

  // Expose imperative handle for external control
  useImperativeHandle(ref, () => ({
    fixValidationErrors: async (errors: ValidationError[], warnings: ValidationError[] = []) => {
      const fixPrompt = buildFixPrompt(errors, warnings)
      setPrompt(fixPrompt)
      // Small delay to let UI update before starting generation
      await new Promise(resolve => setTimeout(resolve, 50))
      await doGenerate(fixPrompt, true)
    },
    setPromptAndGenerate: async (promptText: string, autoGenerate: boolean = true) => {
      setPrompt(promptText)
      if (autoGenerate) {
        await new Promise(resolve => setTimeout(resolve, 50))
        await doGenerate(promptText)
      }
    },
    isGenerating,
  }), [token, currentYaml, isRefineMode, isGenerating, onYamlGenerated, onSuccess, onError])

  const handleGenerate = async () => {
    await doGenerate(prompt)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      handleGenerate()
    }
  }

  return (
    <div className="bg-gradient-to-br from-indigo-50 via-purple-50 to-pink-50 dark:from-indigo-950/30 dark:via-purple-950/30 dark:to-pink-950/30 rounded-xl border border-indigo-200 dark:border-indigo-800 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-indigo-200 dark:border-indigo-800 bg-white/50 dark:bg-gray-900/50">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">
              AI Procedure Generator
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {isRefineMode
                ? 'Describe changes to make to the current procedure'
                : 'Describe the procedure you want to create'}
            </p>
          </div>
        </div>
      </div>

      {/* Input area */}
      <div className="p-4">
        <div className="relative">
          <textarea
            ref={textareaRef}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isRefineMode
                ? "e.g., Add a logging step before sending the email..."
                : "e.g., Create a procedure that searches for SAM.gov notices from the last 24 hours and emails a summary to reports@company.com..."
            }
            className="w-full min-h-[80px] px-4 py-3 pb-7 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none overflow-hidden"
            disabled={isGenerating}
          />

          {/* Character count */}
          <div className="absolute bottom-2 left-3 text-xs text-gray-400">
            {prompt.length > 0 && `${prompt.length} characters`}
          </div>
        </div>

        {/* Actions */}
        <div className="mt-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleModeToggle}
              disabled={isGenerating}
              className="group inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium transition-all duration-200 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
              title="Click to switch mode"
            >
              {isRefineMode ? (
                <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 group-hover:bg-purple-200 dark:group-hover:bg-purple-900/50 group-hover:ring-2 group-hover:ring-purple-300 dark:group-hover:ring-purple-700">
                  <Wand2 className="w-3 h-3" />
                  Refine Mode
                  <ArrowLeftRight className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 group-hover:bg-indigo-200 dark:group-hover:bg-indigo-900/50 group-hover:ring-2 group-hover:ring-indigo-300 dark:group-hover:ring-indigo-700">
                  <Sparkles className="w-3 h-3" />
                  Generate Mode
                  <ArrowLeftRight className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                </span>
              )}
            </button>
            <span className="text-xs text-gray-400 dark:text-gray-500">
              {isRefineMode ? 'Current procedure will be modified' : 'A new procedure will be created'}
              {manualModeOverride !== null && (
                <span className="ml-1 text-amber-500 dark:text-amber-400">(manual)</span>
              )}
            </span>
          </div>

          <button
            onClick={handleGenerate}
            disabled={isGenerating || !prompt.trim()}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200"
          >
            {isGenerating ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Generating...</span>
              </>
            ) : (
              <>
                <Send className="w-4 h-4" />
                <span>{isRefineMode ? 'Refine' : 'Generate'}</span>
              </>
            )}
          </button>
        </div>

        {/* Keyboard shortcut hint */}
        <p className="mt-2 text-xs text-gray-400 dark:text-gray-500 text-right">
          Press <kbd className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 font-mono text-[10px]">⌘</kbd> + <kbd className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 font-mono text-[10px]">Enter</kbd> to submit
        </p>
      </div>

      {/* Loading overlay */}
      {isGenerating && (
        <div className="px-4 pb-4">
          <div className="rounded-lg bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-100 dark:border-indigo-800 p-4">
            <div className="flex items-center gap-3">
              <div className="relative">
                <div className="w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
                  <Sparkles className="w-5 h-5 text-white animate-pulse" />
                </div>
                <div className="absolute inset-0 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 animate-ping opacity-20" />
              </div>
              <div>
                <p className="text-sm font-medium text-indigo-900 dark:text-indigo-100">
                  {isRefineMode ? 'Refining procedure...' : 'Generating procedure...'}
                </p>
                <p className="text-xs text-indigo-600 dark:text-indigo-400">
                  AI is analyzing your request and {isRefineMode ? 'updating' : 'creating'} the YAML definition
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
})

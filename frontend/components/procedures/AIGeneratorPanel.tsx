'use client'

import { useState, useRef, useEffect, forwardRef, useImperativeHandle } from 'react'
import { useAuth } from '@/lib/auth-context'
import { proceduresApi, type ValidationError, type PlanDiagnostics, type GenerateStreamEvent } from '@/lib/api'
import { Sparkles, Loader2, Send, ChevronDown, ChevronRight, Clock, Code2, Search, CheckCircle2, XCircle, HelpCircle, User, Bot } from 'lucide-react'

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

interface ProgressEntry {
  type: 'phase' | 'tool_call' | 'tool_result' | 'error' | 'clarification'
  message: string
  detail?: string
  timestamp: number
}

interface ConversationEntry {
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  progressLog?: ProgressEntry[]
  diagnostics?: PlanDiagnostics | null
  planJson?: Record<string, unknown> | null
  isGenerating?: boolean
}

/**
 * AI Generator Panel for creating or refining procedure definitions.
 *
 * Features:
 * - SSE streaming with real-time progress display
 * - Conversation history with user prompts and AI responses
 * - Planning phase shows tool calls and results
 * - Clarification support — AI can ask questions before generating
 * - Auto-detects refine mode when existing procedure content exists
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
  const [conversation, setConversation] = useState<ConversationEntry[]>([])
  const [currentProgressLog, setCurrentProgressLog] = useState<ProgressEntry[]>([])
  const [currentPhase, setCurrentPhase] = useState<string>('')
  const [showDiagnostics, setShowDiagnostics] = useState<number | null>(null)
  const [showPlanJson, setShowPlanJson] = useState<number | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const conversationEndRef = useRef<HTMLDivElement>(null)

  // Auto-resize textarea as content grows
  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      const minHeight = 60
      const maxHeight = 200
      textarea.style.height = `${Math.min(maxHeight, Math.max(minHeight, textarea.scrollHeight))}px`
    }
  }, [prompt])

  // Auto-scroll conversation
  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [conversation, currentProgressLog])

  // Check if we have meaningful content (not just the default template)
  const hasExistingContent = currentYaml.trim().length > 0 &&
    !currentYaml.includes('name: My Procedure') &&
    currentYaml.includes('steps:')

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

  // Handle SSE events
  const handleStreamEvent = (event: GenerateStreamEvent) => {
    const now = Date.now()

    switch (event.event) {
      case 'phase':
        setCurrentPhase(event.phase || '')
        setCurrentProgressLog(prev => [...prev, {
          type: 'phase',
          message: event.message || `Phase: ${event.phase}`,
          timestamp: now,
        }])
        break

      case 'tool_call':
        setCurrentProgressLog(prev => [...prev, {
          type: 'tool_call',
          message: `Calling ${event.tool}...`,
          detail: event.args ? JSON.stringify(event.args, null, 2) : undefined,
          timestamp: now,
        }])
        break

      case 'tool_result':
        setCurrentProgressLog(prev => [...prev, {
          type: 'tool_result',
          message: event.summary || `${event.tool} completed`,
          timestamp: now,
        }])
        break

      case 'clarification':
        setCurrentProgressLog(prev => [...prev, {
          type: 'clarification' as const,
          message: event.message || 'The AI needs more information.',
          timestamp: now,
        }])
        break
    }
  }

  // Core generation logic with streaming
  const doGenerate = async (promptText: string) => {
    if (!token || !promptText.trim()) return

    // Add user message to conversation
    const userEntry: ConversationEntry = {
      role: 'user',
      content: promptText.trim(),
      timestamp: Date.now(),
    }
    setConversation(prev => [...prev, userEntry])

    setIsGenerating(true)
    setCurrentProgressLog([])
    setCurrentPhase('')

    try {
      // Auto-pass currentPlan when procedure exists (replaces manual refine mode)
      let currentPlan: Record<string, unknown> | undefined
      if (hasExistingContent) {
        // Pass the current YAML as context for refinement
        currentPlan = { _yaml: currentYaml }
      }

      const result = await proceduresApi.generateProcedureStream(
        token,
        promptText.trim(),
        'workflow_standard',
        currentPlan,
        handleStreamEvent,
      )

      // Build assistant response
      const assistantEntry: ConversationEntry = {
        role: 'assistant',
        content: '',
        timestamp: Date.now(),
        progressLog: [...currentProgressLog],
        diagnostics: result.diagnostics || null,
        planJson: result.plan_json || null,
      }

      // Check for clarification
      const resultWithClarification = result as unknown as { needs_clarification?: boolean; clarification_message?: string }
      if (resultWithClarification.needs_clarification && resultWithClarification.clarification_message) {
        assistantEntry.content = resultWithClarification.clarification_message
        setConversation(prev => [...prev, assistantEntry])
      } else if (result.success && result.yaml) {
        assistantEntry.content = 'Procedure generated successfully.'
        setConversation(prev => [...prev, assistantEntry])
        onYamlGenerated(result.yaml)
        onSuccess?.(
          `Procedure generated successfully (${result.attempts} attempt${result.attempts !== 1 ? 's' : ''})`
        )
      } else {
        const errorMsg = result.error || 'Failed to generate procedure'
        const validationInfo = result.validation_errors?.length
          ? ` - ${result.validation_errors.map(e => e.message).join(', ')}`
          : ''
        assistantEntry.content = errorMsg + validationInfo
        setConversation(prev => [...prev, assistantEntry])
        onError?.(errorMsg + validationInfo)
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : 'Failed to generate procedure'
      const errorEntry: ConversationEntry = {
        role: 'assistant',
        content: errMsg,
        timestamp: Date.now(),
        progressLog: [...currentProgressLog],
      }
      setConversation(prev => [...prev, errorEntry])
      onError?.(errMsg)
    } finally {
      setIsGenerating(false)
      setCurrentPhase('')
      setCurrentProgressLog([])
      setPrompt('')
    }
  }

  // Expose imperative handle for external control
  useImperativeHandle(ref, () => ({
    fixValidationErrors: async (errors: ValidationError[], warnings: ValidationError[] = []) => {
      const fixPrompt = buildFixPrompt(errors, warnings)
      setPrompt(fixPrompt)
      await new Promise(resolve => setTimeout(resolve, 50))
      await doGenerate(fixPrompt)
    },
    setPromptAndGenerate: async (promptText: string, autoGenerate: boolean = true) => {
      setPrompt(promptText)
      if (autoGenerate) {
        await new Promise(resolve => setTimeout(resolve, 50))
        await doGenerate(promptText)
      }
    },
    isGenerating,
  }), [token, currentYaml, hasExistingContent, isGenerating, onYamlGenerated, onSuccess, onError])

  const handleGenerate = async () => {
    await doGenerate(prompt)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      handleGenerate()
    }
  }

  const renderProgressLog = (log: ProgressEntry[]) => (
    <div className="mt-2 rounded-lg bg-gray-900 border border-gray-700 overflow-hidden">
      <div className="px-3 py-2 max-h-[180px] overflow-y-auto text-xs font-mono space-y-1">
        {log.map((entry, i) => (
          <div key={i} className="flex items-start gap-2">
            {entry.type === 'phase' && (
              <>
                <Sparkles className="w-3 h-3 text-indigo-400 mt-0.5 shrink-0" />
                <span className="text-indigo-300">{entry.message}</span>
              </>
            )}
            {entry.type === 'tool_call' && (
              <>
                <Search className="w-3 h-3 text-amber-400 mt-0.5 shrink-0" />
                <span className="text-amber-300">{entry.message}</span>
              </>
            )}
            {entry.type === 'tool_result' && (
              <>
                <CheckCircle2 className="w-3 h-3 text-emerald-400 mt-0.5 shrink-0" />
                <span className="text-gray-300">{entry.message}</span>
              </>
            )}
            {entry.type === 'error' && (
              <>
                <XCircle className="w-3 h-3 text-red-400 mt-0.5 shrink-0" />
                <span className="text-red-300">{entry.message}</span>
              </>
            )}
            {entry.type === 'clarification' && (
              <>
                <HelpCircle className="w-3 h-3 text-amber-400 mt-0.5 shrink-0" />
                <span className="text-amber-300">{entry.message}</span>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  )

  return (
    <div className="bg-gradient-to-br from-indigo-50 via-purple-50 to-pink-50 dark:from-indigo-950/30 dark:via-purple-950/30 dark:to-pink-950/30 border border-t-0 border-gray-200 dark:border-gray-700 rounded-b-lg overflow-hidden flex flex-col h-[500px]">
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
              Describe what you want to create or change
            </p>
          </div>
        </div>
      </div>

      {/* Conversation history */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4 min-h-0">
        {conversation.length === 0 && !isGenerating && (
          <div className="flex flex-col items-center justify-center h-full text-center py-12">
            <Sparkles className="w-8 h-8 text-indigo-300 dark:text-indigo-600 mb-3" />
            <p className="text-sm text-gray-500 dark:text-gray-400 max-w-xs">
              Describe the procedure you want to create, or ask the AI to modify the current one.
            </p>
          </div>
        )}

        {conversation.map((entry, i) => (
          <div key={i} className={`flex gap-2 ${entry.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {entry.role === 'assistant' && (
              <div className="shrink-0 mt-1">
                <div className="w-6 h-6 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
                  <Bot className="w-3.5 h-3.5 text-white" />
                </div>
              </div>
            )}
            <div className={`max-w-[85%] ${entry.role === 'user' ? 'order-first' : ''}`}>
              <div className={`rounded-lg px-3 py-2 text-sm ${
                entry.role === 'user'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-gray-100'
              }`}>
                <div className="whitespace-pre-wrap">{entry.content}</div>
              </div>

              {/* Progress log for assistant messages */}
              {entry.role === 'assistant' && entry.progressLog && entry.progressLog.length > 0 && (
                renderProgressLog(entry.progressLog)
              )}

              {/* Diagnostics toggle */}
              {entry.role === 'assistant' && entry.diagnostics && (
                <div className="mt-1">
                  <button
                    onClick={() => setShowDiagnostics(showDiagnostics === i ? null : i)}
                    className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
                  >
                    {showDiagnostics === i ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                    <Clock className="w-3 h-3" />
                    {entry.diagnostics.timing_ms.toFixed(0)}ms, {entry.diagnostics.total_attempts} attempts{entry.diagnostics.planning_tool_calls > 0 ? `, ${entry.diagnostics.planning_tool_calls} tools` : ''}
                  </button>
                  {showDiagnostics === i && (
                    <div className="mt-1 rounded-lg bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 p-2 text-xs">
                      <div className="grid grid-cols-2 gap-1">
                        <div><span className="text-gray-500">Profile:</span> <span className="font-medium">{entry.diagnostics.profile_used}</span></div>
                        <div><span className="text-gray-500">Tools:</span> <span className="font-medium">{entry.diagnostics.tools_available}</span></div>
                      </div>
                      {entry.diagnostics.tools_referenced.length > 0 && (
                        <div className="mt-1"><span className="text-gray-500">In plan:</span> <span className="font-mono text-xs">{entry.diagnostics.tools_referenced.join(', ')}</span></div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Plan JSON toggle */}
              {entry.role === 'assistant' && entry.planJson && (
                <div className="mt-1">
                  <button
                    onClick={() => setShowPlanJson(showPlanJson === i ? null : i)}
                    className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
                  >
                    {showPlanJson === i ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                    <Code2 className="w-3 h-3" />
                    Plan JSON
                  </button>
                  {showPlanJson === i && (
                    <pre className="mt-1 rounded-lg bg-gray-900 text-gray-100 p-2 text-xs overflow-auto max-h-[200px] font-mono">
                      {JSON.stringify(entry.planJson, null, 2)}
                    </pre>
                  )}
                </div>
              )}
            </div>
            {entry.role === 'user' && (
              <div className="shrink-0 mt-1">
                <div className="w-6 h-6 rounded-full bg-gray-200 dark:bg-gray-600 flex items-center justify-center">
                  <User className="w-3.5 h-3.5 text-gray-600 dark:text-gray-300" />
                </div>
              </div>
            )}
          </div>
        ))}

        {/* Active generation progress */}
        {isGenerating && currentProgressLog.length > 0 && (
          <div className="flex gap-2 justify-start">
            <div className="shrink-0 mt-1">
              <div className="w-6 h-6 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
                <Bot className="w-3.5 h-3.5 text-white" />
              </div>
            </div>
            <div className="max-w-[85%]">
              <div className="rounded-lg bg-gray-900 border border-gray-700 overflow-hidden">
                <div className="px-3 py-2 border-b border-gray-700 flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-indigo-400 animate-pulse" />
                  <span className="text-xs font-medium text-indigo-300">
                    {currentPhase === 'researching' ? 'Researching...' :
                     currentPhase === 'validating' ? 'Validating plan...' :
                     currentPhase === 'compiling' ? 'Compiling procedure...' :
                     'Working...'}
                  </span>
                </div>
                <div className="px-3 py-2 max-h-[180px] overflow-y-auto text-xs font-mono space-y-1">
                  {currentProgressLog.map((entry, i) => (
                    <div key={i} className="flex items-start gap-2">
                      {entry.type === 'phase' && (
                        <>
                          <Sparkles className="w-3 h-3 text-indigo-400 mt-0.5 shrink-0" />
                          <span className="text-indigo-300">{entry.message}</span>
                        </>
                      )}
                      {entry.type === 'tool_call' && (
                        <>
                          <Search className="w-3 h-3 text-amber-400 mt-0.5 shrink-0" />
                          <span className="text-amber-300">{entry.message}</span>
                        </>
                      )}
                      {entry.type === 'tool_result' && (
                        <>
                          <CheckCircle2 className="w-3 h-3 text-emerald-400 mt-0.5 shrink-0" />
                          <span className="text-gray-300">{entry.message}</span>
                        </>
                      )}
                      {entry.type === 'clarification' && (
                        <>
                          <HelpCircle className="w-3 h-3 text-amber-400 mt-0.5 shrink-0" />
                          <span className="text-amber-300">{entry.message}</span>
                        </>
                      )}
                    </div>
                  ))}
                  <div className="flex items-center gap-2">
                    <Loader2 className="w-3 h-3 text-gray-500 animate-spin" />
                    <span className="text-gray-500">...</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        <div ref={conversationEndRef} />
      </div>

      {/* Input area — pinned to bottom */}
      <div className="border-t border-indigo-200 dark:border-indigo-800 bg-white/50 dark:bg-gray-900/50 px-4 py-3">
        <div className="flex items-end gap-2">
          <div className="relative flex-1">
            <textarea
              ref={textareaRef}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="e.g., Create a procedure that searches for SAM.gov notices and emails a summary, or describe changes to the current procedure..."
              className="w-full min-h-[60px] max-h-[200px] px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none overflow-y-auto"
              disabled={isGenerating}
            />
          </div>
          <button
            onClick={handleGenerate}
            disabled={isGenerating || !prompt.trim()}
            className="shrink-0 self-end inline-flex items-center justify-center w-10 h-10 rounded-lg bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200"
            title="Generate (Cmd+Enter)"
          >
            {isGenerating ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>
        </div>
        <p className="mt-1 text-xs text-gray-400 dark:text-gray-500 text-right">
          <kbd className="px-1 py-0.5 rounded bg-gray-100 dark:bg-gray-700 font-mono text-[10px]">⌘</kbd>+<kbd className="px-1 py-0.5 rounded bg-gray-100 dark:bg-gray-700 font-mono text-[10px]">Enter</kbd> to send
        </p>
      </div>
    </div>
  )
})

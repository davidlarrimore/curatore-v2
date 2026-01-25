'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import toast from 'react-hot-toast'
import {
  FileInfo,
  ProcessingResult,
  ProcessingOptions,
  OCRSettings
} from '@/types'
import { systemApi, fileApi, processingApi, jobsApi, utils } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import { getDefaultJobName } from '@/lib/job-naming'
import { UploadSelectStage } from '@/components/stages/UploadSelectStage'
import { ProcessingPanel } from '@/components/ProcessingPanel'
import { ReviewStage } from '@/components/stages/ReviewStage'
import { DownloadStage } from '@/components/stages/DownloadStage'
import { ProgressBar, ProgressStep, StepStatus } from '@/components/ui/ProgressBar'
import {
  Upload,
  Eye,
  Download,
  CheckCircle2,
  Zap,
  FileText,
  BarChart3,
  AlertTriangle,
  ArrowRight
} from 'lucide-react'

type AppStage = 'upload' | 'review' | 'download'
type ProcessingPanelState = 'hidden' | 'minimized' | 'normal' | 'fullscreen'

interface ProcessingState {
  currentStage: AppStage
  sourceType: 'local' | 'upload'
  selectedFiles: FileInfo[]
  processingResults: ProcessingResult[]
  processingComplete: boolean
  isProcessing: boolean
  processingOptions: ProcessingOptions
  resetCounter: number
}

interface SystemConfig {
  supportedFormats: string[]
  maxFileSize: number
}

export default function ProcessingPage() {
  const router = useRouter()
  const { accessToken, isAuthenticated } = useAuth()

  // State management
  const [state, setState] = useState<ProcessingState>({
    currentStage: 'upload',
    sourceType: 'local',
    selectedFiles: [],
    processingResults: [],
    processingComplete: false,
    isProcessing: false,
    processingOptions: {
      ocr_settings: {
        language: 'eng',
        psm: 3
      },
      extraction_engine: 'extraction-service'
    },
    resetCounter: 0
  })

  // System config state
  const [config, setConfig] = useState<SystemConfig>({
    supportedFormats: [],
    maxFileSize: 0
  })
  const [isLoadingConfig, setIsLoadingConfig] = useState(true)

  // Processing panel state - NEW
  const [panelVisible, setPanelVisible] = useState(false)
  const [processingPanelState, setProcessingPanelState] = useState<ProcessingPanelState>('hidden')

  // Progress bar configuration
  const progressSteps: ProgressStep[] = [
    { 
      id: 'upload', 
      name: 'Upload & Select', 
      subtitle: 'Choose source documents', 
      icon: Upload 
    },
    { 
      id: 'review', 
      name: 'Review & Edit', 
      subtitle: 'Quality assessment & optimization', 
      icon: Eye 
    },
    { 
      id: 'download', 
      name: 'Export Results', 
      subtitle: 'Download processed documents', 
      icon: Download 
    }
  ]

  // Load saved options on component mount
  useEffect(() => {
    const savedOptions = localStorage.getItem('processingOptions')
    if (savedOptions) {
      try {
        const parsed = JSON.parse(savedOptions)
        setState(prev => ({ ...prev, processingOptions: parsed }))
      } catch (error) {
        console.warn('Failed to load saved processing options:', error)
      }
    }
  }, [])

  // Load system config on mount
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const response = await systemApi.getSupportedFormats()
        setConfig({
          supportedFormats: response.supported_extensions,
          maxFileSize: response.max_file_size
        })
      } catch (error) {
        console.error('Failed to load system config:', error)
        toast.error('Could not load system configuration.')
      } finally {
        setIsLoadingConfig(false)
      }
    }
    fetchConfig()
  }, [])

  // Save options to localStorage when they change
  useEffect(() => {
    localStorage.setItem('processingOptions', JSON.stringify(state.processingOptions))
  }, [state.processingOptions])

  // Progress bar logic
  const getStepStatus = (stepId: string): StepStatus => {
    switch (stepId) {
      case 'upload':
        return state.currentStage === 'upload' ? 'current' : 
               state.selectedFiles.length > 0 ? 'completed' : 'pending'
      case 'review':
        return state.processingComplete ? 'completed' : 
               state.isProcessing || state.currentStage === 'review' ? 'current' : 'pending'
      case 'download':
        // Keep Export Results pending until user clicks Finish Review
        return state.currentStage === 'download' ? 'current' : 'pending'
      default:
        return 'pending'
    }
  }

  const getStepClickable = (stepId: string): boolean => {
    switch (stepId) {
      case 'upload':
        return true // Always can go back to upload
      case 'review':
        return state.processingResults.length > 0 || state.isProcessing
      case 'download':
        return state.processingComplete
      default:
        return false
    }
  }

  // Stage management
  const handleStageChange = (newStage: string) => {
    const stage = newStage as AppStage
    if (getStepClickable(stage)) {
      setState(prev => ({ ...prev, currentStage: stage }))
    }
  }

  // File management
  const handleSelectedFilesChange = (files: FileInfo[]) => {
    setState(prev => ({
      ...prev,
      selectedFiles: files,
      processingResults: [],
      processingComplete: false
    }))
  }

  const handleSourceTypeChange = (sourceType: 'local' | 'upload') => {
    setState(prev => ({
      ...prev,
      sourceType,
      selectedFiles: [],
      processingResults: [],
      processingComplete: false
    }))
  }

  // Processing management
  const handleStartProcessing = async () => {
    if (state.selectedFiles.length === 0) {
      toast.error('Please select files to process')
      return
    }

    // If authenticated, offer to create a job
    if (isAuthenticated && accessToken) {
      const createJob = window.confirm(
        `Create a batch job for ${state.selectedFiles.length} documents?\n\n` +
        `This will track processing in the Jobs page with real-time updates.\n\n` +
        `Click OK to create a job, or Cancel to process immediately.`
      )

      if (createJob) {
        const defaultJobName = getDefaultJobName(state.selectedFiles)
        const jobName = window.prompt(
          'Enter a name for this job:',
          defaultJobName
        )

        if (jobName === null) {
          // User cancelled
          return
        }

        try {
          toast.loading('Creating job...')

          // Extract document IDs from selected files
          const documentIds = state.selectedFiles.map(f => f.document_id)

          // Create job via API
          const job = await jobsApi.createJob(accessToken, {
            document_ids: documentIds,
            options: state.processingOptions,
            name: jobName || defaultJobName,
            description: `Processing ${state.selectedFiles.length} documents from ${state.sourceType}`,
            start_immediately: true
          })

          toast.dismiss()
          toast.success(`Job created: ${job.name}`)

          // Redirect to job detail page
          router.push(`/jobs/${job.id}`)
          return
        } catch (error: any) {
          toast.dismiss()
          toast.error(`Failed to create job: ${error.message || 'Unknown error'}`)
          console.error('Job creation failed:', error)
          return
        }
      }
    }

    // Fall back to immediate processing with ProcessingPanel
    setState(prev => ({
      ...prev,
      isProcessing: true,
      processingComplete: false,
      processingResults: [],
      currentStage: 'review'
    }))
    setPanelVisible(true)
  }

  const handleProcessingComplete = (results: ProcessingResult[]) => {
    setState(prev => ({ ...prev, processingResults: results, processingComplete: true, isProcessing: false }))
    toast.success('Processing complete!')
  }

  const handleProcessingOptionsChange = (options: ProcessingOptions) => {
    setState(prev => ({ ...prev, processingOptions: options }))
  }

  // NEW: Handle processing panel state changes
  const handleProcessingPanelStateChange = (newState: ProcessingPanelState) => {
    setProcessingPanelState(newState)
  }

  // Results management
  const handleResultsUpdate = (updatedResults: ProcessingResult[]) => {
    setState(prev => ({
      ...prev,
      processingResults: updatedResults
    }))
  }

  const handleResultsDownload = async (format: string) => { // This seems unused by DownloadStage
    try {
      const blob = await processingApi.downloadResults(state.processingResults, format)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `processed_documents.${format}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      toast.success(`Downloaded results as ${format.toUpperCase()}`)
    } catch (error) {
      console.error('Download failed:', error)
      toast.error('Failed to download results')
    }
  }

  // System reset: clear server-side runtime files and reset UI state
  const handleReset = async () => {
    try {
      await systemApi.resetSystem()
      setState(prev => ({
        ...prev,
        selectedFiles: [],
        processingResults: [],
        processingComplete: false,
        isProcessing: false,
        currentStage: 'upload',
        resetCounter: prev.resetCounter + 1
      }))
      setPanelVisible(false)
      setProcessingPanelState('hidden')
      toast.success('System reset successfully')
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Reset failed'
      toast.error(`Failed to reset system: ${message}`)
    }
  }

  const stats = utils.calculateStats(state.processingResults)

  return (
    <div className="h-full flex flex-col bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      {/* Deprecation Notice - Enterprise Style */}
      {isAuthenticated && (
        <div className="bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/20 border-b border-amber-200 dark:border-amber-800/50">
          <div className="max-w-7xl mx-auto px-4 py-3">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3 min-w-0">
                <div className="flex-shrink-0 p-2 bg-amber-100 dark:bg-amber-900/30 rounded-lg">
                  <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm text-amber-800 dark:text-amber-200">
                    <span className="font-semibold">Migration Notice:</span>{' '}
                    <span className="text-amber-700 dark:text-amber-300">
                      This page will be deprecated. Use the new Jobs page for improved batch processing with real-time tracking.
                    </span>
                  </p>
                </div>
              </div>
              <button
                onClick={() => router.push('/jobs')}
                className="flex-shrink-0 inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white text-sm font-medium rounded-lg shadow-lg shadow-amber-500/25 transition-all hover:shadow-xl hover:shadow-amber-500/30"
              >
                Try Jobs Page
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Progress Bar Component */}
      <ProgressBar
        steps={progressSteps}
        currentStep={state.currentStage}
        onStepChange={handleStageChange}
        getStepStatus={getStepStatus}
        getStepClickable={getStepClickable}
        variant="slim"
      />

      {/* Main Content Area */}
      <div className="flex-1 overflow-auto">
        <div className="max-w-8xl mx-auto p-4 lg:p-6">
          {/* Stage Content */}
          {state.currentStage === 'upload' && !isLoadingConfig && (
            <UploadSelectStage
              key={state.resetCounter}
              selectedFiles={state.selectedFiles}
              onSelectedFilesChange={handleSelectedFilesChange}
              sourceType={state.sourceType}
              onSourceTypeChange={handleSourceTypeChange}
              onProcess={handleStartProcessing}
              isProcessing={state.isProcessing}
              processingOptions={state.processingOptions}
              onProcessingOptionsChange={handleProcessingOptionsChange}
              supportedFormats={config.supportedFormats}
              maxFileSize={config.maxFileSize}
              processingPanelState={processingPanelState}
            />
          )}

          {state.currentStage === 'review' && (
            <ReviewStage
              selectedFiles={state.selectedFiles}
              processingResults={state.processingResults}
              onResultsUpdate={handleResultsUpdate}
              onComplete={() => handleStageChange('download')}
              isProcessingComplete={state.processingComplete}
              isProcessing={state.isProcessing}
              processingPanelState={processingPanelState}
            />
          )}

          {state.currentStage === 'download' && (
            <DownloadStage
              processingResults={state.processingResults}
              onRestart={handleReset}
              processingPanelState={processingPanelState}
            />
          )}
        </div>
      </div>

      {/* Processing Panel */}
      <ProcessingPanel
        isVisible={panelVisible}
        onClose={() => setPanelVisible(false)}
        selectedFiles={state.selectedFiles}
        processingOptions={state.processingOptions}
        sourceType={state.sourceType}
        onProcessingComplete={handleProcessingComplete}
        onResultUpdate={handleResultsUpdate}
        onError={(error) => {
          toast.error(`Processing error: ${error}`)
          setState(prev => ({ ...prev, isProcessing: false }))
        }}
        resetTrigger={state.resetCounter}
        onPanelStateChange={handleProcessingPanelStateChange}
      />
    </div>
  )
}

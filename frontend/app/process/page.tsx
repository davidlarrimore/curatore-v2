'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import toast from 'react-hot-toast'
import {
  FileInfo,
  ProcessingResult,
  ProcessingOptions,
  QualityThresholds,
  OCRSettings
} from '@/types'
import { systemApi, fileApi, processingApi, jobsApi, utils } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
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
  BarChart3
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
      quality_thresholds: {
        conversion_threshold: 70.0,
        clarity_threshold: 7.0,
        completeness_threshold: 8.0,
        relevance_threshold: 6.0,
        markdown_threshold: 7.0
      },
      ocr_settings: {
        enabled: true,
        language: 'eng',
        confidence_threshold: 0.8,
        psm: 3
      },
      processing_settings: {
        chunk_size: 1000,
        chunk_overlap: 200,
        max_retries: 3
      },
      auto_optimize: true
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
        const jobName = window.prompt(
          'Enter a name for this job:',
          `Process ${state.selectedFiles.length} documents`
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
            name: jobName || `Process ${state.selectedFiles.length} documents`,
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
    <div className="h-full flex flex-col">
      {/* Deprecation Notice */}
      {isAuthenticated && (
        <div className="bg-yellow-50 border-b border-yellow-200 px-4 py-3">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex-shrink-0">
                <svg className="h-5 w-5 text-yellow-600" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="flex-1">
                <p className="text-sm text-yellow-800">
                  <strong>Notice:</strong> This page will be deprecated soon. We recommend using the new <strong>Jobs</strong> page for batch document processing with better tracking and management.
                </p>
              </div>
            </div>
            <button
              onClick={() => router.push('/jobs')}
              className="flex-shrink-0 px-4 py-2 bg-yellow-600 text-white text-sm font-medium rounded-md hover:bg-yellow-700 transition-colors"
            >
              Try Jobs Page
            </button>
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
        <div className="max-w-8xl mx-auto p-4">
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
              processingPanelState={processingPanelState} // NEW: Pass processing panel state
            />
          )}

          {state.currentStage === 'review' && (
            <ReviewStage
              selectedFiles={state.selectedFiles}
              processingResults={state.processingResults}
              onResultsUpdate={handleResultsUpdate}
              onComplete={() => handleStageChange('download')}
              qualityThresholds={{
                conversion: state.processingOptions.quality_thresholds.conversion_threshold,
                clarity: state.processingOptions.quality_thresholds.clarity_threshold,
                completeness: state.processingOptions.quality_thresholds.completeness_threshold,
                relevance: state.processingOptions.quality_thresholds.relevance_threshold,
                markdown: state.processingOptions.quality_thresholds.markdown_threshold,
              }}
              isProcessingComplete={state.processingComplete}
              isProcessing={state.isProcessing}
              processingPanelState={processingPanelState} // NEW: Pass processing panel state
            />
          )}

          {state.currentStage === 'download' && (
            <DownloadStage
              processingResults={state.processingResults}
              onRestart={handleReset}
              processingPanelState={processingPanelState} // NEW: Pass processing panel state
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
        onPanelStateChange={handleProcessingPanelStateChange} // NEW: Handle panel state changes
      />
    </div>
  )
}

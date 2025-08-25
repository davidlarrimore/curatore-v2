'use client'

import { useState, useEffect } from 'react'
import toast from 'react-hot-toast'
import { 
  FileInfo, 
  ProcessingResult, 
  ProcessingOptions,
  QualityThresholds,
  OCRSettings
} from '@/types'
import { systemApi, fileApi, processingApi, utils } from '@/lib/api'
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

export default function ProcessingPage() {
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
        clarity_threshold: 7.0,
        completeness_threshold: 8.0,
        relevance_threshold: 6.0,
        markdown_threshold: 7.0
      },
      ocr_settings: {
        enabled: true,
        language: 'en',
        confidence_threshold: 0.8
      },
      processing_settings: {
        chunk_size: 1000,
        chunk_overlap: 200,
        max_retries: 3
      }
    },
    resetCounter: 0
  })

  // Processing panel state
  const [panelVisible, setPanelVisible] = useState(false)
  const [currentFile, setCurrentFile] = useState<string | null>(null)
  const [processingLogs, setProcessingLogs] = useState<Array<{
    type: 'info' | 'success' | 'error' | 'warning'
    message: string
    timestamp: Date
  }>>([])
  const [processingProgress, setProcessingProgress] = useState(0)

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

  // Save options to localStorage when they change
  useEffect(() => {
    localStorage.setItem('processingOptions', JSON.stringify(state.processingOptions))
  }, [state.processingOptions])

  // Auto-advance to review stage when processing completes
  useEffect(() => {
    if (state.processingComplete && state.currentStage === 'upload') {
      setState(prev => ({ ...prev, currentStage: 'review' }))
    }
  }, [state.processingComplete, state.currentStage])

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
        return state.processingComplete && state.currentStage === 'download' ? 'current' : 
               state.processingComplete ? 'completed' : 'pending'
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
  const handleFilesSelected = (files: FileInfo[]) => {
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

    setState(prev => ({ ...prev, isProcessing: true }))
    setPanelVisible(true)
    setProcessingLogs([])
    setProcessingProgress(0)

    try {
      const results = await processingApi.processBatch(
        state.selectedFiles,
        state.processingOptions,
        (progress, currentFile) => {
          setProcessingProgress(progress)
          setCurrentFile(currentFile)
        }
      )

      setState(prev => ({
        ...prev,
        processingResults: results,
        processingComplete: true,
        isProcessing: false
      }))

      toast.success(`Successfully processed ${results.length} documents`)
      
    } catch (error) {
      console.error('Processing failed:', error)
      toast.error(error instanceof Error ? error.message : 'Processing failed')
      setState(prev => ({ ...prev, isProcessing: false }))
    }
  }

  const handleProcessingOptionsChange = (options: ProcessingOptions) => {
    setState(prev => ({ ...prev, processingOptions: options }))
  }

  // Results management
  const handleResultUpdate = (updatedResult: ProcessingResult) => {
    setState(prev => ({
      ...prev,
      processingResults: prev.processingResults.map(result =>
        result.file_id === updatedResult.file_id ? updatedResult : result
      )
    }))
  }

  const handleResultsDownload = async (format: string) => {
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

  // System reset
  const handleReset = () => {
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
    setProcessingLogs([])
    setProcessingProgress(0)
    setCurrentFile(null)
    toast.success('System reset successfully')
  }

  const stats = utils.calculateStats(state.processingResults)

  return (
    <div className="h-full flex flex-col">
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
        <div className="max-w-6xl mx-auto p-6">
          {/* Stage Content */}
          {state.currentStage === 'upload' && (
            <UploadSelectStage
              key={state.resetCounter}
              selectedFiles={state.selectedFiles}
              onFilesSelected={handleFilesSelected}
              sourceType={state.sourceType}
              onSourceTypeChange={handleSourceTypeChange}
              onStartProcessing={handleStartProcessing}
              isProcessing={state.isProcessing}
              processingOptions={state.processingOptions}
              onProcessingOptionsChange={handleProcessingOptionsChange}
              onReset={handleReset}
            />
          )}

          {state.currentStage === 'review' && (
            <ReviewStage
              selectedFiles={state.selectedFiles}
              processingResults={state.processingResults}
              isProcessing={state.isProcessing}
              processingComplete={state.processingComplete}
              onResultUpdate={handleResultUpdate}
              onAdvanceToDownload={() => handleStageChange('download')}
            />
          )}

          {state.currentStage === 'download' && (
            <DownloadStage
              processingResults={state.processingResults}
              onDownload={handleResultsDownload}
              onStartOver={handleReset}
              stats={stats}
            />
          )}
        </div>
      </div>

      {/* Processing Panel */}
      <ProcessingPanel
        isVisible={panelVisible}
        onClose={() => setPanelVisible(false)}
        isProcessing={state.isProcessing}
        progress={processingProgress}
        currentFile={currentFile}
        results={state.processingResults}
        processingComplete={state.processingComplete}
        onError={(error) => {
          toast.error(error)
          setState(prev => ({ ...prev, isProcessing: false }))
        }}
      />
    </div>
  )
}
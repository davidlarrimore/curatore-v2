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

export default function ProcessPage() {
  const [state, setState] = useState<ProcessingState>({
    currentStage: 'upload',
    sourceType: 'upload',
    selectedFiles: [],
    processingResults: [],
    processingComplete: false,
    isProcessing: false,
    processingOptions: {
      auto_optimize: true,
      ocr_settings: {
        language: 'eng',
        psm: 3
      },
      quality_thresholds: {
        conversion: 70,
        clarity: 7,
        completeness: 7,
        relevance: 7,
        markdown: 7
      }
    },
    resetCounter: 0
  })

  // System configuration
  const [supportedFormats, setSupportedFormats] = useState<string[]>([])
  const [maxFileSize, setMaxFileSize] = useState<number>(52428800)
  const [showProcessingPanel, setShowProcessingPanel] = useState(false)

  // Load system configuration on mount
  useEffect(() => {
    loadSystemConfig()
  }, [])

  const loadSystemConfig = async () => {
    try {
      const [formatsData, configData] = await Promise.all([
        systemApi.getSupportedFormats(),
        systemApi.getConfig()
      ])

      setSupportedFormats(formatsData.supported_extensions)
      setMaxFileSize(formatsData.max_file_size)
      
      setState(prev => ({
        ...prev,
        processingOptions: {
          auto_optimize: configData.auto_optimize,
          ocr_settings: configData.ocr_settings,
          quality_thresholds: configData.quality_thresholds
        }
      }))
    } catch (error) {
      console.error('Failed to load system configuration:', error)
      toast.error('Failed to load system configuration')
    }
  }

  // Stage management
  const handleStageChange = (stage: AppStage) => {
    setState(prev => ({ ...prev, currentStage: stage }))
  }

  const handleSourceTypeChange = (sourceType: 'local' | 'upload') => {
    setState(prev => ({ 
      ...prev, 
      sourceType,
      selectedFiles: [] // Clear selection when switching source
    }))
  }

  const handleSelectedFilesChange = (files: FileInfo[]) => {
    setState(prev => ({ ...prev, selectedFiles: files }))
  }

  const handleProcessingOptionsChange = (options: ProcessingOptions) => {
    setState(prev => ({ ...prev, processingOptions: options }))
  }

  // Processing workflow
  const handleStartProcessing = (files: FileInfo[], options: ProcessingOptions) => {
    setState(prev => ({ 
      ...prev, 
      selectedFiles: files,
      processingOptions: options,
      processingResults: [],
      processingComplete: false,
      isProcessing: true,
      currentStage: 'review'
    }))
    setShowProcessingPanel(true)
  }

  const handleProcessingComplete = (results: ProcessingResult[]) => {
    setState(prev => ({ 
      ...prev, 
      processingResults: results,
      processingComplete: true,
      isProcessing: false
    }))
    
    const stats = utils.calculateStats(results)
    toast.success(
      `Processing complete! ${stats.successful}/${stats.total} successful, ${stats.ragReady} RAG-ready`,
      { duration: 5000 }
    )
  }

  const handleResultsUpdate = (results: ProcessingResult[]) => {
    setState(prev => ({ ...prev, processingResults: results }))
  }

  const handleProcessingError = (error: string) => {
    setState(prev => ({ ...prev, isProcessing: false }))
    toast.error(`Processing failed: ${error}`)
  }

  const handleReviewComplete = () => {
    setState(prev => ({ ...prev, currentStage: 'download' }))
    toast.success('Ready to download your processed documents!')
  }

  const handleRestart = () => {
    setState(prev => ({
      ...prev,
      currentStage: 'upload',
      sourceType: 'upload',
      selectedFiles: [],
      processingResults: [],
      processingComplete: false,
      isProcessing: false,
      resetCounter: prev.resetCounter + 1
    }))
    setShowProcessingPanel(false)
    toast.success('Started new processing session')
  }

  const handleCloseProcessingPanel = () => {
    setShowProcessingPanel(false)
  }

  // Get stage status for progress indicator
  const getStageStatus = (stage: AppStage) => {
    if (stage === state.currentStage) return 'current'
    
    switch (stage) {
      case 'upload':
        return state.selectedFiles.length > 0 ? 'completed' : 'pending'
      case 'review':
        return state.processingComplete ? 'completed' : 
               state.isProcessing ? 'current' : 'pending'
      case 'download':
        return state.processingComplete && state.currentStage === 'download' ? 'current' : 'pending'
      default:
        return 'pending'
    }
  }

  const stats = utils.calculateStats(state.processingResults)

  return (
    <div className="h-full flex flex-col">
      {/* Page Header */}
      {/* Enterprise Progress Header - Full Width */}
      <div className="bg-gradient-to-r from-gray-50 to-gray-100 border-b border-gray-200">
        <div className="px-6 py-4">
          <nav aria-label="Processing Pipeline Progress">
            <div className="flex items-center justify-between">
              {[
                { id: 'upload', name: 'Upload & Select', subtitle: 'Choose source documents', icon: Upload },
                { id: 'review', name: 'Review & Edit', subtitle: 'Quality assessment & optimization', icon: Eye },
                { id: 'download', name: 'Export Results', subtitle: 'Download processed documents', icon: Download }
              ].map((step, stepIdx) => {
                const status = getStageStatus(step.id as AppStage)
                const isCompleted = status === 'completed'
                const isCurrent = status === 'current'
                const isClickable = step.id === 'upload' || 
                  (step.id === 'review' && state.processingResults.length > 0) || 
                  (step.id === 'download' && state.processingComplete)

                return (
                  <div key={step.id} className="flex items-center flex-1">
                    {/* Step Container */}
                    <div className="flex-1">
                      <button
                        onClick={() => {
                          if (isClickable) {
                            handleStageChange(step.id as AppStage)
                          }
                        }}
                        disabled={!isClickable}
                        className={`w-full flex items-center justify-start space-x-4 p-4 rounded-xl transition-all duration-200 ${
                          isCurrent
                            ? 'bg-blue-600 text-white shadow-lg transform scale-[1.02]'
                            : isCompleted
                              ? 'bg-white border-2 border-blue-200 text-gray-900 hover:border-blue-300 shadow-md'
                              : 'bg-white border-2 border-gray-200 text-gray-500 hover:border-gray-300'
                        } ${isClickable ? 'cursor-pointer' : 'cursor-default'} disabled:opacity-60`}
                      >
                        {/* Icon */}
                        <div className={`p-2 rounded-lg ${
                          isCurrent
                            ? 'bg-blue-500 text-white'
                            : isCompleted
                              ? 'bg-blue-100 text-blue-600'
                              : 'bg-gray-100 text-gray-400'
                        }`}>
                          {isCompleted && !isCurrent ? (
                            <CheckCircle2 className="w-5 h-5" />
                          ) : (
                            <step.icon className="w-5 h-5" />
                          )}
                        </div>

                        {/* Text Content */}
                        <div className="text-left flex-1">
                          <div className={`font-semibold ${
                            isCurrent ? 'text-white' : isCompleted ? 'text-gray-900' : 'text-gray-500'
                          }`}>
                            {step.name}
                          </div>
                          <div className={`text-sm ${
                            isCurrent ? 'text-blue-100' : isCompleted ? 'text-gray-600' : 'text-gray-400'
                          }`}>
                            {step.subtitle}
                          </div>
                        </div>

                        {/* Status Indicator */}
                        <div className="flex flex-col items-end">
                          {isCurrent && (
                            <div className="text-xs bg-blue-500 px-2 py-1 rounded-full text-white font-medium">
                              ACTIVE
                            </div>
                          )}
                          {isCompleted && !isCurrent && (
                            <div className="text-xs bg-green-100 text-green-700 px-2 py-1 rounded-full font-medium">
                              COMPLETE
                            </div>
                          )}
                          {state.processingResults.length > 0 && step.id === 'review' && (
                            <div className="text-xs text-gray-500 mt-1">
                              {stats.successful}/{state.processingResults.length} processed
                            </div>
                          )}
                        </div>
                      </button>
                    </div>

                    {/* Connector Line */}
                    {stepIdx !== 2 && (
                      <div className="flex items-center px-4">
                        <div className={`h-0.5 w-8 ${
                          isCompleted ? 'bg-blue-400' : 'bg-gray-300'
                        } transition-colors duration-300`} />
                        <div className={`w-3 h-3 rounded-full border-2 ${
                          isCompleted ? 'border-blue-400 bg-blue-400' : 'border-gray-300 bg-white'
                        } transition-colors duration-300`} />
                        <div className={`h-0.5 w-8 ${
                          isCompleted ? 'bg-blue-400' : 'bg-gray-300'
                        } transition-colors duration-300`} />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </nav>
        </div>
      </div>

      {/* Main Content Area - Full height with proper overflow */}
      <div className="flex-1 overflow-auto">
        <div className="max-w-7xl mx-auto px-6 py-6">
          {/* Stage Content */}
          {state.currentStage === 'upload' && (
            <UploadSelectStage
              sourceType={state.sourceType}
              onSourceTypeChange={handleSourceTypeChange}
              selectedFiles={state.selectedFiles}
              onSelectedFilesChange={handleSelectedFilesChange}
              onProcess={handleStartProcessing}
              supportedFormats={supportedFormats}
              maxFileSize={maxFileSize}
              processingOptions={state.processingOptions}
              onProcessingOptionsChange={handleProcessingOptionsChange}
              isProcessing={state.isProcessing}
            />
          )}

          {state.currentStage === 'review' && (
            <ReviewStage
              processingResults={state.processingResults}
              onResultsUpdate={handleResultsUpdate}
              onComplete={handleReviewComplete}
              qualityThresholds={state.processingOptions.quality_thresholds}
              isProcessingComplete={state.processingComplete}
              isProcessing={state.isProcessing}
              selectedFiles={state.selectedFiles}
            />
          )}

          {state.currentStage === 'download' && (
            <DownloadStage
              processingResults={state.processingResults}
              onRestart={handleRestart}
            />
          )}

          {/* Empty state for no stage selected */}
          {!state.currentStage && (
            <div className="text-center py-12">
              <FileText className="w-16 h-16 text-gray-400 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-gray-900 mb-2">Welcome to Curatore v2</h3>
              <p className="text-gray-600 mb-6">
                Transform your documents into RAG-ready, semantically optimized content
              </p>
              <button
                onClick={() => handleStageChange('upload')}
                className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
              >
                Get Started
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Processing Panel - Overlays the main content */}
      <ProcessingPanel
        selectedFiles={state.selectedFiles}
        processingOptions={state.processingOptions}
        onProcessingComplete={handleProcessingComplete}
        onResultUpdate={handleResultsUpdate}
        onError={handleProcessingError}
        isVisible={showProcessingPanel}
        onClose={handleCloseProcessingPanel}
        resetTrigger={state.resetCounter}
      />


    </div>
  )
}
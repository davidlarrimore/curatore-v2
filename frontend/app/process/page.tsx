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

interface ProgressStep {
  id: string;
  name: string;
  subtitle: string;
  icon: React.ComponentType<any>;
}

interface ChevronProgressBarProps {
  steps: ProgressStep[];
  currentStage: string;
  processingResults: any[];
  processingComplete: boolean;
  onStageChange: (stage: string) => void;
  getStageStatus: (stageId: string) => 'completed' | 'current' | 'pending';
  stats: {
    successful: number;
    failed: number;
    ragReady: number;
  };
}

const ChevronProgressBar: React.FC<ChevronProgressBarProps> = ({
  steps,
  currentStage,
  processingResults,
  processingComplete,
  onStageChange,
  getStageStatus,
  stats
}) => {
  return (
    <div className="bg-gradient-to-r from-slate-50 to-slate-100 border-b border-slate-200">
      <div className="px-6 py-6">
        <nav aria-label="Processing Pipeline Progress" className="max-w-7xl mx-auto">
          <div className="flex items-center justify-center overflow-x-auto">
            {steps.map((step, stepIdx) => {
              const status = getStageStatus(step.id);
              const isCompleted = status === 'completed';
              const isCurrent = status === 'current';
              const isClickable = step.id === 'upload' || 
                (step.id === 'review' && processingResults.length > 0) || 
                (step.id === 'download' && processingComplete);

              return (
                <div key={step.id} className="flex items-center group relative">
                  {/* Chevron Step Container */}
                  <div className="relative">
                    <button
                      onClick={() => {
                        if (isClickable) {
                          onStageChange(step.id);
                        }
                      }}
                      disabled={!isClickable}
                      className={`
                        relative flex items-center px-8 py-6 transition-all duration-300 transform
                        ${stepIdx === 0 ? 'pl-6 rounded-l-2xl' : ''}
                        ${stepIdx === steps.length - 1 ? 'pr-6 rounded-r-2xl' : 'pr-12'}
                        ${isClickable ? 'cursor-pointer hover:scale-[1.02]' : 'cursor-default'}
                        ${isCurrent 
                          ? 'bg-gradient-to-r from-blue-600 to-blue-700 text-white shadow-xl z-30 scale-[1.02]' 
                          : isCompleted
                            ? 'bg-gradient-to-r from-emerald-500 to-emerald-600 text-white shadow-lg z-20 hover:from-emerald-600 hover:to-emerald-700'
                            : 'bg-white text-slate-600 shadow-md z-10 hover:bg-slate-50 hover:shadow-lg'
                        }
                        disabled:opacity-60 min-w-[280px]
                      `}
                      style={{
                        clipPath: stepIdx === steps.length - 1 
                          ? undefined 
                          : 'polygon(0% 0%, calc(100% - 20px) 0%, 100% 50%, calc(100% - 20px) 100%, 0% 100%, 20px 50%)',
                        marginLeft: stepIdx === 0 ? '0' : '-20px'
                      }}
                    >
                      

                      {/* Text Content */}
                      <div className="ml-4 text-left flex-1 min-w-0">
                        <div className={`
                          font-bold text-lg leading-tight
                          ${isCurrent ? 'text-white' : isCompleted ? 'text-white' : 'text-slate-800'}
                        `}>
                          {step.name}
                        </div>
                        <div className={`
                          text-sm mt-1 leading-tight
                          ${isCurrent ? 'text-blue-100' : isCompleted ? 'text-emerald-100' : 'text-slate-500'}
                        `}>
                          {step.subtitle}
                        </div>
                        
                        {/* Progress indicators */}
                        {step.id === 'review' && processingResults.length > 0 && (
                          <div className={`
                            text-xs mt-2 font-medium
                            ${isCurrent ? 'text-blue-100' : isCompleted ? 'text-emerald-100' : 'text-slate-500'}
                          `}>
                            {stats.successful}/{processingResults.length} processed
                          </div>
                        )}
                      </div>

                    </button>

                    {/* Hover effect overlay */}
                    {isClickable && (
                      <div className={`
                        absolute inset-0 opacity-0 group-hover:opacity-10 transition-opacity duration-300
                        ${stepIdx === 0 ? 'rounded-l-2xl' : ''}
                        ${stepIdx === steps.length - 1 ? 'rounded-r-2xl' : ''}
                        ${isCurrent ? 'bg-white' : 'bg-blue-600'}
                      `} 
                      style={{
                        clipPath: stepIdx === steps.length - 1 
                          ? undefined 
                          : 'polygon(0% 0%, calc(100% - 20px) 0%, 100% 50%, calc(100% - 20px) 100%, 0% 100%, 20px 50%)',
                        pointerEvents: 'none'
                      }} />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </nav>
      </div>
    </div>
  );
};

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
  const getStageStatus = (stage: AppStage): 'completed' | 'current' | 'pending' => {
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

  const steps = [
    { id: 'upload', name: 'Upload & Select', subtitle: 'Choose source documents', icon: Upload },
    { id: 'review', name: 'Review & Edit', subtitle: 'Quality assessment & optimization', icon: Eye },
    { id: 'download', name: 'Export Results', subtitle: 'Download processed documents', icon: Download }
  ];

  return (
    <div className="h-full flex flex-col">
      {/* Enhanced Chevron Progress Header */}
      <div className="bg-gradient-to-r from-slate-50 to-slate-100 border-b border-slate-200">
        <div className="px-6 py-6">
          <nav aria-label="Processing Pipeline Progress" className="max-w-7xl mx-auto">
            <div className="flex items-center justify-center overflow-x-auto">
              {steps.map((step, stepIdx) => {
                const status = getStageStatus(step.id as AppStage);
                const isCompleted = status === 'completed';
                const isCurrent = status === 'current';
                const isClickable = step.id === 'upload' || 
                  (step.id === 'review' && state.processingResults.length > 0) || 
                  (step.id === 'download' && state.processingComplete);

                return (
                  <div key={step.id} className="flex items-center group relative">
                    {/* Chevron Step Container */}
                    <div className="relative">
                      <button
                        onClick={() => {
                          if (isClickable) {
                            handleStageChange(step.id as AppStage);
                          }
                        }}
                        disabled={!isClickable}
                        className={`
                          relative flex items-center px-8 py-6 transition-all duration-300 transform
                          ${stepIdx === 0 ? 'pl-6 rounded-l-2xl' : ''}
                          ${stepIdx === steps.length - 1 ? 'pr-6 rounded-r-2xl' : 'pr-12'}
                          ${isClickable ? 'cursor-pointer hover:scale-[1.02]' : 'cursor-default'}
                          ${isCurrent 
                            ? 'bg-gradient-to-r from-blue-600 to-blue-700 text-white shadow-xl z-30 scale-[1.02]' 
                            : isCompleted
                              ? 'bg-gradient-to-r from-emerald-500 to-emerald-600 text-white shadow-lg z-20 hover:from-emerald-600 hover:to-emerald-700'
                              : 'bg-white text-slate-600 shadow-md z-10 hover:bg-slate-50 hover:shadow-lg'
                          }
                          disabled:opacity-60 min-w-[280px]
                        `}
                        style={{
                          clipPath: stepIdx === steps.length - 1 
                            ? undefined 
                            : 'polygon(0% 0%, calc(100% - 20px) 0%, 100% 50%, calc(100% - 20px) 100%, 0% 100%, 20px 50%)',
                          marginLeft: stepIdx === 0 ? '0' : '-20px'
                        }}
                      >
                        
                        {/* Text Content */}
                        <div className="ml-4 text-left flex-1 min-w-0">
                          <div className={`
                            font-bold text-lg leading-tight
                            ${isCurrent ? 'text-white' : isCompleted ? 'text-white' : 'text-slate-800'}
                          `}>
                            {step.name}
                          </div>
                          <div className={`
                            text-sm mt-1 leading-tight
                            ${isCurrent ? 'text-blue-100' : isCompleted ? 'text-emerald-100' : 'text-slate-500'}
                          `}>
                            {step.subtitle}
                          </div>
                          
                          {/* Progress indicators */}
                          {step.id === 'review' && state.processingResults.length > 0 && (
                            <div className={`
                              text-xs mt-2 font-medium
                              ${isCurrent ? 'text-blue-100' : isCompleted ? 'text-emerald-100' : 'text-slate-500'}
                            `}>
                              {stats.successful}/{state.processingResults.length} processed
                            </div>
                          )}
                        </div>

                      </button>

                      {/* Hover effect overlay */}
                      {isClickable && (
                        <div className={`
                          absolute inset-0 opacity-0 group-hover:opacity-10 transition-opacity duration-300
                          ${stepIdx === 0 ? 'rounded-l-2xl' : ''}
                          ${stepIdx === steps.length - 1 ? 'rounded-r-2xl' : ''}
                          ${isCurrent ? 'bg-white' : 'bg-blue-600'}
                        `} 
                        style={{
                          clipPath: stepIdx === steps.length - 1 
                            ? undefined 
                            : 'polygon(0% 0%, calc(100% - 20px) 0%, 100% 50%, calc(100% - 20px) 100%, 0% 100%, 20px 50%)',
                          pointerEvents: 'none'
                        }} />
                      )}
                    </div>
                  </div>
                );
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
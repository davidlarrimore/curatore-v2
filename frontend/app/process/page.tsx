// app/process/page.tsx
'use client'

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { ProcessingStage, ProcessingState, FileInfo, ProcessingResult, ProcessingOptions } from '@/types';
import { systemApi, utils } from '@/lib/api';
import { Accordion, AccordionItem } from '@/components/ui/Accordion';
import { UploadSelectStage } from '@/components/stages/UploadSelectStage';
import { ProcessingStage as ProcessingStageComponent } from '@/components/stages/ProcessingStage';
import { ReviewStage } from '@/components/stages/ReviewStage';
import { DownloadStage } from '@/components/stages/DownloadStage';

export default function ProcessPage() {
  const router = useRouter();
  const [state, setState] = useState<ProcessingState>({
    currentStage: 'upload',
    sourceType: 'upload',
    selectedFiles: [],
    processingResults: [],
    processingComplete: false,
    config: {
      quality_thresholds: {
        conversion: 70,
        clarity: 7,
        completeness: 7,
        relevance: 7,
        markdown: 7
      },
      ocr_settings: {
        language: 'eng',
        psm: 3
      },
      auto_optimize: true
    }
  });

  const [systemStatus, setSystemStatus] = useState({
    health: 'checking...',
    llmConnected: false,
    supportedFormats: [] as string[],
    maxFileSize: 52428800
  });

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string>('');
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [isResetting, setIsResetting] = useState(false);

  // Load initial data
  useEffect(() => {
    loadInitialData();
  }, []);

  const loadInitialData = async () => {
    setIsLoading(true);
    try {
      // Load system status and configuration
      const [healthStatus, config, formatsData] = await Promise.all([
        systemApi.getHealth(),
        systemApi.getConfig(),
        systemApi.getSupportedFormats()
      ]);

      setSystemStatus({
        health: healthStatus.status,
        llmConnected: healthStatus.llm_connected,
        supportedFormats: formatsData.supported_extensions,
        maxFileSize: formatsData.max_file_size
      });

      setState(prev => ({
        ...prev,
        config: {
          ...prev.config,
          ...config
        }
      }));

    } catch (error) {
      console.error('Failed to load initial data:', error);
      setError('Failed to load application data. Please refresh the page.');
    } finally {
      setIsLoading(false);
    }
  };

  // Reset system handler
  const handleResetSystem = async () => {
    setIsResetting(true);
    try {
      await systemApi.resetSystem();
      
      // Reset local state
      setState({
        currentStage: 'upload',
        sourceType: 'upload',
        selectedFiles: [],
        processingResults: [],
        processingComplete: false,
        config: state.config // Keep configuration
      });
      
      setError('');
      setShowResetConfirm(false);
      
      // Show success message briefly
      setError('✅ System reset successfully');
      setTimeout(() => setError(''), 3000);
      
    } catch (error) {
      console.error('Reset failed:', error);
      const errorMessage = error instanceof Error ? error.message : 'Reset failed';
      setError(`❌ Reset failed: ${errorMessage}`);
    } finally {
      setIsResetting(false);
    }
  };

  // Stage navigation handlers
  const handleStageChange = (stage: ProcessingStage) => {
    setState(prev => ({ ...prev, currentStage: stage }));
  };

  // Fixed handler for accordion onToggle
  const handleAccordionToggle = (id: string) => {
    handleStageChange(id as ProcessingStage);
  };

  const handleSourceTypeChange = (sourceType: 'local' | 'upload') => {
    setState(prev => ({
      ...prev,
      sourceType,
      selectedFiles: [] // Clear selection when switching
    }));
  };

  const handleSelectedFilesChange = (files: FileInfo[]) => {
    setState(prev => ({ ...prev, selectedFiles: files }));
  };

  const handleProcessingOptionsChange = (options: ProcessingOptions) => {
    setState(prev => ({
      ...prev,
      config: {
        ...prev.config,
        ...options
      }
    }));
  };

  const handleProcessStart = (files: FileInfo[], options: ProcessingOptions) => {
    if (!systemStatus.llmConnected) {
      setError('Cannot process files: LLM connection is not available');
      return;
    }

    setState(prev => ({
      ...prev,
      selectedFiles: files,
      config: { ...prev.config, ...options },
      currentStage: 'process',
      processingComplete: false,
      processingResults: []
    }));
  };

  const handleProcessingComplete = (results: ProcessingResult[]) => {
    setState(prev => ({
      ...prev,
      processingResults: results,
      processingComplete: true,
      currentStage: 'review'
    }));
  };

  const handleProcessingError = (error: string) => {
    setError(error);
    setState(prev => ({ ...prev, currentStage: 'upload' }));
  };

  const handleResultsUpdate = (results: ProcessingResult[]) => {
    setState(prev => ({ ...prev, processingResults: results }));
  };

  const handleReviewComplete = () => {
    setState(prev => ({ ...prev, currentStage: 'download' }));
  };

  const handleRestart = () => {
    setState({
      currentStage: 'upload',
      sourceType: 'upload',
      selectedFiles: [],
      processingResults: [],
      processingComplete: false,
      config: state.config // Keep configuration
    });
    setError('');
  };

  // Determine stage completion status
  const getStageStatus = (stage: ProcessingStage) => {
    switch (stage) {
      case 'upload':
        return state.currentStage !== 'upload';
      case 'process':
        return state.processingComplete;
      case 'review':
        return state.currentStage === 'download';
      case 'download':
        return false; // Never completed, can always restart
      default:
        return false;
    }
  };

  // Determine if stage should be disabled
  const isStageDisabled = (stage: ProcessingStage) => {
    switch (stage) {
      case 'upload':
        return false; // Always enabled
      case 'process':
        return state.selectedFiles.length === 0;
      case 'review':
        return !state.processingComplete;
      case 'download':
        return state.processingResults.length === 0;
      default:
        return true;
    }
  };

  // Get stage subtitle
  const getStageSubtitle = (stage: ProcessingStage) => {
    switch (stage) {
      case 'upload':
        return `${state.selectedFiles.length} files selected`;
      case 'process':
        return state.processingComplete 
          ? `${state.processingResults.length} files processed`
          : 'Ready to process';
      case 'review':
        const ragReady = state.processingResults.filter(r => r.pass_all_thresholds).length;
        return `${ragReady}/${state.processingResults.length} RAG-ready`;
      case 'download':
        return 'Download and manage results';
      default:
        return '';
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading Curatore...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">📚 Curatore v2</h1>
              <p className="text-gray-600 mt-1">RAG Document Processing & Optimization</p>
            </div>
            
            <div className="flex items-center space-x-4">
              {/* System Status */}
              <div className="flex items-center space-x-4 text-sm">
                <div className="flex items-center space-x-2">
                  <div className={`w-2 h-2 rounded-full ${
                    systemStatus.health === 'healthy' ? 'bg-green-500' : 'bg-red-500'
                  }`}></div>
                  <span className="text-gray-600">API</span>
                </div>
                <div className="flex items-center space-x-2">
                  <div className={`w-2 h-2 rounded-full ${
                    systemStatus.llmConnected ? 'bg-green-500' : 'bg-red-500'
                  }`}></div>
                  <span className="text-gray-600">LLM</span>
                </div>
              </div>
              
              {/* Reset Button */}
              <button
                type="button"
                onClick={() => setShowResetConfirm(true)}
                disabled={isResetting}
                className="flex items-center space-x-2 px-4 py-2 bg-red-100 hover:bg-red-200 text-red-700 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isResetting ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-red-600"></div>
                    <span className="hidden sm:inline">Resetting...</span>
                  </>
                ) : (
                  <>
                    <span>🔄</span>
                    <span className="hidden sm:inline">Reset</span>
                  </>
                )}
              </button>
              
              {/* Settings Button */}
              <button
                type="button"
                onClick={() => router.push('/settings')}
                className="flex items-center space-x-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors"
              >
                <span>⚙️</span>
                <span className="hidden sm:inline">Settings</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Reset Confirmation Modal */}
        {showResetConfirm && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg p-6 max-w-md w-mx-4">
              <div className="text-center">
                <div className="text-6xl mb-4">⚠️</div>
                <h3 className="text-xl font-bold text-gray-900 mb-2">Reset System?</h3>
                <p className="text-gray-600 mb-6">
                  This will permanently delete all uploaded files, processed documents, and reset the system to the initial state. This action cannot be undone.
                </p>
                
                <div className="flex space-x-3">
                  <button
                    type="button"
                    onClick={() => setShowResetConfirm(false)}
                    disabled={isResetting}
                    className="flex-1 px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleResetSystem}
                    disabled={isResetting}
                    className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isResetting ? (
                      <div className="flex items-center justify-center space-x-2">
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                        <span>Resetting...</span>
                      </div>
                    ) : (
                      'Yes, Reset System'
                    )}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Error Display */}
        {error && (
          <div className={`mb-6 rounded-lg p-4 ${
            error.startsWith('✅') 
              ? 'bg-green-50 border border-green-200'
              : 'bg-red-50 border border-red-200'
          }`}>
            <div className="flex items-center justify-between">
              <p className={error.startsWith('✅') ? 'text-green-800' : 'text-red-800'}>
                {error}
              </p>
              <button
                type="button"
                onClick={() => setError('')}
                className={`text-sm underline ${
                  error.startsWith('✅') ? 'text-green-600 hover:text-green-800' : 'text-red-600 hover:text-red-800'
                }`}
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {/* Processing Stages Accordion */}
        <Accordion 
          activeId={state.currentStage} 
          onActiveChange={handleAccordionToggle}
        >
          {/* Stage 1: Upload & Select Documents */}
          <AccordionItem
            id="upload"
            title="1. Upload & Select Documents"
            subtitle={getStageSubtitle('upload')}
            icon="📁"
            isOpen={state.currentStage === 'upload'}
            onToggle={handleAccordionToggle}
            disabled={isStageDisabled('upload')}
            completed={getStageStatus('upload')}
          >
            <UploadSelectStage
              sourceType={state.sourceType}
              onSourceTypeChange={handleSourceTypeChange}
              selectedFiles={state.selectedFiles}
              onSelectedFilesChange={handleSelectedFilesChange}
              onProcess={handleProcessStart}
              supportedFormats={systemStatus.supportedFormats}
              maxFileSize={systemStatus.maxFileSize}
              processingOptions={{
                auto_optimize: state.config.auto_optimize,
                ocr_settings: state.config.ocr_settings,
                quality_thresholds: state.config.quality_thresholds
              }}
              onProcessingOptionsChange={handleProcessingOptionsChange}
              isProcessing={state.currentStage === 'process'}
            />
          </AccordionItem>

          {/* Stage 2: Process Documents */}
          <AccordionItem
            id="process"
            title="2. Process Documents"
            subtitle={getStageSubtitle('process')}
            icon="⚙️"
            isOpen={state.currentStage === 'process'}
            onToggle={handleAccordionToggle}
            disabled={isStageDisabled('process')}
            completed={getStageStatus('process')}
          >
            {state.currentStage === 'process' && (
              <ProcessingStageComponent
                selectedFiles={state.selectedFiles}
                processingOptions={{
                  auto_optimize: state.config.auto_optimize,
                  ocr_settings: state.config.ocr_settings,
                  quality_thresholds: state.config.quality_thresholds
                }}
                onProcessingComplete={handleProcessingComplete}
                onError={handleProcessingError}
              />
            )}
          </AccordionItem>

          {/* Stage 3: Review Results */}
          <AccordionItem
            id="review"
            title="3. Review Results"
            subtitle={getStageSubtitle('review')}
            icon="📊"
            isOpen={state.currentStage === 'review'}
            onToggle={handleAccordionToggle}
            disabled={isStageDisabled('review')}
            completed={getStageStatus('review')}
          >
            {state.currentStage === 'review' && (
              <ReviewStage
                processingResults={state.processingResults}
                onResultsUpdate={handleResultsUpdate}
                onComplete={handleReviewComplete}
                qualityThresholds={state.config.quality_thresholds}
              />
            )}
          </AccordionItem>

          {/* Stage 4: Download Results */}
          <AccordionItem
            id="download"
            title="4. Download Results"
            subtitle={getStageSubtitle('download')}
            icon="⬇️"
            isOpen={state.currentStage === 'download'}
            onToggle={handleAccordionToggle}
            disabled={isStageDisabled('download')}
            completed={getStageStatus('download')}
          >
            {state.currentStage === 'download' && (
              <DownloadStage
                processingResults={state.processingResults}
                onRestart={handleRestart}
              />
            )}
          </AccordionItem>
        </Accordion>

        {/* Footer */}
        <div className="mt-12 text-center text-gray-500 text-sm">
          <p>
            <strong>Curatore v2</strong> - Transform documents into RAG-ready, semantically optimized content
          </p>
          <p className="mt-1">
            Multi-stage processing pipeline for optimal vector database integration
          </p>
        </div>
      </div>
    </div>
  );
}
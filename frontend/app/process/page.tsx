// app/process/page.tsx
'use client'

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { ProcessingStage, ProcessingState, FileInfo, ProcessingResult, ProcessingOptions } from '@/types';
import { systemApi, utils } from '@/lib/api';
import { UploadSelectStage } from '@/components/stages/UploadSelectStage';
import { ProcessingPanel } from '@/components/ProcessingPanel';
import { ReviewStage } from '@/components/stages/ReviewStage';
import { DownloadStage } from '@/components/stages/DownloadStage';

type AppStage = 'upload' | 'review' | 'download';

export default function ProcessPage() {
  const router = useRouter();
  const [currentStage, setCurrentStage] = useState<AppStage>('upload');
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

  // Processing panel state
  const [showProcessingPanel, setShowProcessingPanel] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isProcessingComplete, setIsProcessingComplete] = useState(false);

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
      
      setCurrentStage('upload');
      setShowProcessingPanel(false);
      setIsProcessing(false);
      setIsProcessingComplete(false);
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
      processingResults: []
    }));

    // Switch to review stage and show processing panel
    setCurrentStage('review');
    setShowProcessingPanel(true);
    setIsProcessing(true);
    setIsProcessingComplete(false);
  };

  const handleProcessingComplete = (results: ProcessingResult[]) => {
    setState(prev => ({
      ...prev,
      processingResults: results,
      processingComplete: true
    }));
    
    setIsProcessing(false);
    setIsProcessingComplete(true);
    // Keep the processing panel open so user can see the logs/results
  };

  const handleProcessingError = (error: string) => {
    setError(error);
    setIsProcessing(false);
    setIsProcessingComplete(false);
    // Don't close the processing panel so user can see the error logs
  };

  const handleResultsUpdate = (results: ProcessingResult[]) => {
    setState(prev => ({ ...prev, processingResults: results }));
  };

  const handleReviewComplete = () => {
    setCurrentStage('download');
    setShowProcessingPanel(false); // Close processing panel when moving to download
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
    setCurrentStage('upload');
    setShowProcessingPanel(false);
    setIsProcessing(false);
    setIsProcessingComplete(false);
    setError('');
  };

  const handleCloseProcessingPanel = () => {
    setShowProcessingPanel(false);
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

        {/* Stage Navigation */}
        <div className="flex items-center justify-center mb-8">
          <div className="flex items-center space-x-4">
            {/* Upload Stage */}
            <div className="flex items-center">
              <div className={`flex items-center justify-center w-10 h-10 rounded-full ${
                currentStage === 'upload' 
                  ? 'bg-blue-600 text-white' 
                  : state.selectedFiles.length > 0
                    ? 'bg-green-600 text-white'
                    : 'bg-gray-300 text-gray-600'
              }`}>
                {state.selectedFiles.length > 0 ? '✓' : '1'}
              </div>
              <span className={`ml-2 font-medium ${
                currentStage === 'upload' ? 'text-blue-600' : 'text-gray-600'
              }`}>
                Upload & Select
              </span>
            </div>

            {/* Arrow */}
            <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>

            {/* Review Stage */}
            <div className="flex items-center">
              <div className={`flex items-center justify-center w-10 h-10 rounded-full ${
                currentStage === 'review' 
                  ? 'bg-blue-600 text-white' 
                  : isProcessingComplete
                    ? 'bg-green-600 text-white'
                    : 'bg-gray-300 text-gray-600'
              }`}>
                {isProcessingComplete ? '✓' : '2'}
              </div>
              <span className={`ml-2 font-medium ${
                currentStage === 'review' ? 'text-blue-600' : 'text-gray-600'
              }`}>
                Review Results
              </span>
            </div>

            {/* Arrow */}
            <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>

            {/* Download Stage */}
            <div className="flex items-center">
              <div className={`flex items-center justify-center w-10 h-10 rounded-full ${
                currentStage === 'download' 
                  ? 'bg-blue-600 text-white' 
                  : 'bg-gray-300 text-gray-600'
              }`}>
                3
              </div>
              <span className={`ml-2 font-medium ${
                currentStage === 'download' ? 'text-blue-600' : 'text-gray-600'
              }`}>
                Download
              </span>
            </div>
          </div>
        </div>

        {/* Stage Content */}
        <div className="bg-white rounded-2xl border shadow-sm p-6 mb-8">
          {currentStage === 'upload' && (
            <div>
              <div className="text-center mb-6">
                <h2 className="text-2xl font-bold text-gray-900 mb-2">📁 Upload & Select Documents</h2>
                <p className="text-gray-600">Choose documents to process for RAG optimization</p>
              </div>
              
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
                isProcessing={isProcessing}
              />
            </div>
          )}

          {currentStage === 'review' && (
            <ReviewStage
              processingResults={state.processingResults}
              onResultsUpdate={handleResultsUpdate}
              onComplete={handleReviewComplete}
              qualityThresholds={state.config.quality_thresholds}
              isProcessingComplete={isProcessingComplete}
              isProcessing={isProcessing}
              selectedFiles={state.selectedFiles}
            />
          )}

          {currentStage === 'download' && (
            <DownloadStage
              processingResults={state.processingResults}
              onRestart={handleRestart}
            />
          )}
        </div>

        {/* Footer */}
        <div className="text-center text-gray-500 text-sm">
          <p>
            <strong>Curatore v2</strong> - Transform documents into RAG-ready, semantically optimized content
          </p>
          <p className="mt-1">
            Streamlined processing pipeline for optimal vector database integration
          </p>
        </div>
      </div>

      {/* Background Processing Panel */}
      <ProcessingPanel
        selectedFiles={state.selectedFiles}
        processingOptions={{
          auto_optimize: state.config.auto_optimize,
          ocr_settings: state.config.ocr_settings,
          quality_thresholds: state.config.quality_thresholds
        }}
        onProcessingComplete={handleProcessingComplete}
        onError={handleProcessingError}
        isVisible={showProcessingPanel}
        onClose={handleCloseProcessingPanel}
      />
    </div>
  );
}
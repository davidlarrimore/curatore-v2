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
        {/* Error Display */}
        {error && (
          <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4">
            <div className="flex items-center space-x-2">
              <span className="text-red-600">❌</span>
              <p className="text-red-800">{error}</p>
            </div>
            <button
              type="button"
              onClick={() => setError('')}
              className="mt-2 text-red-600 hover:text-red-800 text-sm underline"
            >
              Dismiss
            </button>
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
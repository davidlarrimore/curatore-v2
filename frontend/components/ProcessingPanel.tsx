// components/ProcessingPanel.tsx
'use client'

import { useState, useEffect } from 'react';
import { ProcessingResult, FileInfo, ProcessingOptions } from '@/types';
import { processingApi, utils } from '@/lib/api';

interface ProcessingLog {
  timestamp: string;
  level: 'info' | 'success' | 'warning' | 'error';
  message: string;
}

interface ProcessingPanelProps {
  selectedFiles: FileInfo[];
  processingOptions: ProcessingOptions;
  onProcessingComplete: (results: ProcessingResult[]) => void;
  onError: (error: string) => void;
  isVisible: boolean;
  onClose: () => void;
}

type PanelState = 'minimized' | 'normal' | 'fullscreen';

export function ProcessingPanel({
  selectedFiles,
  processingOptions,
  onProcessingComplete,
  onError,
  isVisible,
  onClose
}: ProcessingPanelProps) {
  const [panelState, setPanelState] = useState<PanelState>('normal');
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [currentFile, setCurrentFile] = useState<string>('');
  const [results, setResults] = useState<ProcessingResult[]>([]);
  const [logs, setLogs] = useState<ProcessingLog[]>([]);
  const [processingStartTime, setProcessingStartTime] = useState<number>(0);
  const [processingComplete, setProcessingComplete] = useState(false);

  // Start processing when panel becomes visible
  useEffect(() => {
    if (isVisible && selectedFiles.length > 0 && !isProcessing && !processingComplete) {
      processFiles();
    }
  }, [isVisible, selectedFiles]);

  // Handle fullscreen body scroll lock
  useEffect(() => {
    if (panelState === 'fullscreen') {
      // Prevent body scroll when fullscreen
      document.body.style.overflow = 'hidden';
      return () => {
        document.body.style.overflow = 'unset';
      };
    } else {
      // Ensure body scroll is restored when not fullscreen
      document.body.style.overflow = 'unset';
    }
  }, [panelState]);

  const addLog = (level: ProcessingLog['level'], message: string) => {
    const timestamp = new Date().toLocaleTimeString();
    const newLog: ProcessingLog = { timestamp, level, message };
    setLogs(prev => [...prev.slice(-50), newLog]); // Keep last 50 logs
  };

  const getLogIcon = (level: ProcessingLog['level']) => {
    switch (level) {
      case 'success': return '✅';
      case 'warning': return '⚠️';
      case 'error': return '❌';
      default: return 'ℹ️';
    }
  };

  const processFiles = async () => {
    if (selectedFiles.length === 0) {
      onError('No files selected for processing');
      return;
    }

    setIsProcessing(true);
    setProgress(0);
    setResults([]);
    setLogs([]);
    setProcessingStartTime(Date.now());
    setProcessingComplete(false);

    addLog('info', `🚀 Starting background processing of ${selectedFiles.length} files...`);
    addLog('info', `🎯 Vector optimization: ${processingOptions.auto_optimize ? 'Enabled' : 'Disabled'}`);

    try {
      const processedResults: ProcessingResult[] = [];

      for (let i = 0; i < selectedFiles.length; i++) {
        const file = selectedFiles[i];
        setCurrentFile(file.filename);
        setProgress(((i) / selectedFiles.length) * 100);

        addLog('info', `📄 Processing: ${file.filename}`);

        try {
          const result = await processingApi.processDocument(file.document_id, processingOptions);
          
          if (result.success) {
            addLog('success', `✅ Successfully processed: ${file.filename}`);
            addLog('info', `📊 Conversion score: ${result.conversion_score}/100`);
            
            if (result.llm_evaluation) {
              const eval_scores = [
                `Clarity: ${result.llm_evaluation.clarity_score || 'N/A'}/10`,
                `Completeness: ${result.llm_evaluation.completeness_score || 'N/A'}/10`,
                `Relevance: ${result.llm_evaluation.relevance_score || 'N/A'}/10`,
                `Markdown: ${result.llm_evaluation.markdown_score || 'N/A'}/10`
              ].join(', ');
              addLog('info', `📈 Quality scores - ${eval_scores}`);
            }

            if (result.pass_all_thresholds) {
              addLog('success', `🎯 ${file.filename} is RAG-ready! ✨`);
            } else {
              addLog('warning', `⚠️ ${file.filename} needs improvement to meet quality thresholds`);
            }
          } else {
            addLog('error', `❌ Processing failed for ${file.filename}: ${result.message}`);
          }

          processedResults.push(result);
          setResults([...processedResults]);

        } catch (error) {
          const errorMessage = error instanceof Error ? error.message : 'Unknown error';
          addLog('error', `❌ Error processing ${file.filename}: ${errorMessage}`);
          
          const failedResult: ProcessingResult = {
            document_id: file.document_id,
            filename: file.filename,
            status: 'failed',
            success: false,
            message: errorMessage,
            conversion_score: 0,
            pass_all_thresholds: false,
            vector_optimized: false
          };
          
          processedResults.push(failedResult);
          setResults([...processedResults]);
        }

        addLog('info', '─'.repeat(30));
      }

      setProgress(100);
      setCurrentFile('');

      // Final summary
      const successful = processedResults.filter(r => r.success).length;
      const failed = processedResults.length - successful;
      const ragReady = processedResults.filter(r => r.pass_all_thresholds).length;
      const processingTime = (Date.now() - processingStartTime) / 1000;

      addLog('success', `🎉 Processing complete!`);
      addLog('info', `📊 Summary: ${successful} successful, ${failed} failed, ${ragReady} RAG-ready`);
      addLog('info', `⏱️ Total time: ${utils.formatDuration(processingTime)}`);

      setProcessingComplete(true);
      onProcessingComplete(processedResults);

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      addLog('error', `❌ Batch processing failed: ${errorMessage}`);
      onError(errorMessage);
    } finally {
      setIsProcessing(false);
    }
  };

  if (!isVisible) return null;

  const successful = results.filter(r => r.success).length;
  const failed = results.length - successful;
  const ragReady = results.filter(r => r.pass_all_thresholds).length;

  // Panel height classes based on state
  const getPanelClasses = () => {
    const baseClasses = "fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 shadow-2xl transition-all duration-300 ease-in-out z-50";
    
    switch (panelState) {
      case 'minimized':
        return `${baseClasses} h-16`;
      case 'fullscreen':
        return `${baseClasses} h-screen overflow-hidden`; // Prevent body scroll
      case 'normal':
      default:
        return `${baseClasses} h-80`;
    }
  };

  return (
    <div className={getPanelClasses()}>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-gray-200 bg-gray-50">
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2">
            {isProcessing ? (
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>
            ) : processingComplete ? (
              <span className="text-green-600">✅</span>
            ) : (
              <span className="text-blue-600">📄</span>
            )}
            <h3 className="font-medium text-gray-900">
              {isProcessing 
                ? `Processing Documents... (${Math.round(progress)}%)`
                : processingComplete
                  ? 'Processing Complete'
                  : 'Document Processing'
              }
            </h3>
          </div>

          {/* Mini stats when minimized */}
          {panelState === 'minimized' && (
            <div className="flex items-center space-x-4 text-sm text-gray-600">
              <span>{selectedFiles.length} files</span>
              {results.length > 0 && (
                <>
                  <span>•</span>
                  <span className="text-green-600">{successful} success</span>
                  <span>•</span>
                  <span className="text-blue-600">{ragReady} RAG-ready</span>
                </>
              )}
              {currentFile && (
                <>
                  <span>•</span>
                  <span className="text-blue-600">Processing: {currentFile}</span>
                </>
              )}
            </div>
          )}
        </div>

        {/* Controls */}
        <div className="flex items-center space-x-2">
          {/* Minimize/Restore */}
          <button
            type="button"
            onClick={() => setPanelState(panelState === 'minimized' ? 'normal' : 'minimized')}
            className="p-2 hover:bg-gray-200 rounded-lg transition-colors"
            title={panelState === 'minimized' ? 'Restore' : 'Minimize'}
          >
            {panelState === 'minimized' ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 14l9-9 3 3L9 18l-6-6z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 12H4" />
              </svg>
            )}
          </button>

          {/* Fullscreen */}
          <button
            type="button"
            onClick={() => setPanelState(panelState === 'fullscreen' ? 'normal' : 'fullscreen')}
            className="p-2 hover:bg-gray-200 rounded-lg transition-colors"
            title={panelState === 'fullscreen' ? 'Exit Fullscreen' : 'Fullscreen'}
          >
            {panelState === 'fullscreen' ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 9V4.5M9 9H4.5M9 9L3.5 3.5M15 15v4.5M15 15h4.5M15 15l5.5 5.5M15 9h4.5M15 9V4.5M15 9l5.5-5.5M9 15H4.5M9 15v4.5M9 15l-5.5 5.5" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5v-4m0 4h-4m4 0l-5-5" />
              </svg>
            )}
          </button>

          {/* Close */}
          {processingComplete && (
            <button
              type="button"
              onClick={onClose}
              className="p-2 hover:bg-gray-200 rounded-lg transition-colors"
              title="Close"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Content (hidden when minimized) */}
      {panelState !== 'minimized' && (
        <div className={`flex-1 overflow-hidden ${
          panelState === 'fullscreen' 
            ? 'h-[calc(100vh-4rem)]' 
            : 'h-[calc(20rem-4rem)]' // Fixed height for normal mode (320px - header)
        }`}>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 p-4 h-full">
            {/* Progress and Stats */}
            <div className="space-y-4 overflow-y-auto">
              {/* Progress Bar */}
              <div className="flex-shrink-0">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-gray-700">Progress</span>
                  <span className="text-sm text-gray-600">{Math.round(progress)}%</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div 
                    className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>

              {/* Current File */}
              {currentFile && (
                <div className="flex items-center space-x-2 text-sm text-gray-600 flex-shrink-0">
                  <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-blue-600"></div>
                  <span>Processing: <strong>{currentFile}</strong></span>
                </div>
              )}

              {/* Stats Grid */}
              {results.length > 0 && (
                <div className="grid grid-cols-3 gap-3 flex-shrink-0">
                  <div className="text-center p-3 bg-green-50 rounded-lg">
                    <div className="text-xl font-bold text-green-600">{successful}</div>
                    <div className="text-xs text-green-800">Successful</div>
                  </div>
                  <div className="text-center p-3 bg-red-50 rounded-lg">
                    <div className="text-xl font-bold text-red-600">{failed}</div>
                    <div className="text-xs text-red-800">Failed</div>
                  </div>
                  <div className="text-center p-3 bg-blue-50 rounded-lg">
                    <div className="text-xl font-bold text-blue-600">{ragReady}</div>
                    <div className="text-xs text-blue-800">RAG Ready</div>
                  </div>
                </div>
              )}

              {/* Results Preview */}
              {results.length > 0 && (
                <div className="border rounded-lg flex flex-col min-h-0 flex-1">
                  <h4 className="font-medium p-3 border-b bg-gray-50 flex-shrink-0">Recent Results</h4>
                  <div className="overflow-y-auto flex-1">
                    {results.slice(-3).map((result) => (
                      <div key={result.document_id} className="flex items-center justify-between p-2 border-b last:border-b-0">
                        <div className="flex items-center space-x-2">
                          <span className="text-sm">
                            {result.success ? (result.pass_all_thresholds ? '✅' : '⚠️') : '❌'}
                          </span>
                          <span className="text-sm font-medium truncate">{result.filename}</span>
                        </div>
                        <span className="text-xs text-gray-500">{result.conversion_score}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Processing Log - Fixed height for normal mode */}
            <div className={`border rounded-lg flex flex-col ${
              panelState === 'fullscreen' 
                ? 'h-full' 
                : 'h-64' // Fixed height for normal mode
            }`}>
              <div className="flex items-center justify-between p-3 border-b bg-gray-50 flex-shrink-0">
                <h4 className="font-medium">Processing Log</h4>
                <div className="flex items-center space-x-2">
                  <span className="text-xs text-gray-500">{logs.length} entries</span>
                  {logs.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setLogs([])}
                      className="text-xs text-gray-500 hover:text-gray-700 underline"
                    >
                      Clear
                    </button>
                  )}
                </div>
              </div>
              
              <div className="bg-black text-green-400 font-mono text-xs flex-1 overflow-hidden relative">
                {logs.length === 0 ? (
                  <div className="p-4 text-center text-gray-500 h-full flex items-center justify-center">
                    <p>Processing log will appear here...</p>
                  </div>
                ) : (
                  <div 
                    className="p-2 h-full overflow-y-auto scrollbar-thin scrollbar-thumb-green-400 scrollbar-track-gray-800"
                    style={{ 
                      scrollbarWidth: 'thin', 
                      scrollbarColor: '#22c55e #1f2937'
                    }}
                    onWheel={(e) => {
                      // Prevent event bubbling to parent when scrolling in fullscreen
                      if (panelState === 'fullscreen') {
                        e.stopPropagation();
                      }
                    }}
                  >
                    {logs.map((log, index) => (
                      <div key={index} className="flex items-start space-x-2 mb-1 min-h-[1.2rem]">
                        <span className="text-gray-400 text-xs flex-shrink-0 w-20 font-mono">{log.timestamp}</span>
                        <span className="flex-shrink-0">{getLogIcon(log.level)}</span>
                        <span className={`flex-1 break-words ${
                          log.level === 'error' ? 'text-red-400' :
                          log.level === 'warning' ? 'text-yellow-400' :
                          log.level === 'success' ? 'text-green-400' :
                          'text-gray-300'
                        }`}>
                          {log.message}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
// components/stages/ProcessingStage.tsx
'use client'

import { useState, useEffect } from 'react';
import { ProcessingResult, FileInfo, ProcessingOptions } from '@/types';
import { processingApi, utils } from '@/lib/api';

interface ProcessingStageProps {
  selectedFiles: FileInfo[];
  processingOptions: ProcessingOptions;
  onProcessingComplete: (results: ProcessingResult[]) => void;
  onError: (error: string) => void;
}

interface ProcessingLog {
  timestamp: string;
  level: 'info' | 'success' | 'warning' | 'error';
  message: string;
}

export function ProcessingStage({
  selectedFiles,
  processingOptions,
  onProcessingComplete,
  onError
}: ProcessingStageProps) {
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [currentFile, setCurrentFile] = useState<string>('');
  const [results, setResults] = useState<ProcessingResult[]>([]);
  const [logs, setLogs] = useState<ProcessingLog[]>([]);
  const [processingStartTime, setProcessingStartTime] = useState<number>(0);

  const addLog = (level: ProcessingLog['level'], message: string) => {
    const timestamp = new Date().toLocaleTimeString();
    const newLog: ProcessingLog = { timestamp, level, message };
    setLogs(prev => [...prev.slice(-20), newLog]); // Keep last 20 logs
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

    addLog('info', `🚀 Starting processing of ${selectedFiles.length} files...`);
    addLog('info', `🎯 Vector optimization: ${processingOptions.auto_optimize ? 'Enabled' : 'Disabled'}`);

    try {
      // Process files individually to show progress
      const processedResults: ProcessingResult[] = [];

      for (let i = 0; i < selectedFiles.length; i++) {
        const file = selectedFiles[i];
        setCurrentFile(file.filename);
        setProgress(((i) / selectedFiles.length) * 100);

        addLog('info', `📄 Processing: ${file.filename}`);

        try {
          // Step 1: Convert to markdown
          addLog('info', `🔄 Converting ${file.filename} to markdown...`);
          
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

            if (result.document_summary) {
              addLog('info', `📝 Summary: ${result.document_summary.substring(0, 100)}...`);
            }
          } else {
            addLog('error', `❌ Processing failed for ${file.filename}: ${result.message}`);
          }

          processedResults.push(result);
          setResults([...processedResults]);

        } catch (error) {
          const errorMessage = error instanceof Error ? error.message : 'Unknown error';
          addLog('error', `❌ Error processing ${file.filename}: ${errorMessage}`);
          
          // Create a failed result
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

        addLog('info', '─'.repeat(50)); // Separator
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

      // Auto-advance after a short delay
      setTimeout(() => {
        onProcessingComplete(processedResults);
      }, 2000);

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      addLog('error', `❌ Batch processing failed: ${errorMessage}`);
      onError(errorMessage);
    } finally {
      setIsProcessing(false);
    }
  };

  // Start processing when component mounts
  useEffect(() => {
    processFiles();
  }, []);

  const successful = results.filter(r => r.success).length;
  const failed = results.length - successful;
  const ragReady = results.filter(r => r.pass_all_thresholds).length;

  return (
    <div className="space-y-6">
      {/* Processing Header */}
      <div className="text-center">
        <h2 className="text-2xl font-bold text-gray-900 mb-2">
          {isProcessing ? '🔄 Processing Documents...' : '✅ Processing Complete'}
        </h2>
        <p className="text-gray-600">
          {isProcessing 
            ? `Processing ${selectedFiles.length} document(s) with ${processingOptions.auto_optimize ? 'vector optimization' : 'standard processing'}`
            : `Processed ${results.length} document(s) in ${utils.formatDuration((Date.now() - processingStartTime) / 1000)}`
          }
        </p>
      </div>

      {/* Progress Section */}
      <div className="bg-white rounded-lg border p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-medium">📊 Progress</h3>
          <span className="text-sm font-medium text-gray-600">
            {Math.round(progress)}%
          </span>
        </div>

        {/* Progress Bar */}
        <div className="w-full bg-gray-200 rounded-full h-3 mb-4">
          <div 
            className="bg-blue-600 h-3 rounded-full transition-all duration-300 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>

        {/* Current File */}
        {currentFile && (
          <div className="flex items-center space-x-2 text-sm text-gray-600">
            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>
            <span>Currently processing: <strong>{currentFile}</strong></span>
          </div>
        )}

        {/* Summary Stats */}
        {results.length > 0 && (
          <div className="grid grid-cols-3 gap-4 mt-6">
            <div className="text-center p-3 bg-green-50 rounded-lg">
              <div className="text-2xl font-bold text-green-600">{successful}</div>
              <div className="text-sm text-green-800">Successful</div>
            </div>
            <div className="text-center p-3 bg-red-50 rounded-lg">
              <div className="text-2xl font-bold text-red-600">{failed}</div>
              <div className="text-sm text-red-800">Failed</div>
            </div>
            <div className="text-center p-3 bg-blue-50 rounded-lg">
              <div className="text-2xl font-bold text-blue-600">{ragReady}</div>
              <div className="text-sm text-blue-800">RAG Ready</div>
            </div>
          </div>
        )}
      </div>

      {/* Processing Log */}
      <div className="bg-white rounded-lg border p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-medium">📋 Processing Log</h3>
          <span className="text-sm text-gray-500">Latest {logs.length} entries</span>
        </div>

        <div className="bg-gray-50 rounded-lg p-4 max-h-64 overflow-y-auto">
          {logs.length === 0 ? (
            <div className="text-center text-gray-500 py-4">
              <div className="text-2xl mb-2">📝</div>
              <p>Processing log will appear here...</p>
            </div>
          ) : (
            <div className="space-y-1 font-mono text-sm">
              {logs.map((log, index) => (
                <div key={index} className="flex items-start space-x-2">
                  <span className="text-gray-500 text-xs">{log.timestamp}</span>
                  <span>{getLogIcon(log.level)}</span>
                  <span className={`flex-1 ${
                    log.level === 'error' ? 'text-red-700' :
                    log.level === 'warning' ? 'text-yellow-700' :
                    log.level === 'success' ? 'text-green-700' :
                    'text-gray-700'
                  }`}>
                    {log.message}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Results Preview */}
      {results.length > 0 && (
        <div className="bg-white rounded-lg border p-6">
          <h3 className="text-lg font-medium mb-4">📄 Processing Results</h3>
          
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {results.map((result) => (
              <div key={result.document_id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                <div className="flex items-center space-x-3">
                  <span className="text-xl">
                    {result.success ? (result.pass_all_thresholds ? '✅' : '⚠️') : '❌'}
                  </span>
                  <div>
                    <p className="font-medium">{result.filename}</p>
                    <p className="text-sm text-gray-600">
                      Score: {result.conversion_score}/100
                      {result.vector_optimized && ' • Optimized'}
                    </p>
                  </div>
                </div>
                
                <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                  result.pass_all_thresholds 
                    ? 'bg-green-100 text-green-800'
                    : result.success
                      ? 'bg-yellow-100 text-yellow-800'
                      : 'bg-red-100 text-red-800'
                }`}>
                  {result.pass_all_thresholds ? 'RAG Ready' : result.success ? 'Needs Work' : 'Failed'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Auto-advance notice */}
      {!isProcessing && results.length > 0 && (
        <div className="text-center">
          <div className="inline-flex items-center space-x-2 px-4 py-2 bg-blue-50 text-blue-700 rounded-lg">
            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>
            <span>Proceeding to review stage...</span>
          </div>
        </div>
      )}
    </div>
  );
}
// components/stages/DownloadStage.tsx
'use client'

import { useState } from 'react';
import { ProcessingResult } from '@/types';
import { fileApi, utils } from '@/lib/api';

interface DownloadStageProps {
  processingResults: ProcessingResult[];
  onRestart: () => void;
}

export function DownloadStage({
  processingResults,
  onRestart
}: DownloadStageProps) {
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [isDownloading, setIsDownloading] = useState<string>('');
  const [isBulkDownloading, setIsBulkDownloading] = useState<boolean>(false);

  const successfulResults = processingResults.filter(r => r.success);
  const ragReadyResults = successfulResults.filter(r => r.pass_all_thresholds);
  const vectorOptimizedResults = successfulResults.filter(r => r.vector_optimized);

  const handleFileToggle = (documentId: string, checked: boolean) => {
    const newSelected = new Set(selectedFiles);
    if (checked) {
      newSelected.add(documentId);
    } else {
      newSelected.delete(documentId);
    }
    setSelectedFiles(newSelected);
  };

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedFiles(new Set(successfulResults.map(r => r.document_id)));
    } else {
      setSelectedFiles(new Set());
    }
  };

  const handleSelectRAGReady = () => {
    setSelectedFiles(new Set(ragReadyResults.map(r => r.document_id)));
  };

  const downloadIndividualFile = async (result: ProcessingResult) => {
    setIsDownloading(result.document_id);
    try {
      // The API wrapper returns the blob directly, not a Response object.
      const blob: Blob = await fileApi.downloadDocument(result.document_id);
      
      // Create download link
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${result.filename.split('.')[0]}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      
    } catch (error) {
      console.error('Download failed:', error);
      // Fixed: Handle unknown error type
      const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
      alert(`Failed to download ${result.filename}: ${errorMessage}`);
    } finally {
      setIsDownloading('');
    }
  };

  const downloadSelectedFiles = async () => {
    if (selectedFiles.size === 0) {
      alert('Please select files to download');
      return;
    }

    setIsBulkDownloading(true);
    try {
      // Fixed: Convert Set to Array for iteration
      const selectedArray = Array.from(selectedFiles);
      for (const documentId of selectedArray) {
        const result = successfulResults.find(r => r.document_id === documentId);
        if (result) {
          await downloadIndividualFile(result);
          // Add small delay between downloads
          await new Promise(resolve => setTimeout(resolve, 500));
        }
      }
    } catch (error) {
      console.error('Bulk download failed:', error);
      alert('Bulk download failed. Some files may not have been downloaded.');
    } finally {
      setIsBulkDownloading(false);
    }
  };

  const downloadRAGReadyFiles = async () => {
    if (ragReadyResults.length === 0) {
      alert('No RAG-ready files available');
      return;
    }

    setIsBulkDownloading(true);
    try {
      for (const result of ragReadyResults) {
        await downloadIndividualFile(result);
        // Add small delay between downloads
        await new Promise(resolve => setTimeout(resolve, 500));
      }
    } catch (error) {
      console.error('RAG-ready download failed:', error);
      alert('RAG-ready download failed. Some files may not have been downloaded.');
    } finally {
      setIsBulkDownloading(false);
    }
  };

  const generateSummaryReport = () => {
    const timestamp = new Date().toISOString().split('T')[0];
    const passRate = successfulResults.length > 0 ? (ragReadyResults.length / successfulResults.length * 100).toFixed(1) : '0';
    
    const reportLines = [
      '# Curatore Processing Summary Report',
      `Generated: ${new Date().toLocaleString()}`,
      '',
      '## Overview',
      `- Total Files Processed: ${processingResults.length}`,
      `- Successfully Processed: ${successfulResults.length}`,
      `- RAG Ready Files: ${ragReadyResults.length}`,
      `- Vector Optimized Files: ${vectorOptimizedResults.length}`,
      `- Pass Rate: ${passRate}%`,
      '',
      '## Processing Results',
      '',
    ];

    successfulResults.forEach(result => {
      const status = result.pass_all_thresholds ? 'RAG Ready ✅' : 'Needs Improvement ⚠️';
      const optimization = result.vector_optimized ? 'Vector Optimized 🎯' : 'Standard Processing';
      
      reportLines.push(`### ${result.filename}`);
      reportLines.push(`- **Status:** ${status}`);
      reportLines.push(`- **Processing:** ${optimization}`);
      reportLines.push(`- **Conversion Score:** ${result.conversion_score}/100`);
      
      if (result.llm_evaluation) {
        reportLines.push(`- **Quality Scores:**`);
        reportLines.push(`  - Clarity: ${result.llm_evaluation.clarity_score || 'N/A'}/10`);
        reportLines.push(`  - Completeness: ${result.llm_evaluation.completeness_score || 'N/A'}/10`);
        reportLines.push(`  - Relevance: ${result.llm_evaluation.relevance_score || 'N/A'}/10`);
        reportLines.push(`  - Markdown: ${result.llm_evaluation.markdown_score || 'N/A'}/10`);
      }
      
      if (result.document_summary) {
        reportLines.push(`- **Summary:** ${result.document_summary}`);
      }
      reportLines.push('');
    });

    const reportContent = reportLines.join('\n');
    const blob = new Blob([reportContent], { type: 'text/markdown' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `curatore_summary_${timestamp}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  };

  const allSelected = successfulResults.length > 0 && selectedFiles.size === successfulResults.length;
  const someSelected = selectedFiles.size > 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="text-center">
        <h2 className="text-2xl font-bold text-gray-900 mb-2">⬇️ Download Results</h2>
        <p className="text-gray-600">
          Download your processed documents and reports
        </p>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-blue-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-blue-600">{successfulResults.length}</div>
          <div className="text-sm text-blue-800">Total Files</div>
        </div>
        <div className="bg-green-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-green-600">{ragReadyResults.length}</div>
          <div className="text-sm text-green-800">RAG Ready</div>
        </div>
        <div className="bg-purple-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-purple-600">{vectorOptimizedResults.length}</div>
          <div className="text-sm text-purple-800">Optimized</div>
        </div>
        <div className="bg-yellow-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-yellow-600">{selectedFiles.size}</div>
          <div className="text-sm text-yellow-800">Selected</div>
        </div>
      </div>

      {/* Download Options */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Individual Downloads */}
        <div className="bg-white rounded-lg border p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium">📄 Individual Downloads</h3>
            <div className="flex items-center space-x-2">
              <label className="flex items-center space-x-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) => handleSelectAll(e.target.checked)}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm text-gray-600">Select All</span>
              </label>
            </div>
          </div>

          <div className="space-y-2 max-h-64 overflow-y-auto">
            {successfulResults.map((result) => {
              const isSelected = selectedFiles.has(result.document_id);
              const isDownloadingThis = isDownloading === result.document_id;

              return (
                <div key={result.document_id} className="flex items-center justify-between p-3 border rounded-lg hover:bg-gray-50">
                  <div className="flex items-center space-x-3 flex-1">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={(e) => handleFileToggle(result.document_id, e.target.checked)}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <div className="flex-1">
                      <div className="flex items-center space-x-2">
                        <span className="font-medium text-gray-900">{result.filename}</span>
                        {result.pass_all_thresholds && <span className="text-green-600">✅</span>}
                        {result.vector_optimized && <span className="text-purple-600">🎯</span>}
                      </div>
                      <div className="text-sm text-gray-500">
                        Score: {result.conversion_score}% • 
                        {result.processing_time && ` ${utils.formatDuration(result.processing_time)}`}
                      </div>
                    </div>
                  </div>
                  
                  <button
                    type="button"
                    onClick={() => downloadIndividualFile(result)}
                    disabled={isDownloadingThis}
                    className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                  >
                    {isDownloadingThis ? (
                      <div className="flex items-center space-x-1">
                        <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-white"></div>
                        <span>...</span>
                      </div>
                    ) : (
                      '💾'
                    )}
                  </button>
                </div>
              );
            })}
          </div>

          {successfulResults.length === 0 && (
            <div className="text-center py-8 text-gray-500">
              <div className="text-4xl mb-2">📭</div>
              <p>No successful files available for download</p>
            </div>
          )}
        </div>

        {/* Bulk Downloads */}
        <div className="bg-white rounded-lg border p-6">
          <h3 className="text-lg font-medium mb-4">📦 Bulk Downloads</h3>
          
          <div className="space-y-3">
            {/* Download Selected */}
            <button
              type="button"
              onClick={downloadSelectedFiles}
              disabled={!someSelected || isBulkDownloading}
              className="w-full px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
            >
              {isBulkDownloading ? (
                <div className="flex items-center justify-center space-x-2">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                  <span>Downloading...</span>
                </div>
              ) : (
                `📦 Download Selected (${selectedFiles.size})`
              )}
            </button>

            {/* Download RAG Ready */}
            <button
              type="button"
              onClick={downloadRAGReadyFiles}
              disabled={ragReadyResults.length === 0 || isBulkDownloading}
              className="w-full px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
            >
              🎯 Download RAG-Ready Only ({ragReadyResults.length})
            </button>

            {/* Quick Select RAG Ready */}
            {ragReadyResults.length > 0 && (
              <button
                type="button"
                onClick={handleSelectRAGReady}
                className="w-full px-4 py-2 bg-green-100 text-green-700 rounded-lg hover:bg-green-200 font-medium"
              >
                ✨ Select All RAG-Ready Files
              </button>
            )}

            {/* Download Summary Report */}
            <button
              type="button"
              onClick={generateSummaryReport}
              className="w-full px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 font-medium"
            >
              📊 Download Summary Report
            </button>
          </div>

          {/* Processing Statistics */}
          <div className="mt-6 pt-4 border-t">
            <h4 className="font-medium mb-2">📈 Final Statistics</h4>
            <div className="text-sm space-y-1">
              {ragReadyResults.length === successfulResults.length && successfulResults.length > 0 ? (
                <div className="text-green-600 font-medium">🎉 All files are RAG-ready!</div>
              ) : ragReadyResults.length > 0 ? (
                <div className="text-blue-600">
                  ✅ {ragReadyResults.length}/{successfulResults.length} files are RAG-ready
                </div>
              ) : (
                <div className="text-yellow-600">⚠️ No files meet all quality thresholds</div>
              )}
              
              {vectorOptimizedResults.length > 0 && (
                <div className="text-purple-600">
                  🔧 {vectorOptimizedResults.length} files were vector optimized
                </div>
              )}
              
              <div className="text-gray-600">
                📊 Average score: {successfulResults.length > 0 
                  ? Math.round(successfulResults.reduce((sum, r) => sum + r.conversion_score, 0) / successfulResults.length)
                  : 0
                }/100
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex justify-center space-x-4 pt-6 border-t">
        <button
          type="button"
          onClick={onRestart}
          className="px-6 py-3 bg-gray-600 text-white rounded-lg hover:bg-gray-700 font-medium"
        >
          🔄 Start Over
        </button>
        
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
        >
          🏠 New Session
        </button>
      </div>

      {/* Help Text */}
      <div className="text-center text-sm text-gray-500">
        <p>💡 Tip: RAG-ready files have passed all quality thresholds and are optimized for vector databases</p>
      </div>
    </div>
  );
}
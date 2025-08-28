// components/stages/DownloadStage.tsx
'use client'

import { useState } from 'react';
import { ProcessingResult } from '@/types';
import { fileApi, utils } from '@/lib/api';
import toast from 'react-hot-toast';

interface DownloadStageProps {
  processingResults: ProcessingResult[];
  onRestart: () => void;
  processingPanelState?: 'hidden' | 'minimized' | 'normal' | 'fullscreen';
}

export function DownloadStage({
  processingResults,
  onRestart,
  processingPanelState = 'hidden'
}: DownloadStageProps) {
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [isDownloading, setIsDownloading] = useState<string>('');
  const [isBulkDownloading, setIsBulkDownloading] = useState<boolean>(false);
  const [isCombinedDownloading, setIsCombinedDownloading] = useState<boolean>(false);
  const [isRAGDownloading, setIsRAGDownloading] = useState<boolean>(false);

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

  const downloadIndividualFile = async (result: ProcessingResult) => {
    setIsDownloading(result.document_id);
    try {
      const blob: Blob = await fileApi.downloadDocument(result.document_id);
      const filename = `${result.filename.split('.')[0]}.md`;
      utils.downloadBlob(blob, filename);
      toast.success(`Downloaded ${filename}`, { icon: '💾' });
    } catch (error) {
      console.error('Download failed:', error);
      const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
      toast.error(`Failed to download ${result.filename}: ${errorMessage}`);
    } finally {
      setIsDownloading('');
    }
  };

  const downloadSelectedFiles = async () => {
    if (selectedFiles.size === 0) {
      toast.error('Please select files to download');
      return;
    }

    setIsBulkDownloading(true);
    const loadingToast = toast.loading(`Creating ZIP archive with ${selectedFiles.size} files...`);
    
    try {
      const selectedArray = Array.from(selectedFiles);
      const timestamp = utils.generateTimestamp();
      const zipName = `curatore_selected_${timestamp}.zip`;
      
      const blob = await fileApi.downloadBulkDocuments(selectedArray, 'individual', zipName);
      utils.downloadBlob(blob, zipName);
      
      toast.success(`Downloaded ${selectedFiles.size} files as ZIP archive`, { 
        id: loadingToast,
        icon: '📦'
      });
    } catch (error) {
      console.error('Bulk download failed:', error);
      const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
      toast.error(`Bulk download failed: ${errorMessage}`, { id: loadingToast });
    } finally {
      setIsBulkDownloading(false);
    }
  };

  const downloadRAGReadyFiles = async () => {
    if (ragReadyResults.length === 0) {
      toast.error('No RAG-ready files available');
      return;
    }

    setIsRAGDownloading(true);
    const loadingToast = toast.loading(`Creating ZIP archive with ${ragReadyResults.length} RAG-ready files...`);
    
    try {
      const timestamp = utils.generateTimestamp();
      const zipName = `curatore_rag_ready_${timestamp}.zip`;
      
      const blob = await fileApi.downloadRAGReadyDocuments(zipName);
      utils.downloadBlob(blob, zipName);
      
      toast.success(`Downloaded ${ragReadyResults.length} RAG-ready files as ZIP archive`, { 
        id: loadingToast,
        icon: '🎯'
      });
    } catch (error) {
      console.error('RAG-ready download failed:', error);
      const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
      toast.error(`RAG-ready download failed: ${errorMessage}`, { id: loadingToast });
    } finally {
      setIsRAGDownloading(false);
    }
  };

  const downloadCombinedArchive = async () => {
    if (successfulResults.length === 0) {
      toast.error('No processed files available');
      return;
    }

    setIsCombinedDownloading(true);
    const loadingToast = toast.loading(`Creating complete archive with ${successfulResults.length} files...`);
    
    try {
      const allIds = successfulResults.map(r => r.document_id);
      const timestamp = utils.generateTimestamp();
      const zipName = `curatore_complete_${timestamp}.zip`;
      
      const blob = await fileApi.downloadBulkDocuments(allIds, 'combined', zipName);
      utils.downloadBlob(blob, zipName);
      
      toast.success('Downloaded complete archive with summary', { 
        id: loadingToast,
        icon: '📁'
      });
    } catch (error) {
      console.error('Combined archive download failed:', error);
      const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
      toast.error(`Combined archive download failed: ${errorMessage}`, { id: loadingToast });
    } finally {
      setIsCombinedDownloading(false);
    }
  };

  const downloadProcessingSummary = () => {
    if (successfulResults.length === 0) {
      toast.error('No processing data available for summary');
      return;
    }

    const timestamp = utils.generateTimestamp();
    const reportLines = [
      '# Curatore Processing Summary',
      `Generated: ${new Date().toISOString()}`,
      '',
      '## Overview',
      `- Total Files Processed: ${successfulResults.length}`,
      `- RAG-Ready Files: ${ragReadyResults.length}`,
      `- Vector Optimized Files: ${vectorOptimizedResults.length}`,
      `- Selected for Download: ${selectedFiles.size}`,
      '',
      '## Individual File Results',
      ''
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
    const filename = `curatore_summary_${timestamp}.md`;
    utils.downloadBlob(blob, filename);
    toast.success(`Downloaded summary report: ${filename}`, { icon: '📊' });
  };

  // Helper function to format processing time as seconds only (no decimals)
  const formatProcessingTimeSeconds = (timeInSeconds: number): string => {
    if (!timeInSeconds) return 'N/A';
    const seconds = Math.round(timeInSeconds); // Round to nearest whole second
    return `${seconds}s`;
  };

  const allSelected = successfulResults.length > 0 && selectedFiles.size === successfulResults.length;
  const someSelected = selectedFiles.size > 0;
  const isAnyDownloading = isBulkDownloading || isCombinedDownloading || isRAGDownloading;

  return (
    <div className="space-y-6 pb-24">
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
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Individual Downloads - Now takes 3/4 of the width */}
        <div className="lg:col-span-3 bg-white rounded-lg border p-6">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center space-x-4">
              <h3 className="text-lg font-semibold text-gray-900">📄 Individual Downloads</h3>
              <span className="px-3 py-1 bg-gray-100 text-gray-700 text-sm font-medium rounded-full">
                {successfulResults.length} files
              </span>
            </div>
            <div className="flex items-center space-x-3">
              <label className="flex items-center space-x-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) => handleSelectAll(e.target.checked)}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm font-medium text-gray-700">Select All</span>
              </label>
            </div>
          </div>

          {successfulResults.length === 0 ? (
            <div className="text-center py-12 text-gray-500 border-2 border-dashed border-gray-200 rounded-xl">
              <div className="text-6xl mb-4">📭</div>
              <p className="text-xl font-medium mb-2">No successful files available</p>
              <p className="text-sm">Complete document processing to see downloadable files here</p>
            </div>
          ) : (
            <div className="border border-gray-200 rounded-lg overflow-hidden">
              {/* Table Header - Updated column distribution */}
              <div className="bg-gray-50 border-b border-gray-200 px-6 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wider">
                <div className="grid grid-cols-12 gap-4 items-center">
                  <div className="col-span-1">Select</div>
                  <div className="col-span-5">File Name</div>
                  <div className="col-span-2">Status</div>
                  <div className="col-span-2">Quality Score</div>
                  <div className="col-span-1">Time</div>
                  <div className="col-span-1">Download</div>
                </div>
              </div>

              {/* Table Body */}
              <div className="divide-y divide-gray-200 max-h-96 overflow-y-auto">
                {successfulResults.map((result) => {
                  const isSelected = selectedFiles.has(result.document_id);
                  const isDownloadingThis = isDownloading === result.document_id;

                  return (
                    <div 
                      key={result.document_id} 
                      className={`px-6 py-4 hover:bg-gray-50 transition-colors ${
                        isSelected ? 'bg-blue-50 border-blue-200' : ''
                      }`}
                    >
                      <div className="grid grid-cols-12 gap-4 items-center">
                        {/* Select Checkbox */}
                        <div className="col-span-1">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={(e) => handleFileToggle(result.document_id, e.target.checked)}
                            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                            disabled={isAnyDownloading}
                          />
                        </div>

                        {/* File Name - Increased from col-span-4 to col-span-5 */}
                        <div className="col-span-5">
                          <div className="flex items-center space-x-2">
                            <span className="text-gray-400">
                              {result.vector_optimized ? '🎯' : '📄'}
                            </span>
                            <div className="min-w-0 flex-1">
                              <p className="text-sm font-medium text-gray-900 truncate" title={result.filename}>
                                {result.filename}
                              </p>
                              {result.document_summary && (
                                <p className="text-xs text-gray-500 truncate mt-1" title={result.document_summary}>
                                  {result.document_summary}
                                </p>
                              )}
                            </div>
                          </div>
                        </div>

                        {/* Status */}
                        <div className="col-span-2">
                          <div className="flex items-center space-x-2">
                            {result.pass_all_thresholds ? (
                              <div className="flex items-center space-x-1">
                                <span className="w-2 h-2 bg-green-500 rounded-full"></span>
                                <span className="text-xs font-medium text-green-700">RAG Ready</span>
                              </div>
                            ) : (
                              <div className="flex items-center space-x-1">
                                <span className="w-2 h-2 bg-yellow-500 rounded-full"></span>
                                <span className="text-xs font-medium text-yellow-700">Needs Review</span>
                              </div>
                            )}
                          </div>
                        </div>

                        {/* Quality Score */}
                        <div className="col-span-2">
                          <div className="flex items-center space-x-2">
                            <div className="flex-1 bg-gray-200 rounded-full h-2">
                              <div 
                                className={`h-2 rounded-full transition-all ${
                                  result.conversion_score >= 85 ? 'bg-green-500' :
                                  result.conversion_score >= 70 ? 'bg-yellow-500' :
                                  'bg-red-500'
                                }`}
                                style={{ width: `${result.conversion_score}%` }}
                              />
                            </div>
                            <span className="text-xs font-mono text-gray-600 w-8">
                              {result.conversion_score}%
                            </span>
                          </div>
                          {result.llm_evaluation && (
                            <div className="flex items-center space-x-1 mt-1 text-xs text-gray-500">
                              <span>📊 {result.llm_evaluation.clarity_score || 'N/A'}</span>
                              <span>•</span>
                              <span>📋 {result.llm_evaluation.completeness_score || 'N/A'}</span>
                              <span>•</span>
                              <span>🎯 {result.llm_evaluation.relevance_score || 'N/A'}</span>
                              <span>•</span>
                              <span>📝 {result.llm_evaluation.markdown_score || 'N/A'}</span>
                            </div>
                          )}
                        </div>

                        {/* Processing Time - Reduced from col-span-2 to col-span-1 */}
                        <div className="col-span-1">
                          <div className="text-gray-600">
                            {result.processing_time ? (
                              <div className="flex items-center justify-center">
                                <span className="font-mono text-xs">
                                  {formatProcessingTimeSeconds(result.processing_time)}
                                </span>
                              </div>
                            ) : (
                              <span className="text-gray-400 text-xs">N/A</span>
                            )}
                          </div>
                        </div>

                        {/* Download Button */}
                        <div className="col-span-1">
                          <button
                            type="button"
                            onClick={() => downloadIndividualFile(result)}
                            disabled={isDownloadingThis || isAnyDownloading}
                            className="w-8 h-8 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center transition-colors"
                            title="Download processed file"
                          >
                            {isDownloadingThis ? (
                              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                            ) : (
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                              </svg>
                            )}
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Bulk Download Options - Takes remaining 1/4 of the width */}
        <div className="lg:col-span-1 space-y-6">
          {/* Selected Files Download */}
          <div className="bg-white rounded-lg border p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
              <span className="mr-2">📦</span>
              Bulk Downloads
            </h3>

            <div className="space-y-3">
              {/* Selected Files */}
              <button
                type="button"
                onClick={downloadSelectedFiles}
                disabled={selectedFiles.size === 0 || isBulkDownloading || isAnyDownloading}
                className="w-full bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2 transition-colors"
              >
                {isBulkDownloading ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                    <span>Downloading...</span>
                  </>
                ) : (
                  <>
                    <span>📋</span>
                    <span>Selected ({selectedFiles.size})</span>
                  </>
                )}
              </button>

              {/* Combined Archive */}
              <button
                type="button"
                onClick={downloadCombinedArchive}
                disabled={successfulResults.length === 0 || isCombinedDownloading || isAnyDownloading}
                className="w-full bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2 transition-colors"
              >
                {isCombinedDownloading ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                    <span>Creating...</span>
                  </>
                ) : (
                  <>
                    <span>📁</span>
                    <span>Complete Archive</span>
                  </>
                )}
              </button>

              {/* RAG-Ready Files */}
              <button
                type="button"
                onClick={downloadRAGReadyFiles}
                disabled={ragReadyResults.length === 0 || isRAGDownloading || isAnyDownloading}
                className="w-full bg-purple-600 text-white px-4 py-2 rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2 transition-colors"
              >
                {isRAGDownloading ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                    <span>Preparing...</span>
                  </>
                ) : (
                  <>
                    <span>🎯</span>
                    <span>RAG-Ready ({ragReadyResults.length})</span>
                  </>
                )}
              </button>

              {/* Processing Summary */}
              <button
                type="button"
                onClick={downloadProcessingSummary}
                disabled={successfulResults.length === 0 || isAnyDownloading}
                className="w-full bg-gray-600 text-white px-4 py-2 rounded-lg hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2 transition-colors"
              >
                <span>📊</span>
                <span>Summary Report</span>
              </button>
            </div>

            {/* Help Text */}
            <div className="mt-4 pt-4 border-t border-gray-200">
              <p className="text-xs text-gray-500 text-center">
                Select files above, then choose a download option
              </p>
            </div>
          </div>

          {/* Download Info */}
          <div className="bg-blue-50 rounded-lg p-4">
            <h4 className="font-medium text-blue-900 mb-2">💡 Download Types</h4>
            <div className="space-y-2 text-xs text-blue-800">
              <div><strong>Selected:</strong> Custom file selection</div>
              <div><strong>Complete:</strong> All files + merged + summary</div>
              <div><strong>RAG-Ready:</strong> Quality-filtered files</div>
              <div><strong>Summary:</strong> Processing report</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
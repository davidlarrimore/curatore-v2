// components/stages/DownloadStage.tsx
'use client'

import { useState } from 'react';
import { ProcessingResult } from '@/types';
import { fileApi, utils } from '@/lib/api';

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

    setIsRAGDownloading(true);
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
      setIsRAGDownloading(false);
    }
  };

  // NEW: Function to adjust markdown hierarchy
  const adjustMarkdownHierarchy = (content: string): string => {
    if (!content) return content;
    
    // Split content into lines
    const lines = content.split('\n');
    const adjustedLines: string[] = [];
    
    for (const line of lines) {
      // Check if line starts with markdown headers
      const headerMatch = line.match(/^(#{1,6})\s+(.*)$/);
      if (headerMatch) {
        const headerLevel = headerMatch[1]; // The # symbols
        const headerText = headerMatch[2]; // The text after #
        
        // Add one more # to increase the nesting level (shift everything down one level)
        // But cap at maximum of 6 levels (######)
        const newLevel = headerLevel.length < 6 ? '#' + headerLevel : headerLevel;
        adjustedLines.push(`${newLevel} ${headerText}`);
      } else {
        adjustedLines.push(line);
      }
    }
    
    return adjustedLines.join('\n');
  };

  // NEW: Function to download all files in a single markdown file
  const downloadCombinedMarkdown = async () => {
    if (successfulResults.length === 0) {
      alert('No processed files available for combined download');
      return;
    }

    setIsCombinedDownloading(true);
    
    // Add a small delay to ensure the UI updates before starting the heavy work
    await new Promise(resolve => setTimeout(resolve, 50));
    
    try {
      const combinedSections: string[] = [];
      
      // Add main title and summary
      const timestamp = new Date().toLocaleString();
      const passRate = successfulResults.length > 0 ? (ragReadyResults.length / successfulResults.length * 100).toFixed(1) : '0';
      
      combinedSections.push(`# Curatore Processing Results - Combined Export`);
      combinedSections.push(`*Generated on ${timestamp}*`);
      combinedSections.push(``);
      combinedSections.push(`**Processing Summary:**`);
      combinedSections.push(`- Total Files: ${successfulResults.length}`);
      combinedSections.push(`- RAG Ready: ${ragReadyResults.length} (${passRate}%)`);
      combinedSections.push(`- Vector Optimized: ${vectorOptimizedResults.length}`);
      combinedSections.push(``);
      combinedSections.push(`---`);
      combinedSections.push(``);

      // Process each successful result with proper async handling
      for (let i = 0; i < successfulResults.length; i++) {
        const result = successfulResults[i];
        
        // Add a small delay between requests to prevent overwhelming the browser
        if (i > 0) {
          await new Promise(resolve => setTimeout(resolve, 100));
        }
        
        try {
          // Use the API endpoint correctly
          const response = await fetch(`http://localhost:8000/api/documents/${result.document_id}/content`);
          if (!response.ok) {
            throw new Error(`Failed to fetch content: ${response.statusText}`);
          }
          const data = await response.json();
          const content = data.content || '';

          // Create section header with filename and summary
          combinedSections.push(`# ${result.filename}`);
          
          if (result.document_summary) {
            combinedSections.push(``);
            combinedSections.push(`*${result.document_summary}*`);
          }

          // Add processing metadata
          const statusEmoji = result.pass_all_thresholds ? '✅' : '⚠️';
          const optimizedEmoji = result.vector_optimized ? ' 🎯' : '';
          combinedSections.push(``);
          combinedSections.push(`**Processing Status:** ${statusEmoji} ${result.pass_all_thresholds ? 'RAG Ready' : 'Needs Improvement'}${optimizedEmoji}`);
          combinedSections.push(`**Conversion Score:** ${result.conversion_score}/100`);
          
          if (result.llm_evaluation) {
            const scores = [
              `Clarity: ${result.llm_evaluation.clarity_score || 'N/A'}/10`,
              `Completeness: ${result.llm_evaluation.completeness_score || 'N/A'}/10`,
              `Relevance: ${result.llm_evaluation.relevance_score || 'N/A'}/10`,
              `Markdown: ${result.llm_evaluation.markdown_score || 'N/A'}/10`
            ].join(', ');
            combinedSections.push(`**Quality Scores:** ${scores}`);
          }

          combinedSections.push(``);
          combinedSections.push(`---`);
          combinedSections.push(``);

          // Adjust the markdown hierarchy and add the content
          const adjustedContent = adjustMarkdownHierarchy(content);
          combinedSections.push(adjustedContent);
          
          // Add separator between documents
          combinedSections.push(``);
          combinedSections.push(``);
          combinedSections.push(`---`);
          combinedSections.push(``);
          
        } catch (error) {
          console.error(`Failed to fetch content for ${result.filename}:`, error);
          // Add error note for this document
          combinedSections.push(`# ${result.filename}`);
          combinedSections.push(``);
          combinedSections.push(`*Error: Could not load content for this document*`);
          combinedSections.push(``);
          combinedSections.push(`---`);
          combinedSections.push(``);
        }
      }

      // Create and download the combined file
      const combinedContent = combinedSections.join('\n');
      const blob = new Blob([combinedContent], { type: 'text/markdown' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `curatore_combined_export_${new Date().toISOString().split('T')[0]}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

    } catch (error) {
      console.error('Combined download failed:', error);
      alert('Failed to create combined markdown file. Please try downloading files individually.');
    } finally {
      setIsCombinedDownloading(false);
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
              {/* Table Header */}
              <div className="bg-gray-50 border-b border-gray-200 px-6 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wider">
                <div className="grid grid-cols-12 gap-4 items-center">
                  <div className="col-span-1">Select</div>
                  <div className="col-span-4">File Name</div>
                  <div className="col-span-2">Status</div>
                  <div className="col-span-2">Quality Score</div>
                  <div className="col-span-2">Processing Time</div>
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
                        isSelected ? 'bg-blue-50 border-l-4 border-blue-500' : ''
                      }`}
                    >
                      <div className="grid grid-cols-12 gap-4 items-center text-sm">
                        {/* Checkbox */}
                        <div className="col-span-1">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={(e) => handleFileToggle(result.document_id, e.target.checked)}
                            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 focus:ring-offset-0"
                          />
                        </div>

                        {/* File Name */}
                        <div className="col-span-4">
                          <div className="min-w-0">
                            <p className="font-medium text-gray-900 truncate" title={result.filename}>
                              {result.filename}
                            </p>
                            {result.document_summary && (
                              <p className="text-xs text-gray-500 truncate mt-1" title={result.document_summary}>
                                {result.document_summary}
                              </p>
                            )}
                          </div>
                        </div>

                        {/* Status */}
                        <div className="col-span-2">
                          <div className="flex items-center space-x-2">
                            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                              result.pass_all_thresholds
                                ? 'bg-green-100 text-green-800'
                                : 'bg-yellow-100 text-yellow-800'
                            }`}>
                              {result.pass_all_thresholds ? '✅ RAG Ready' : '⚠️ Needs Work'}
                            </span>
                            {result.vector_optimized && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-800">
                                🎯 Optimized
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Quality Score */}
                        <div className="col-span-2">
                          <div className="flex items-center space-x-2">
                            <div className="flex-1 bg-gray-200 rounded-full h-2">
                              <div 
                                className={`h-2 rounded-full transition-all duration-300 ${
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

                        {/* Processing Time - UPDATED: Show only seconds */}
                        <div className="col-span-2">
                          <div className="text-gray-600">
                            {result.processing_time ? (
                              <div className="flex items-center space-x-1">
                                <span className="text-gray-400">⏱️</span>
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
                              <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-white"></div>
                            ) : (
                              <span className="text-xs">💾</span>
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

        {/* Bulk Downloads - Now takes 1/4 of the width */}
        <div className="lg:col-span-1 bg-white rounded-lg border p-4">
          <h3 className="text-lg font-medium mb-3">📦 Bulk Downloads</h3>
          
          <div className="space-y-3">
            {/* NEW: Download Combined Markdown */}
            <button
              type="button"
              onClick={downloadCombinedMarkdown}
              disabled={successfulResults.length === 0 || isAnyDownloading}
              className="w-full px-4 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
            >
              {isCombinedDownloading ? (
                <div className="flex items-center justify-center space-x-2">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                  <span>Creating Combined File...</span>
                </div>
              ) : (
                `📋 Download Combined Markdown (${successfulResults.length} files)`
              )}
            </button>

            {/* Download Selected */}
            <button
              type="button"
              onClick={downloadSelectedFiles}
              disabled={!someSelected || isAnyDownloading}
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
              disabled={ragReadyResults.length === 0 || isAnyDownloading}
              className="w-full px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
            >
              {isRAGDownloading ? (
                <div className="flex items-center justify-center space-x-2">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                  <span>Downloading...</span>
                </div>
              ) : (
                `🎯 Download RAG-Ready Only (${ragReadyResults.length})`
              )}
            </button>

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
          <div className="mt-4 pt-3 border-t">
            <h4 className="font-medium mb-2 text-sm">📈 Statistics</h4>
            <div className="text-xs space-y-1">
              {ragReadyResults.length === successfulResults.length && successfulResults.length > 0 ? (
                <div className="text-green-600 font-medium">🎉 All RAG-ready!</div>
              ) : ragReadyResults.length > 0 ? (
                <div className="text-blue-600">
                  ✅ {ragReadyResults.length}/{successfulResults.length} RAG-ready
                </div>
              ) : (
                <div className="text-yellow-600">⚠️ No files meet thresholds</div>
              )}
              
              {vectorOptimizedResults.length > 0 && (
                <div className="text-purple-600">
                  🔧 {vectorOptimizedResults.length} optimized
                </div>
              )}
              
              <div className="text-gray-600">
                📊 Avg: {successfulResults.length > 0 
                  ? Math.round(successfulResults.reduce((sum, r) => sum + r.conversion_score, 0) / successfulResults.length)
                  : 0
                }/100
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Help Text */}
      <div className="text-center text-sm text-gray-500">
        <p>💡 Tip: The combined markdown file automatically adjusts header levels and includes file summaries</p>
      </div>

      {/* Fixed Action Button - Bottom Right with Processing Panel Awareness - UPDATED: Single button */}
      {processingPanelState !== 'fullscreen' && (
        <div className={`fixed right-6 z-40 transition-all duration-300 ${
          processingPanelState === 'normal' 
            ? 'bottom-[384px]'  // Above normal processing panel: 320px panel + 52px (status + gap) + 12px margin = 384px
            : processingPanelState === 'minimized'
            ? 'bottom-[112px]'  // Above minimized panel: 48px panel + 52px (status + gap) + 12px margin = 112px
            : 'bottom-16'       // Above status bar only: 52px (status + gap) + 12px margin = 64px (bottom-16)
        }`}>
          <button
            type="button"
            onClick={onRestart}
            className="px-6 py-3 bg-blue-600 text-white rounded-full hover:bg-blue-700 font-medium text-sm transition-all shadow-lg hover:shadow-xl hover:-translate-y-1"
          >
            🔄 Process New Documents
          </button>
        </div>
      )}
    </div>
  );
}
// components/stages/ReviewStage.tsx
'use client'

import { useState, useEffect } from 'react';
import toast from 'react-hot-toast';
import { ProcessingResult, QualityThresholds } from '@/types';
import { contentApi, jobsApi } from '@/lib/api';

interface ReviewStageProps {
  processingResults: ProcessingResult[];
  onResultsUpdate: (results: ProcessingResult[]) => void;
  onComplete: () => void;
  qualityThresholds: QualityThresholds;
  isProcessingComplete: boolean;
  isProcessing: boolean;
  selectedFiles: any[];
  processingPanelState?: 'hidden' | 'minimized' | 'normal' | 'fullscreen';
}

type TabType = 'quality' | 'editor';

export function ReviewStage({
  processingResults,
  onResultsUpdate,
  onComplete,
  qualityThresholds,
  isProcessingComplete,
  isProcessing,
  selectedFiles,
  processingPanelState = 'hidden'
}: ReviewStageProps) {
  const [selectedResult, setSelectedResult] = useState<ProcessingResult | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>('quality');
  const [documentContent, setDocumentContent] = useState<string>('');
  const [editedContent, setEditedContent] = useState<string>('');
  const [customPrompt, setCustomPrompt] = useState<string>('Improve clarity, structure, and formatting. Add helpful headings and organize content better.');
  const [showCustomPrompt, setShowCustomPrompt] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isEditing, setIsEditing] = useState<boolean>(false);

  // Load document content when result is selected
  useEffect(() => {
    if (selectedResult && activeTab === 'editor') {
      loadDocumentContent(selectedResult.document_id);
    }
  }, [selectedResult, activeTab]);

  // Auto-select first result when processing completes OR when first result becomes available
  useEffect(() => {
    if (processingResults.length > 0 && !selectedResult) {
      setSelectedResult(processingResults[0]);
    }
  }, [processingResults, selectedResult]);

  const loadDocumentContent = async (documentId: string) => {
    setIsLoading(true);
    try {
      const response = await contentApi.getDocumentContent(documentId);
      setDocumentContent(response.content);
      setEditedContent(response.content);
    } catch (error) {
      console.error('Failed to load document content:', error);
      setDocumentContent('Failed to load content');
      setEditedContent('');
      toast.error('Failed to load document content');
    } finally {
      setIsLoading(false);
    }
  };

  const pollJobUntilDone = async (jobId: string) => {
    const interval = parseInt(process.env.NEXT_PUBLIC_JOB_POLL_INTERVAL_MS || '2500', 10);
    // eslint-disable-next-line no-constant-condition
    while (true) {
      try {
        const status = await jobsApi.getJob(jobId);
        const st = (status.status || '').toUpperCase();
        if (st === 'SUCCESS') return status.result as ProcessingResult;
        if (st === 'FAILURE') throw new Error(status.error || 'Update failed');
      } catch (e) {
        throw e as Error;
      }
      await new Promise(res => setTimeout(res, interval));
    }
  };

  // Attempt to enqueue a content update. If a 409 occurs, wait for the active job
  // on this document to finish, then retry once automatically.
  const enqueueUpdateWithAutoRetry = async (
    documentId: string,
    content: string,
    improvementPrompt?: string,
    applyVectorOptimization: boolean = false
  ): Promise<ProcessingResult> => {
    try {
      const resp = await contentApi.updateDocumentContent(documentId, content, improvementPrompt, applyVectorOptimization);
      return await pollJobUntilDone(resp.job_id);
    } catch (error: any) {
      if (error?.status === 409) {
        // Inform user and wait for current job to finish
        toast('Another operation is running. Will retry when it completes…', { icon: '⏳' });
        try {
          const current = await jobsApi.getJobByDocument(documentId);
          if (current?.job_id) {
            await pollJobUntilDone(current.job_id);
          }
        } catch {
          // ignore lookup errors; proceed to retry
        }
        // Retry enqueue once
        const retry = await contentApi.updateDocumentContent(documentId, content, improvementPrompt, applyVectorOptimization);
        return await pollJobUntilDone(retry.job_id);
      }
      throw error;
    }
  };

  const handleSaveAndRescore = async () => {
    if (!selectedResult) return;

    setIsEditing(true);
    const loadingToast = toast.loading('Saving and re-scoring document (queued)...');
    
    try {
      const updatedResult = await enqueueUpdateWithAutoRetry(
        selectedResult.document_id,
        editedContent
      );

      // Update the result in the list
      const updatedResults = processingResults.map(r =>
        r.document_id === selectedResult.document_id ? updatedResult : r
      );
      onResultsUpdate(updatedResults);
      setSelectedResult(updatedResult);
      
      toast.success('Document saved and re-scored successfully!', { id: loadingToast });

    } catch (error: any) {
      console.error('Failed to save and re-score:', error);
      if (error?.status === 409) {
        toast.error('Another operation is already running for this document. Please retry after it completes.', { id: loadingToast });
      } else {
        toast.error('Failed to save and re-score document', { id: loadingToast });
      }
    } finally {
      setIsEditing(false);
    }
  };

  const handleVectorOptimize = async () => {
    if (!selectedResult) return;

    setIsEditing(true);
    const loadingToast = toast.loading('Applying vector optimization (queued)...');
    
    try {
      const updatedResult = await enqueueUpdateWithAutoRetry(
        selectedResult.document_id,
        editedContent,
        undefined,
        true // apply vector optimization
      );

      // Update the result in the list
      const updatedResults = processingResults.map(r =>
        r.document_id === selectedResult.document_id ? updatedResult : r
      );
      onResultsUpdate(updatedResults);
      setSelectedResult(updatedResult);
      setEditedContent(updatedResult.conversion_result?.markdown_content || editedContent);
      
      toast.success('Vector optimization applied successfully!', { 
        id: loadingToast,
        icon: '🎯'
      });

    } catch (error: any) {
      console.error('Failed to apply vector optimization:', error);
      if (error?.status === 409) {
        toast.error('Another operation is already running for this document. Please retry after it completes.', { id: loadingToast });
      } else {
        toast.error('Failed to apply vector optimization', { id: loadingToast });
      }
    } finally {
      setIsEditing(false);
    }
  };

  const handleCustomImprovement = async () => {
    if (!selectedResult || !customPrompt.trim()) return;

    setIsEditing(true);
    const loadingToast = toast.loading('Applying custom improvements (queued)...');
    
    try {
      const updatedResult = await enqueueUpdateWithAutoRetry(
        selectedResult.document_id,
        editedContent,
        customPrompt
      );

      // Update the result in the list
      const updatedResults = processingResults.map(r =>
        r.document_id === selectedResult.document_id ? updatedResult : r
      );
      onResultsUpdate(updatedResults);
      setSelectedResult(updatedResult);
      setEditedContent(updatedResult.conversion_result?.markdown_content || editedContent);
      
      toast.success('Custom improvements applied successfully!', { 
        id: loadingToast,
        icon: '✨'
      });

    } catch (error: any) {
      console.error('Failed to apply custom improvements:', error);
      if (error?.status === 409) {
        toast.error('Another operation is already running for this document. Please retry after it completes.', { id: loadingToast });
      } else {
        toast.error('Failed to apply custom improvements', { id: loadingToast });
      }
    } finally {
      setIsEditing(false);
    }
  };

  const getQualityColor = (score: number, threshold: number) => {
    if (score >= 9) return 'text-green-600';
    if (score >= threshold) return 'text-yellow-600';
    return 'text-red-600';
  };

  const getPassFailColor = (passes: boolean) => {
    return passes
      ? 'bg-green-100 text-green-800'
      : 'bg-red-100 text-red-800';
  };

  const getScoreIcon = (score: number, threshold: number) => {
    if (score >= threshold) return '🟢';
    return '🔴';
  };

  const successfulResults = processingResults.filter(r => r.success);
  const ragReadyCount = successfulResults.filter(r => r.pass_all_thresholds).length;
  const vectorOptimizedCount = successfulResults.filter(r => r.vector_optimized).length;

  // Show waiting state only if no results are available yet
  if (processingResults.length === 0 && !isProcessingComplete) {
    return (
      <div className="space-y-6 pb-24">
        {/* Header */}
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">📊 Review Results</h2>
          <p className="text-gray-600">
            {isProcessing 
              ? 'Processing documents in the background. Results will appear here as they complete.'
              : 'Waiting for documents to process...'
            }
          </p>
        </div>

        {/* Processing Status */}
        <div className="bg-white rounded-lg border p-8">
          <div className="text-center">
            <div className="mb-6">
              {isProcessing ? (
                <div className="animate-spin rounded-full h-16 w-16 border-b-4 border-blue-600 mx-auto"></div>
              ) : (
                <div className="text-6xl mb-4">⏳</div>
              )}
            </div>
            
            <h3 className="text-xl font-medium text-gray-900 mb-2">
              {isProcessing ? 'Processing in Progress' : 'Ready to Process'}
            </h3>
            
            <p className="text-gray-600 mb-6">
              {isProcessing 
                ? `Processing ${selectedFiles.length} document(s). You can monitor progress in the processing panel.`
                : 'Documents will be processed when you start the operation.'
              }
            </p>
          </div>
        </div>

        {/* Tips while waiting */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
          <h4 className="font-medium text-blue-900 mb-2">💡 While You Wait</h4>
          <ul className="text-sm text-blue-800 space-y-1">
            <li>• Results will appear automatically as documents are processed</li>
            <li>• You can monitor detailed progress in the processing panel</li>
            <li>• Each document is evaluated for clarity, completeness, relevance, and markdown quality</li>
            <li>• The system will notify you when all documents are complete</li>
          </ul>
        </div>
      </div>
    );
  }

  // Show results interface when we have at least one result
  return (
    <div className="space-y-6 pb-24">
      {/* Streamlined Header */}
      <div className="text-center">
        <h2 className="text-2xl font-bold text-gray-900 mb-2">📊 Review Results</h2>
        <p className="text-gray-600">
          Review and improve your processed documents before finalizing
        </p>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-blue-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-blue-600">{processingResults.length}</div>
          <div className="text-sm text-blue-800">
            {isProcessing ? `of ${selectedFiles.length}` : 'Total Files'}
          </div>
        </div>
        <div className="bg-green-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-green-600">{ragReadyCount}</div>
          <div className="text-sm text-green-800">RAG Ready</div>
        </div>
        <div className="bg-purple-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-purple-600">{vectorOptimizedCount}</div>
          <div className="text-sm text-purple-800">Optimized</div>
        </div>
        <div className="bg-gray-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-gray-600">{successfulResults.length}</div>
          <div className="text-sm text-gray-800">Successful</div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Panel - Results List */}
        <div className="lg:col-span-1">
          <div className="bg-white rounded-lg border p-6">
            <h3 className="text-lg font-medium mb-4">
              📋 Results ({successfulResults.length}
              {isProcessing && ` of ${selectedFiles.length}`})
            </h3>
            
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {successfulResults.map((result) => {
                const isSelected = selectedResult?.document_id === result.document_id;
                const qualityBadge = getQualityColor(result.conversion_score, qualityThresholds.conversion);
                const passBadge = getPassFailColor(result.pass_all_thresholds);

                return (
                  <button
                    key={result.document_id}
                    type="button"
                    onClick={() => setSelectedResult(result)}
                    className={`w-full text-left p-3 rounded-lg border transition-colors ${
                      isSelected 
                        ? 'border-blue-500 bg-blue-50' 
                        : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium text-gray-900 truncate">{result.filename}</span>
                    </div>
                    
                    <div className="flex items-center justify-between text-xs">
                      <span className={`px-2 py-1 rounded ${qualityBadge}`}>
                        {result.conversion_score}%
                      </span>
                      <span className={`px-2 py-1 rounded ${passBadge}`}>
                        {result.pass_all_thresholds ? 'PASS' : 'FAIL'}
                      </span>
                    </div>
                    
                    {result.vector_optimized && (
                      <div className="mt-1">
                        <span className="text-xs bg-purple-100 text-purple-800 px-2 py-1 rounded">
                          🎯 Optimized
                        </span>
                      </div>
                    )}
                  </button>
                );
              })}
              
              {/* Show placeholder for pending files when still processing */}
              {isProcessing && processingResults.length < selectedFiles.length && (
                <div className="space-y-2">
                  {Array.from({ length: selectedFiles.length - processingResults.length }).map((_, index) => (
                    <div key={`pending-${index}`} className="p-3 border border-dashed border-gray-200 rounded-lg">
                      <div className="flex items-center space-x-3">
                        <div className="animate-pulse rounded-full h-4 w-4 bg-gray-300"></div>
                        <span className="text-gray-500 text-sm">Processing...</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right Panel - Review Details */}
        <div className="lg:col-span-2">
          <div className="bg-white rounded-lg border p-6">
            {selectedResult ? (
              <div>
                {/* Header */}
                <div className="mb-6">
                  <h3 className="text-xl font-medium mb-2">📄 {selectedResult.filename}</h3>
                  <div className="flex items-center space-x-4">
                    <span className={`px-3 py-1 rounded-full text-sm font-medium ${getQualityColor(selectedResult.conversion_score, qualityThresholds.conversion)}`}>
                      Quality: {selectedResult.conversion_score}%
                    </span>
                    <span className={`px-3 py-1 rounded-full text-sm font-medium ${getPassFailColor(selectedResult.pass_all_thresholds)}`}>
                      {selectedResult.pass_all_thresholds ? '✅ PASS' : '❌ FAIL'}
                    </span>
                    {selectedResult.vector_optimized && (
                      <span className="px-3 py-1 rounded-full text-sm font-medium bg-purple-100 text-purple-800">
                        🎯 Optimized
                      </span>
                    )}
                  </div>
                </div>

                {/* Tabs */}
                <div className="flex space-x-1 bg-gray-100 p-1 rounded-lg mb-6">
                  <button
                    type="button"
                    onClick={() => setActiveTab('quality')}
                    className={`flex-1 px-4 py-2 rounded-md transition-colors ${
                      activeTab === 'quality'
                        ? 'bg-white text-gray-900 shadow-sm'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                  >
                    📊 Quality Scores
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab('editor')}
                    className={`flex-1 px-4 py-2 rounded-md transition-colors ${
                      activeTab === 'editor'
                        ? 'bg-white text-gray-900 shadow-sm'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                  >
                    ✏️ Live Editor
                  </button>
                </div>

                {/* Tab Content */}
                {activeTab === 'quality' ? (
                  <div className="space-y-6">
                    {/* Conversion Quality */}
                    <div>
                      <h4 className="font-medium mb-3">📄 Conversion Quality</h4>
                      <div className="bg-gray-50 p-4 rounded-lg">
                        <div className="text-2xl font-bold mb-2">{selectedResult.conversion_score}/100</div>
                        {selectedResult.conversion_result?.conversion_feedback && (
                          <p className="text-gray-600">{selectedResult.conversion_result.conversion_feedback}</p>
                        )}
                      </div>
                    </div>

                    {/* LLM Evaluation */}
                    {selectedResult.llm_evaluation && (
                      <div>
                        <h4 className="font-medium mb-3">📊 Content Quality</h4>
                        <div className="grid grid-cols-2 gap-4">
                          <div className="space-y-3">
                            <div className="flex items-center justify-between">
                              <span className="text-sm font-medium">Clarity</span>
                              <div className="flex items-center space-x-2">
                                <span className={getQualityColor(selectedResult.llm_evaluation.clarity_score || 0, qualityThresholds.clarity)}>
                                  {selectedResult.llm_evaluation.clarity_score || 'N/A'}/10
                                </span>
                                <span>{getScoreIcon(selectedResult.llm_evaluation.clarity_score || 0, qualityThresholds.clarity)}</span>
                              </div>
                            </div>
                            {selectedResult.llm_evaluation.clarity_feedback && (
                              <p className="text-xs text-gray-600">{selectedResult.llm_evaluation.clarity_feedback}</p>
                            )}
                          </div>

                          <div className="space-y-3">
                            <div className="flex items-center justify-between">
                              <span className="text-sm font-medium">Completeness</span>
                              <div className="flex items-center space-x-2">
                                <span className={getQualityColor(selectedResult.llm_evaluation.completeness_score || 0, qualityThresholds.completeness)}>
                                  {selectedResult.llm_evaluation.completeness_score || 'N/A'}/10
                                </span>
                                <span>{getScoreIcon(selectedResult.llm_evaluation.completeness_score || 0, qualityThresholds.completeness)}</span>
                              </div>
                            </div>
                            {selectedResult.llm_evaluation.completeness_feedback && (
                              <p className="text-xs text-gray-600">{selectedResult.llm_evaluation.completeness_feedback}</p>
                            )}
                          </div>

                          <div className="space-y-3">
                            <div className="flex items-center justify-between">
                              <span className="text-sm font-medium">Relevance</span>
                              <div className="flex items-center space-x-2">
                                <span className={getQualityColor(selectedResult.llm_evaluation.relevance_score || 0, qualityThresholds.relevance)}>
                                  {selectedResult.llm_evaluation.relevance_score || 'N/A'}/10
                                </span>
                                <span>{getScoreIcon(selectedResult.llm_evaluation.relevance_score || 0, qualityThresholds.relevance)}</span>
                              </div>
                            </div>
                            {selectedResult.llm_evaluation.relevance_feedback && (
                              <p className="text-xs text-gray-600">{selectedResult.llm_evaluation.relevance_feedback}</p>
                            )}
                          </div>

                          <div className="space-y-3">
                            <div className="flex items-center justify-between">
                              <span className="text-sm font-medium">Markdown</span>
                              <div className="flex items-center space-x-2">
                                <span className={getQualityColor(selectedResult.llm_evaluation.markdown_score || 0, qualityThresholds.markdown)}>
                                  {selectedResult.llm_evaluation.markdown_score || 'N/A'}/10
                                </span>
                                <span>{getScoreIcon(selectedResult.llm_evaluation.markdown_score || 0, qualityThresholds.markdown)}</span>
                              </div>
                            </div>
                            {selectedResult.llm_evaluation.markdown_feedback && (
                              <p className="text-xs text-gray-600">{selectedResult.llm_evaluation.markdown_feedback}</p>
                            )}
                          </div>
                        </div>

                        {/* Overall Feedback */}
                        {selectedResult.llm_evaluation.overall_feedback && (
                          <div className="mt-4 p-4 bg-blue-50 rounded-lg">
                            <h5 className="font-medium text-blue-900 mb-2">💡 Improvement Suggestions</h5>
                            <p className="text-blue-800">{selectedResult.llm_evaluation.overall_feedback}</p>
                          </div>
                        )}

                        {/* LLM Recommendation */}
                        {selectedResult.llm_evaluation.pass_recommendation && (
                          <div className={`mt-4 p-4 rounded-lg ${
                            selectedResult.llm_evaluation.pass_recommendation.toLowerCase().startsWith('p')
                              ? 'bg-green-50 border border-green-200'
                              : 'bg-yellow-50 border border-yellow-200'
                          }`}>
                            <h5 className="font-medium mb-2">🤖 LLM Recommendation</h5>
                            <p className={
                              selectedResult.llm_evaluation.pass_recommendation.toLowerCase().startsWith('p')
                                ? 'text-green-800'
                                : 'text-yellow-800'
                            }>
                              {selectedResult.llm_evaluation.pass_recommendation.toLowerCase().startsWith('p')
                                ? '✅ Pass - Document meets quality standards'
                                : '⚠️ Needs improvement before RAG use'
                              }
                            </p>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Threshold Reference */}
                    <div>
                      <h4 className="font-medium mb-3">🎯 Current Thresholds</h4>
                      <div className="bg-gray-50 p-4 rounded-lg">
                        <p className="text-sm text-gray-600 mb-2">All must be met for RAG readiness:</p>
                        <div className="grid grid-cols-2 gap-2 text-sm">
                          <div>📄 Conversion: ≥ {qualityThresholds.conversion}/100</div>
                          <div>📝 Clarity: ≥ {qualityThresholds.clarity}/10</div>
                          <div>📋 Completeness: ≥ {qualityThresholds.completeness}/10</div>
                          <div>🎯 Relevance: ≥ {qualityThresholds.relevance}/10</div>
                          <div>📄 Markdown: ≥ {qualityThresholds.markdown}/10</div>
                        </div>
                      </div>
                    </div>

                    {/* Document Summary */}
                    {selectedResult.document_summary && (
                      <div>
                        <h4 className="font-medium mb-3">📝 Document Summary</h4>
                        <div className="bg-gray-50 p-4 rounded-lg">
                          <p className="text-gray-700">{selectedResult.document_summary}</p>
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  /* Live Editor Tab */
                  <div className="space-y-6">
                    <h4 className="font-medium">✏️ Live Editor</h4>
                    
                    {isLoading ? (
                      <div className="flex items-center justify-center py-8">
                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                        <span className="ml-2">Loading content...</span>
                      </div>
                    ) : (
                      <>
                        {/* Text Editor */}
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">
                            Markdown Content
                          </label>
                          <textarea
                            value={editedContent}
                            onChange={(e) => setEditedContent(e.target.value)}
                            rows={12}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 font-mono text-sm"
                            placeholder="Markdown content will appear here..."
                          />
                        </div>

                        {/* Action Buttons */}
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                          <button
                            type="button"
                            onClick={handleSaveAndRescore}
                            disabled={isEditing}
                            className="flex items-center justify-center px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {isEditing ? (
                              <span className="flex items-center space-x-2">
                                <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></span>
                                <span>Queued…</span>
                              </span>
                            ) : (
                              <>💾 Save & Re-Score</>
                            )}
                          </button>

                          <button
                            type="button"
                            onClick={handleVectorOptimize}
                            disabled={isEditing || selectedResult.vector_optimized}
                            className="flex items-center justify-center px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {isEditing ? (
                              <span className="flex items-center space-x-2">
                                <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></span>
                                <span>Queued…</span>
                              </span>
                            ) : (
                              <>🎯 Vector Optimize</>
                            )}
                          </button>

                          <button
                            type="button"
                            onClick={() => setShowCustomPrompt(!showCustomPrompt)}
                            disabled={isEditing}
                            className="flex items-center justify-center px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            ✨ Custom Edit
                          </button>
                        </div>

                        {/* Disabled state explanation */}
                        {selectedResult.vector_optimized && (
                          <div className="text-sm text-gray-600 bg-gray-50 p-3 rounded-lg">
                            ℹ️ Vector optimization already applied during processing
                          </div>
                        )}

                        {/* Custom LLM Edit Section */}
                        {showCustomPrompt && (
                          <div className="border-t pt-6">
                            <h5 className="font-medium mb-3">🎨 Custom LLM Instructions</h5>
                            <div className="space-y-4">
                              <textarea
                                value={customPrompt}
                                onChange={(e) => setCustomPrompt(e.target.value)}
                                rows={3}
                                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500"
                                placeholder="Enter instructions for the LLM to improve the document..."
                              />
                              <button
                                type="button"
                                onClick={handleCustomImprovement}
                                disabled={isEditing || !customPrompt.trim()}
                                className="w-full px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
                              >
                                {isEditing ? (
                                  <span className="flex items-center justify-center space-x-2">
                                    <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></span>
                                    <span>Queued…</span>
                                  </span>
                                ) : (
                                  'Apply Custom Improvements'
                                )}
                              </button>
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            ) : (
              /* No Selection State */
              <div className="text-center py-12">
                <div className="text-6xl mb-4">👈</div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">Select a file to review</h3>
                <p className="text-gray-600">
                  Choose a processed document from the list to view quality scores and edit content
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

{/* Fixed Action Button - Bottom Right with Processing Panel Awareness */}
      {processingPanelState !== 'fullscreen' && (
        <div className={`fixed right-6 z-40 transition-all duration-300 ${
          processingPanelState === 'normal' 
            ? 'bottom-[424px]'  // Above normal processing panel: 360px panel + 52px (status + gap) + 12px margin = 424px
            : processingPanelState === 'minimized'
            ? 'bottom-[92px]'   // Above minimized panel: 40px panel + 40px (status) + 12px margin = 92px
            : 'bottom-16'       // Above status bar only: 52px (status + gap) + 12px margin = 64px (bottom-16)
        }`}>
          <button
            type="button"
            onClick={onComplete}
            disabled={isProcessing}
            className={`px-6 py-3 rounded-full font-medium text-sm transition-all shadow-lg hover:shadow-xl ${
              isProcessing
                ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                : 'bg-green-600 text-white hover:bg-green-700 hover:-translate-y-1'
            }`}
          >
            {isProcessing ? (
              <span className="flex items-center space-x-2">
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-400"></div>
                <span>Processing {selectedFiles.length - processingResults.length} more...</span>
              </span>
            ) : (
              '✅ Finish Review'
            )}
          </button>
        </div>
      )}
    </div>
  );
}

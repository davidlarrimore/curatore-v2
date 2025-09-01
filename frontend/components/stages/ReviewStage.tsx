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

type ResultFilter = 'all' | 'failed_processing' | 'failed_quality' | 'passed'

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
  // LLM-based custom improvements are disabled
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isEditing, setIsEditing] = useState<boolean>(false);
  const [resultFilter, setResultFilter] = useState<ResultFilter>('all');
  // Processing log state for failed results
  const [logLoading, setLogLoading] = useState<boolean>(false);
  const [logError, setLogError] = useState<string>('');
  const [processingLog, setProcessingLog] = useState<Array<{ timestamp?: string; level?: string; message?: string }>>([]);
  const [jobMeta, setJobMeta] = useState<any>(null);

  // Consistent timestamp formatter (time only) to match processing bar
  const formatTimestamp = (raw: any): string => {
    if (!raw) return ''
    try {
      let d: Date | null = null
      if (typeof raw === 'number') {
        d = new Date(raw > 1e12 ? raw : raw * 1000)
      } else if (typeof raw === 'string') {
        const trimmed = raw.trim()
        const num = Number(trimmed)
        if (!Number.isNaN(num) && trimmed.length >= 10 && trimmed.length <= 13) {
          d = new Date(num > 1e12 ? num : num * 1000)
        } else {
          const parsed = new Date(trimmed)
          if (!Number.isNaN(parsed.getTime())) d = parsed
        }
      }
      if (!d || Number.isNaN(d.getTime())) return String(raw)
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    } catch {
      return String(raw)
    }
  }

  // Load document content when result is selected and is editable
  useEffect(() => {
    if (!selectedResult || activeTab !== 'editor') return;
    // Avoid fetching content for failed processing results
    if (!selectedResult.success) {
      setDocumentContent('');
      setEditedContent('');
      return;
    }
    loadDocumentContent(selectedResult.document_id);
  }, [selectedResult, activeTab]);

  // Load processing log for failed results
  useEffect(() => {
    setProcessingLog([]);
    setLogError('');
    setJobMeta(null);
    if (!selectedResult || selectedResult.success !== false) return;
    const fetchLog = async () => {
      setLogLoading(true);
      try {
        const byDoc: any = await jobsApi.getJobByDocument(selectedResult.document_id);
        // Attempt to extract logs directly, if present
        const logs = byDoc?.logs || byDoc?.log || byDoc?.events || [];
        const normalized = Array.isArray(logs)
          ? logs.map((l: any) => ({ timestamp: l.timestamp || l.ts || l.time, level: l.level || l.severity || 'info', message: l.message || l.msg || String(l) }))
          : [];
        if (normalized.length > 0) {
          setProcessingLog(normalized);
        } else if (byDoc?.job_id) {
          // Fetch job details for logs
          try {
            const job = await jobsApi.getJob(byDoc.job_id);
            const jlogs = job?.logs || job?.log || job?.events || [];
            const n2 = Array.isArray(jlogs)
              ? jlogs.map((l: any) => ({ timestamp: l.timestamp || l.ts || l.time, level: l.level || l.severity || 'info', message: l.message || l.msg || String(l) }))
              : [];
            if (n2.length > 0) setProcessingLog(n2);
            setJobMeta(job);
          } catch {}
        }
        setJobMeta((jm: any) => jm || byDoc);
        if (normalized.length === 0 && !byDoc?.job_id) {
          setLogError('No processing log available for this file.');
        }
      } catch (e: any) {
        setLogError(e?.message || 'Failed to load processing log');
      } finally {
        setLogLoading(false);
      }
    };
    fetchLog();
  }, [selectedResult]);

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
  ): Promise<ProcessingResult> => {
    try {
      const resp = await contentApi.updateDocumentContent(documentId, content);
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
        const retry = await contentApi.updateDocumentContent(documentId, content);
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

  // Vector optimization and custom LLM improvements are disabled

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

  // Helpers for messaging and applicability
  const isMarkdownSource = (filename?: string) => {
    if (!filename) return false;
    const f = filename.toLowerCase();
    return f.endsWith('.md') || f.endsWith('.markdown');
  };
  const hasConvertedMarkdown = (r: ProcessingResult | null) => {
    if (!r) return false;
    return Boolean((r as any).markdown_path || r.conversion_result?.markdown_content);
  };
  const getMarkdownAwareFeedback = (feedback?: string, filename?: string) => {
    if (!feedback) return feedback;
    const fb = feedback.trim();
    // If backend reports that no markdown was produced, clarify outcome without implying a separate step ran now
    if (/no markdown produced\.?/i.test(fb)) {
      return 'No markdown available. The conversion step did not produce markdown content for this file.';
    }
    return feedback;
  };

  const isExtractionOnlyFailure = (r?: ProcessingResult | null) => {
    if (!r) return false;
    const nonMdSource = !isMarkdownSource(r.filename);
    const hasMd = hasConvertedMarkdown(r);
    const msg = (r.message || '').toLowerCase();
    const suggestsNoMd = msg.includes('no markdown') || msg.includes('conversion failed');
    return r.success === false && nonMdSource && !hasMd && suggestsNoMd;
  };

  const getUserFacingErrorMessage = (message?: string, filename?: string, result?: ProcessingResult) => {
    if (!message) return message;
    const hasMd = hasConvertedMarkdown(result || null);
    const nonMdSource = !isMarkdownSource(filename);
    const msg = message.trim();
    const lower = msg.toLowerCase();
    const mentionsNoMd = lower.includes('no markdown produced');
    const mentionsConversionFailed = lower.startsWith('conversion failed');
    if ((mentionsNoMd || mentionsConversionFailed) && nonMdSource && !hasMd) {
      return 'Extraction failed: No content was extracted; conversion was not attempted.';
    }
    return message;
  };

  const successfulResults = processingResults.filter(r => r.success);
  const filteredResults = (() => {
    switch (resultFilter) {
      case 'failed_processing':
        return processingResults.filter(r => !r.success);
      case 'failed_quality':
        return processingResults.filter(r => r.success && !r.pass_all_thresholds);
      case 'passed':
        return processingResults.filter(r => r.success && r.pass_all_thresholds);
      case 'all':
      default:
        return processingResults;
    }
  })();
  const ragReadyCount = successfulResults.filter(r => r.pass_all_thresholds).length;
  const vectorOptimizedCount = successfulResults.filter(r => r.vector_optimized).length;

  // Show waiting state only if no results are available yet
  if (processingResults.length === 0 && !isProcessingComplete) {
    return (
      <div className="space-y-6 pb-24">

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
              📋 Results ({filteredResults.length} of {processingResults.length})
            </h3>

            {/* Quick Filters */}
            <div className="flex flex-wrap gap-2 mb-3">
              <button
                type="button"
                onClick={() => setResultFilter('all')}
                className={`px-2 py-1 rounded text-xs border ${resultFilter === 'all' ? 'bg-gray-800 text-white border-gray-800' : 'bg-gray-100 text-gray-700 border-gray-200 hover:bg-gray-200'}`}
                title="Show all results"
              >
                All
              </button>
              <button
                type="button"
                onClick={() => setResultFilter('failed_processing')}
                className={`px-2 py-1 rounded text-xs border ${resultFilter === 'failed_processing' ? 'bg-red-600 text-white border-red-600' : 'bg-red-50 text-red-700 border-red-200 hover:bg-red-100'}`}
                title="Failed to data extract"
              >
                Failed Processing
              </button>
              <button
                type="button"
                onClick={() => setResultFilter('failed_quality')}
                className={`px-2 py-1 rounded text-xs border ${resultFilter === 'failed_quality' ? 'bg-yellow-600 text-white border-yellow-600' : 'bg-yellow-50 text-yellow-800 border-yellow-200 hover:bg-yellow-100'}`}
                title="Passed processing, failed quality review"
              >
                Failed Quality Review
              </button>
              <button
                type="button"
                onClick={() => setResultFilter('passed')}
                className={`px-2 py-1 rounded text-xs border ${resultFilter === 'passed' ? 'bg-green-600 text-white border-green-600' : 'bg-green-50 text-green-700 border-green-200 hover:bg-green-100'}`}
                title="Passed processing and quality review"
              >
                Passed
              </button>
            </div>
            
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {filteredResults.map((result) => {
                const isSelected = selectedResult?.document_id === result.document_id;
                const qualityBadge = getQualityColor(result.conversion_score || 0, qualityThresholds.conversion);
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
                      {result.success ? (
                        <>
                          <span className={`px-2 py-1 rounded ${qualityBadge}`}>
                            {result.conversion_score}%
                          </span>
                          <span className={`px-2 py-1 rounded ${passBadge}`}>
                            {result.pass_all_thresholds ? 'PASS' : 'FAIL'}
                          </span>
                        </>
                      ) : (
                        <span className="px-2 py-1 rounded bg-red-100 text-red-800">
                          PROCESS FAILED
                        </span>
                      )}
                    </div>
                    
                    {result.vector_optimized && (
                      <div className="mt-1">
                        <span className="text-xs bg-purple-100 text-purple-800 px-2 py-1 rounded">
                          🎯 Optimized
                        </span>
                      </div>
                    )}
                    {isExtractionOnlyFailure(result) && (
                      <div className="mt-1">
                        <span className="text-xs bg-yellow-100 text-yellow-800 px-2 py-1 rounded">
                          ⏭️ Conversion Skipped
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
                    onClick={() => selectedResult?.success && setActiveTab('editor')}
                    disabled={!selectedResult?.success}
                    aria-disabled={!selectedResult?.success}
                    className={`flex-1 px-4 py-2 rounded-md transition-colors ${
                      !selectedResult?.success
                        ? 'text-gray-400 cursor-not-allowed'
                        : activeTab === 'editor'
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
                          <p className="text-gray-600">
                            {getMarkdownAwareFeedback(selectedResult.conversion_result.conversion_feedback, selectedResult.filename)}
                          </p>
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

                          {(isMarkdownSource(selectedResult.filename) || hasConvertedMarkdown(selectedResult)) ? (
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
                          ) : (
                            <div className="space-y-1">
                              <div className="text-sm font-medium text-gray-500">Markdown</div>
                              <p className="text-xs text-gray-500">Evaluated after conversion. Not applicable at extraction stage for this file type.</p>
                            </div>
                          )}
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

                    {/* Failure Details and Processing Log */}
                    {!selectedResult.success && (
                      <div className="space-y-4">
                        <h4 className="font-medium mb-1">⚠️ Processing Failure Details</h4>
                        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm">
                          <div className="flex items-center justify-between">
                            <span className="text-red-800 font-medium">Status:</span>
                            <span className="text-red-900 font-mono">{selectedResult.status || 'failed'}</span>
                          </div>
                          <div className="flex items-center justify-between mt-1">
                            <span className="text-red-800 font-medium">Markdown quality:</span>
                            <span className="text-red-900 font-mono">Not applicable (no markdown available)</span>
                          </div>
                          {selectedResult.message && (
                            <div className="mt-2">
                              <div className="text-red-800 font-medium">Message</div>
                              <div className="text-red-900 whitespace-pre-wrap">
                                {getUserFacingErrorMessage(selectedResult.message, selectedResult.filename, selectedResult)}
                              </div>
                            </div>
                          )}
                          {isExtractionOnlyFailure(selectedResult) ? (
                            <div className="mt-2">
                              <div className="text-red-800 font-medium">Conversion</div>
                              <div className="text-red-900">Not attempted due to extraction failure.</div>
                            </div>
                          ) : (
                            <>
                              {selectedResult.conversion_result?.conversion_feedback && (
                                <div className="mt-2">
                                  <div className="text-red-800 font-medium">Converter Feedback</div>
                                  <div className="text-red-900 whitespace-pre-wrap">{getMarkdownAwareFeedback(selectedResult.conversion_result.conversion_feedback, selectedResult.filename)}</div>
                                </div>
                              )}
                              {selectedResult.conversion_result?.conversion_note && (
                                <div className="mt-2">
                                  <div className="text-red-800 font-medium">Converter Notes</div>
                                  <div className="text-red-900 whitespace-pre-wrap">{selectedResult.conversion_result.conversion_note}</div>
                                </div>
                              )}
                            </>
                          )}
                        </div>

                        <div>
                          <h5 className="font-medium mb-2">🔎 What the system attempted</h5>
                          <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-sm space-y-1">
                            <div className="flex items-start justify-between">
                              <span className="text-gray-600">Vector optimize attempted:</span>
                              <span className="text-gray-900 font-mono">{selectedResult.vector_optimized ? 'yes' : 'no'}</span>
                            </div>
                            {jobMeta?.processor && (
                              <div className="flex items-start justify-between">
                                <span className="text-gray-600">Python framework:</span>
                                <span className="text-gray-900 font-mono">{String(jobMeta.processor)}</span>
                              </div>
                            )}
                            {jobMeta?.settings && (
                              <div className="mt-1">
                                <div className="text-gray-600">Settings used:</div>
                                <pre className="mt-1 bg-white rounded border border-gray-200 p-2 text-xs overflow-x-auto">{JSON.stringify(jobMeta.settings, null, 2)}</pre>
                              </div>
                            )}
                            {!jobMeta?.processor && !jobMeta?.settings && (
                              <div className="text-gray-600">
                                Detailed framework/settings were not provided by the API for this job.
                              </div>
                            )}
                          </div>
                        </div>

                        <div>
                          <h5 className="font-medium mb-2">🧾 Processing Log</h5>
                          {logLoading ? (
                            <div className="flex items-center space-x-2 text-gray-600 text-sm">
                              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-400"></div>
                              <span>Loading log…</span>
                            </div>
                          ) : logError ? (
                            <div className="text-sm text-gray-600">{logError}</div>
                          ) : processingLog.length === 0 ? (
                            <div className="text-sm text-gray-600">No log entries available.</div>
                          ) : (
                            <div className="processing-log bg-black text-gray-100 rounded-md p-3 max-h-64 overflow-y-auto overflow-x-hidden text-xs">
                              {processingLog.map((e, i) => (
                                <div key={i} className="log-entry py-0.5 flex items-start">
                                  <span className="log-timestamp text-gray-400 mr-2 font-mono w-[120px] flex-shrink-0">{formatTimestamp(e.timestamp)}</span>
                                  <span className={`mr-2 flex-shrink-0 ${e.level === 'error' ? 'text-red-400' : e.level === 'warning' ? 'text-yellow-300' : 'text-green-300'}`}>{(e.level || 'info').toUpperCase()}</span>
                                  <span className="log-message text-gray-100 whitespace-pre-wrap break-words break-all">
                                    {e.message}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="space-y-6">
                    {/* Live Editor Tab */}
                    <h4 className="font-medium">✏️ Live Editor</h4>
                    
                    {!selectedResult?.success ? (
                      <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-md text-sm text-yellow-800">
                        This document failed processing, so no editable content is available.
                      </div>
                    ) : isLoading ? (
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
                        </div>

                        {/* Disabled state explanation */}
                        {/* Vector optimization disabled */}

                        {/* Custom LLM improvements disabled */}
                      </>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center py-12">
                {/* No Selection State */}
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

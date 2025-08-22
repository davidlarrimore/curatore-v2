// components/stages/ReviewStage.tsx
'use client'

import { useState, useEffect } from 'react';
import { ProcessingResult, QualityThresholds } from '@/types';
import { contentApi, utils } from '@/lib/api';

interface ReviewStageProps {
  processingResults: ProcessingResult[];
  onResultsUpdate: (results: ProcessingResult[]) => void;
  onComplete: () => void;
  qualityThresholds: QualityThresholds;
}

type TabType = 'quality' | 'editor';

export function ReviewStage({
  processingResults,
  onResultsUpdate,
  onComplete,
  qualityThresholds
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
    } finally {
      setIsLoading(false);
    }
  };

  const handleSaveAndRescore = async () => {
    if (!selectedResult) return;

    setIsEditing(true);
    try {
      const updatedResult = await contentApi.updateDocumentContent(
        selectedResult.document_id,
        editedContent
      );

      // Update the result in the list
      const updatedResults = processingResults.map(r =>
        r.document_id === selectedResult.document_id ? updatedResult : r
      );
      onResultsUpdate(updatedResults);
      setSelectedResult(updatedResult);

    } catch (error) {
      console.error('Failed to save and re-score:', error);
      alert('Failed to save and re-score document');
    } finally {
      setIsEditing(false);
    }
  };

  const handleVectorOptimize = async () => {
    if (!selectedResult) return;

    setIsEditing(true);
    try {
      const updatedResult = await contentApi.updateDocumentContent(
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

    } catch (error) {
      console.error('Failed to apply vector optimization:', error);
      alert('Failed to apply vector optimization');
    } finally {
      setIsEditing(false);
    }
  };

  const handleCustomImprovement = async () => {
    if (!selectedResult || !customPrompt.trim()) return;

    setIsEditing(true);
    try {
      const updatedResult = await contentApi.updateDocumentContent(
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

    } catch (error) {
      console.error('Failed to apply custom improvements:', error);
      alert('Failed to apply custom improvements');
    } finally {
      setIsEditing(false);
    }
  };

  const getQualityColor = (score: number, threshold: number) => {
    if (score >= 9) return 'text-green-600';
    if (score >= threshold) return 'text-yellow-600';
    return 'text-red-600';
  };

  const getScoreIcon = (score: number, threshold: number) => {
    if (score >= threshold) return '🟢';
    return '🔴';
  };

  const successfulResults = processingResults.filter(r => r.success);
  const ragReadyCount = successfulResults.filter(r => r.pass_all_thresholds).length;
  const vectorOptimizedCount = successfulResults.filter(r => r.vector_optimized).length;

  return (
    <div className="space-y-6">
      {/* Header */}
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
          <div className="text-sm text-blue-800">Total Files</div>
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
            <h3 className="text-lg font-medium mb-4">📋 Results ({successfulResults.length})</h3>
            
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {successfulResults.map((result) => {
                const isSelected = selectedResult?.document_id === result.document_id;
                const qualityBadge = utils.getQualityColor(result.conversion_score, qualityThresholds.conversion);
                const passBadge = utils.getPassFailColor(result.pass_all_thresholds);

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
                    <span className={`px-3 py-1 rounded-full text-sm font-medium ${utils.getQualityColor(selectedResult.conversion_score, qualityThresholds.conversion)}`}>
                      Quality: {selectedResult.conversion_score}%
                    </span>
                    <span className={`px-3 py-1 rounded-full text-sm font-medium ${utils.getPassFailColor(selectedResult.pass_all_thresholds)}`}>
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
                              <>
                                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                                Saving...
                              </>
                            ) : (
                              '💾 Save & Re-Score'
                            )}
                          </button>

                          <button
                            type="button"
                            onClick={handleVectorOptimize}
                            disabled={isEditing || selectedResult.vector_optimized}
                            className="flex items-center justify-center px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {isEditing ? (
                              <>
                                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                                Optimizing...
                              </>
                            ) : (
                              '🎯 Vector Optimize'
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
                                  <>
                                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2 inline-block"></div>
                                    Applying improvements...
                                  </>
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

      {/* Complete Review Button */}
      <div className="flex justify-center pt-6 border-t">
        <button
          type="button"
          onClick={onComplete}
          className="px-8 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium text-lg"
        >
          ✅ Finish Review
        </button>
      </div>
    </div>
  );
}
// components/Settings.tsx
'use client'

import { useState, useEffect } from 'react';
import { QualityThresholds, OCRSettings, LLMConnectionStatus } from '@/types';
import { systemApi } from '@/lib/api';

interface SettingsProps {
  qualityThresholds: QualityThresholds;
  onQualityThresholdsChange: (thresholds: QualityThresholds) => void;
  ocrSettings: OCRSettings;
  onOCRSettingsChange: (settings: OCRSettings) => void;
  autoOptimize: boolean;
  onAutoOptimizeChange: (enabled: boolean) => void;
}

export function Settings({
  qualityThresholds,
  onQualityThresholdsChange,
  ocrSettings,
  onOCRSettingsChange,
  autoOptimize,
  onAutoOptimizeChange
}: SettingsProps) {
  const [llmStatus, setLLMStatus] = useState<LLMConnectionStatus | null>(null);
  const [isTestingLLM, setIsTestingLLM] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Load LLM status on mount
  useEffect(() => {
    testLLMConnection();
  }, []);

  const testLLMConnection = async () => {
    setIsTestingLLM(true);
    try {
      const status = await systemApi.getLLMStatus();
      setLLMStatus(status);
    } catch (error) {
      console.error('Failed to test LLM connection:', error);
      setLLMStatus({
        connected: false,
        endpoint: 'Unknown',
        model: 'Unknown',
        error: 'Connection test failed',
        ssl_verify: true,
        timeout: 60
      });
    } finally {
      setIsTestingLLM(false);
    }
  };

  const handleThresholdChange = (key: keyof QualityThresholds, value: number) => {
    onQualityThresholdsChange({
      ...qualityThresholds,
      [key]: value
    });
  };

  const handleOCRChange = (key: keyof OCRSettings, value: string | number) => {
    onOCRSettingsChange({
      ...ocrSettings,
      [key]: value
    });
  };

  const resetToDefaults = () => {
    onQualityThresholdsChange({
      conversion: 70,
      clarity: 7,
      completeness: 7,
      relevance: 7,
      markdown: 7
    });
    onOCRSettingsChange({
      language: 'eng',
      psm: 3
    });
    onAutoOptimizeChange(true);
  };

  return (
    <div className="bg-white rounded-2xl border shadow-sm p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-semibold">⚙️ Settings</h2>
        <button
          type="button"
          onClick={resetToDefaults}
          className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
        >
          🔄 Reset to Defaults
        </button>
      </div>

      <div className="space-y-8">
        {/* LLM Connection Status */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium">🤖 LLM Connection</h3>
            <button
              type="button"
              onClick={testLLMConnection}
              disabled={isTestingLLM}
              className="px-3 py-1 text-sm bg-blue-100 hover:bg-blue-200 text-blue-700 rounded-md transition-colors disabled:opacity-50"
            >
              {isTestingLLM ? '🔄 Testing...' : '🔍 Test Connection'}
            </button>
          </div>

          {llmStatus && (
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                <span className="font-medium">Status</span>
                <span className={`px-2 py-1 rounded-full text-sm font-medium ${
                  llmStatus.connected 
                    ? 'bg-green-100 text-green-800' 
                    : 'bg-red-100 text-red-800'
                }`}>
                  {llmStatus.connected ? '✅ Connected' : '❌ Disconnected'}
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-600">Endpoint:</span>
                  <span className="font-mono text-xs truncate ml-2">{llmStatus.endpoint}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Model:</span>
                  <span className="font-mono text-xs">{llmStatus.model}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">SSL Verify:</span>
                  <span className={`px-1 py-0.5 rounded text-xs ${
                    llmStatus.ssl_verify ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'
                  }`}>
                    {llmStatus.ssl_verify ? 'Enabled' : 'Disabled'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Timeout:</span>
                  <span className="text-xs">{llmStatus.timeout}s</span>
                </div>
              </div>

              {llmStatus.error && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
                  <span className="text-red-800 text-sm">⚠️ {llmStatus.error}</span>
                </div>
              )}

              {llmStatus.response && (
                <div className="p-3 bg-green-50 border border-green-200 rounded-lg">
                  <span className="text-green-800 text-sm">✅ Response: {llmStatus.response}</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Processing Options */}
        <div>
          <h3 className="text-lg font-medium mb-4">🎯 Processing Options</h3>
          
          <div className="space-y-4">
            <label className="flex items-center space-x-3">
              <input
                type="checkbox"
                checked={autoOptimize}
                onChange={(e) => onAutoOptimizeChange(e.target.checked)}
                className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <div>
                <span className="font-medium">Vector Database Optimization</span>
                <p className="text-sm text-gray-600">
                  Automatically optimize documents for vector database chunking and retrieval
                </p>
              </div>
            </label>
          </div>
        </div>

        {/* Quality Thresholds */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium">📊 Quality Thresholds</h3>
            <span className="text-sm text-gray-500">All must be met for RAG readiness</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Conversion Quality (0-100)
              </label>
              <div className="flex items-center space-x-2">
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={qualityThresholds.conversion}
                  onChange={(e) => handleThresholdChange('conversion', parseInt(e.target.value))}
                  className="flex-1"
                />
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={qualityThresholds.conversion}
                  onChange={(e) => handleThresholdChange('conversion', parseInt(e.target.value) || 0)}
                  className="w-16 px-2 py-1 border border-gray-300 rounded text-sm"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Clarity (1-10)
              </label>
              <div className="flex items-center space-x-2">
                <input
                  type="range"
                  min="1"
                  max="10"
                  value={qualityThresholds.clarity}
                  onChange={(e) => handleThresholdChange('clarity', parseInt(e.target.value))}
                  className="flex-1"
                />
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={qualityThresholds.clarity}
                  onChange={(e) => handleThresholdChange('clarity', parseInt(e.target.value) || 1)}
                  className="w-16 px-2 py-1 border border-gray-300 rounded text-sm"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Completeness (1-10)
              </label>
              <div className="flex items-center space-x-2">
                <input
                  type="range"
                  min="1"
                  max="10"
                  value={qualityThresholds.completeness}
                  onChange={(e) => handleThresholdChange('completeness', parseInt(e.target.value))}
                  className="flex-1"
                />
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={qualityThresholds.completeness}
                  onChange={(e) => handleThresholdChange('completeness', parseInt(e.target.value) || 1)}
                  className="w-16 px-2 py-1 border border-gray-300 rounded text-sm"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Relevance (1-10)
              </label>
              <div className="flex items-center space-x-2">
                <input
                  type="range"
                  min="1"
                  max="10"
                  value={qualityThresholds.relevance}
                  onChange={(e) => handleThresholdChange('relevance', parseInt(e.target.value))}
                  className="flex-1"
                />
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={qualityThresholds.relevance}
                  onChange={(e) => handleThresholdChange('relevance', parseInt(e.target.value) || 1)}
                  className="w-16 px-2 py-1 border border-gray-300 rounded text-sm"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Markdown Quality (1-10)
              </label>
              <div className="flex items-center space-x-2">
                <input
                  type="range"
                  min="1"
                  max="10"
                  value={qualityThresholds.markdown}
                  onChange={(e) => handleThresholdChange('markdown', parseInt(e.target.value))}
                  className="flex-1"
                />
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={qualityThresholds.markdown}
                  onChange={(e) => handleThresholdChange('markdown', parseInt(e.target.value) || 1)}
                  className="w-16 px-2 py-1 border border-gray-300 rounded text-sm"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Advanced Settings */}
        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center space-x-2 text-lg font-medium text-gray-700 hover:text-gray-900"
          >
            <span>🔧 Advanced Settings</span>
            <svg
              className={`w-4 h-4 transition-transform ${showAdvanced ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {showAdvanced && (
            <div className="mt-4 space-y-4">
              {/* OCR Settings */}
              <div>
                <h4 className="font-medium mb-3">🔍 OCR Settings</h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Language Code
                    </label>
                    <input
                      type="text"
                      value={ocrSettings.language}
                      onChange={(e) => handleOCRChange('language', e.target.value)}
                      placeholder="e.g., eng, eng+spa, fra"
                      className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                      Use language codes like 'eng' for English, 'eng+spa' for English + Spanish
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Page Segmentation Mode (PSM)
                    </label>
                    <select
                      value={ocrSettings.psm}
                      onChange={(e) => handleOCRChange('psm', parseInt(e.target.value))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500"
                    >
                      <option value={0}>0 - OSD only</option>
                      <option value={1}>1 - Auto with OSD</option>
                      <option value={2}>2 - Auto without OSD</option>
                      <option value={3}>3 - Fully automatic (default)</option>
                      <option value={4}>4 - Single column text</option>
                      <option value={5}>5 - Single uniform block</option>
                      <option value={6}>6 - Single uniform block</option>
                      <option value={7}>7 - Single text line</option>
                      <option value={8}>8 - Single word</option>
                      <option value={9}>9 - Single word in circle</option>
                      <option value={10}>10 - Single character</option>
                      <option value={11}>11 - Sparse text</option>
                      <option value={12}>12 - Sparse text with OSD</option>
                      <option value={13}>13 - Raw line</option>
                    </select>
                    <p className="text-xs text-gray-500 mt-1">
                      Controls how Tesseract segments the page for OCR
                    </p>
                  </div>
                </div>
              </div>

              {/* Configuration Info */}
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <h4 className="font-medium text-blue-900 mb-2">💡 Configuration Tips</h4>
                <ul className="text-sm text-blue-800 space-y-1">
                  <li>• Higher quality thresholds ensure better RAG performance but may reject more documents</li>
                  <li>• Vector optimization restructures content for better semantic search</li>
                  <li>• OCR language should match your document languages</li>
                  <li>• PSM 3 works best for most documents; try PSM 6 for clean text blocks</li>
                </ul>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
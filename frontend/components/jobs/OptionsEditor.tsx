'use client'

import { ProcessingOptions } from '@/types'
import { HelpCircle } from 'lucide-react'
import { useState } from 'react'

interface OptionsEditorProps {
  options: ProcessingOptions
  onChange: (options: ProcessingOptions) => void
}

export function OptionsEditor({ options, onChange }: OptionsEditorProps) {
  const [showAdvanced, setShowAdvanced] = useState(false)

  const updateQualityThreshold = (key: keyof ProcessingOptions['quality_thresholds'], value: number) => {
    onChange({
      ...options,
      quality_thresholds: {
        ...options.quality_thresholds,
        [key]: value
      }
    })
  }

  const updateOCRSetting = (key: keyof ProcessingOptions['ocr_settings'], value: any) => {
    onChange({
      ...options,
      ocr_settings: {
        ...options.ocr_settings,
        [key]: value
      }
    })
  }

  const updateProcessingSetting = (key: keyof ProcessingOptions['processing_settings'], value: number) => {
    onChange({
      ...options,
      processing_settings: {
        ...options.processing_settings,
        [key]: value
      }
    })
  }

  const getThresholdHelp = (key: string): string => {
    switch (key) {
      case 'conversion_threshold':
        return 'Minimum overall quality score (0-100) for successful conversion'
      case 'clarity_threshold':
        return 'Minimum readability/legibility score (1-10)'
      case 'completeness_threshold':
        return 'Minimum coverage score (1-10) - ensures content is not missing key parts'
      case 'relevance_threshold':
        return 'Minimum on-topic score (1-10) - ensures content matches intent'
      case 'markdown_threshold':
        return 'Minimum formatting quality score (1-10) for clean Markdown output'
      default:
        return ''
    }
  }

  return (
    <div className="space-y-6">
      {/* Auto-optimize Toggle */}
      <div className="flex items-center justify-between p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="auto-optimize"
            checked={options.auto_optimize}
            onChange={(e) => onChange({ ...options, auto_optimize: e.target.checked })}
            className="w-4 h-4 text-blue-600 rounded focus:ring-2 focus:ring-blue-500"
          />
          <label htmlFor="auto-optimize" className="text-sm font-medium text-gray-900">
            Auto-optimize for RAG
          </label>
        </div>
        <div className="group relative">
          <HelpCircle className="w-4 h-4 text-gray-400 cursor-help" />
          <div className="absolute right-0 bottom-full mb-2 hidden group-hover:block w-64 p-2 bg-gray-900 text-white text-xs rounded shadow-lg z-10">
            Automatically optimize document structure for vector database ingestion
          </div>
        </div>
      </div>

      {/* Quality Thresholds */}
      <div>
        <h4 className="text-sm font-semibold text-gray-900 mb-3">Quality Thresholds</h4>
        <div className="space-y-4">
          {/* Conversion Threshold */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1">
                <label className="text-sm text-gray-700">Conversion</label>
                <div className="group relative">
                  <HelpCircle className="w-3 h-3 text-gray-400 cursor-help" />
                  <div className="absolute left-0 bottom-full mb-1 hidden group-hover:block w-64 p-2 bg-gray-900 text-white text-xs rounded shadow-lg z-10">
                    {getThresholdHelp('conversion_threshold')}
                  </div>
                </div>
              </div>
              <span className="text-sm font-medium text-gray-900">
                {options.quality_thresholds.conversion_threshold}
              </span>
            </div>
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={options.quality_thresholds.conversion_threshold}
              onChange={(e) => updateQualityThreshold('conversion_threshold', parseFloat(e.target.value))}
              className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
            />
            <div className="flex justify-between text-xs text-gray-500 mt-1">
              <span>0</span>
              <span>100</span>
            </div>
          </div>

          {/* Clarity Threshold */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1">
                <label className="text-sm text-gray-700">Clarity</label>
                <div className="group relative">
                  <HelpCircle className="w-3 h-3 text-gray-400 cursor-help" />
                  <div className="absolute left-0 bottom-full mb-1 hidden group-hover:block w-64 p-2 bg-gray-900 text-white text-xs rounded shadow-lg z-10">
                    {getThresholdHelp('clarity_threshold')}
                  </div>
                </div>
              </div>
              <span className="text-sm font-medium text-gray-900">
                {options.quality_thresholds.clarity_threshold}
              </span>
            </div>
            <input
              type="range"
              min="1"
              max="10"
              step="0.5"
              value={options.quality_thresholds.clarity_threshold}
              onChange={(e) => updateQualityThreshold('clarity_threshold', parseFloat(e.target.value))}
              className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
            />
            <div className="flex justify-between text-xs text-gray-500 mt-1">
              <span>1</span>
              <span>10</span>
            </div>
          </div>

          {/* Completeness Threshold */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1">
                <label className="text-sm text-gray-700">Completeness</label>
                <div className="group relative">
                  <HelpCircle className="w-3 h-3 text-gray-400 cursor-help" />
                  <div className="absolute left-0 bottom-full mb-1 hidden group-hover:block w-64 p-2 bg-gray-900 text-white text-xs rounded shadow-lg z-10">
                    {getThresholdHelp('completeness_threshold')}
                  </div>
                </div>
              </div>
              <span className="text-sm font-medium text-gray-900">
                {options.quality_thresholds.completeness_threshold}
              </span>
            </div>
            <input
              type="range"
              min="1"
              max="10"
              step="0.5"
              value={options.quality_thresholds.completeness_threshold}
              onChange={(e) => updateQualityThreshold('completeness_threshold', parseFloat(e.target.value))}
              className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
            />
            <div className="flex justify-between text-xs text-gray-500 mt-1">
              <span>1</span>
              <span>10</span>
            </div>
          </div>

          {/* Relevance Threshold */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1">
                <label className="text-sm text-gray-700">Relevance</label>
                <div className="group relative">
                  <HelpCircle className="w-3 h-3 text-gray-400 cursor-help" />
                  <div className="absolute left-0 bottom-full mb-1 hidden group-hover:block w-64 p-2 bg-gray-900 text-white text-xs rounded shadow-lg z-10">
                    {getThresholdHelp('relevance_threshold')}
                  </div>
                </div>
              </div>
              <span className="text-sm font-medium text-gray-900">
                {options.quality_thresholds.relevance_threshold}
              </span>
            </div>
            <input
              type="range"
              min="1"
              max="10"
              step="0.5"
              value={options.quality_thresholds.relevance_threshold}
              onChange={(e) => updateQualityThreshold('relevance_threshold', parseFloat(e.target.value))}
              className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
            />
            <div className="flex justify-between text-xs text-gray-500 mt-1">
              <span>1</span>
              <span>10</span>
            </div>
          </div>

          {/* Markdown Threshold */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1">
                <label className="text-sm text-gray-700">Markdown Quality</label>
                <div className="group relative">
                  <HelpCircle className="w-3 h-3 text-gray-400 cursor-help" />
                  <div className="absolute left-0 bottom-full mb-1 hidden group-hover:block w-64 p-2 bg-gray-900 text-white text-xs rounded shadow-lg z-10">
                    {getThresholdHelp('markdown_threshold')}
                  </div>
                </div>
              </div>
              <span className="text-sm font-medium text-gray-900">
                {options.quality_thresholds.markdown_threshold}
              </span>
            </div>
            <input
              type="range"
              min="1"
              max="10"
              step="0.5"
              value={options.quality_thresholds.markdown_threshold}
              onChange={(e) => updateQualityThreshold('markdown_threshold', parseFloat(e.target.value))}
              className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
            />
            <div className="flex justify-between text-xs text-gray-500 mt-1">
              <span>1</span>
              <span>10</span>
            </div>
          </div>
        </div>
      </div>

      {/* Advanced Settings Toggle */}
      <button
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="text-sm text-blue-600 hover:text-blue-700 font-medium"
      >
        {showAdvanced ? 'Hide' : 'Show'} Advanced Settings
      </button>

      {/* Advanced Settings */}
      {showAdvanced && (
        <div className="space-y-6 p-4 bg-gray-50 rounded-lg border border-gray-200">
          {/* OCR Settings */}
          <div>
            <h4 className="text-sm font-semibold text-gray-900 mb-3">OCR Settings</h4>
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="ocr-enabled"
                  checked={options.ocr_settings.enabled}
                  onChange={(e) => updateOCRSetting('enabled', e.target.checked)}
                  className="w-4 h-4 text-blue-600 rounded focus:ring-2 focus:ring-blue-500"
                />
                <label htmlFor="ocr-enabled" className="text-sm text-gray-700">
                  Enable OCR for image-based documents
                </label>
              </div>

              {options.ocr_settings.enabled && (
                <>
                  <div>
                    <label className="block text-sm text-gray-700 mb-1">Language</label>
                    <select
                      value={options.ocr_settings.language}
                      onChange={(e) => updateOCRSetting('language', e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="eng">English</option>
                      <option value="spa">Spanish</option>
                      <option value="fra">French</option>
                      <option value="deu">German</option>
                      <option value="chi_sim">Chinese (Simplified)</option>
                    </select>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-sm text-gray-700">Confidence Threshold</label>
                      <span className="text-sm font-medium text-gray-900">
                        {options.ocr_settings.confidence_threshold}
                      </span>
                    </div>
                    <input
                      type="range"
                      min="0.1"
                      max="1.0"
                      step="0.1"
                      value={options.ocr_settings.confidence_threshold}
                      onChange={(e) => updateOCRSetting('confidence_threshold', parseFloat(e.target.value))}
                      className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                    />
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Processing Settings */}
          <div>
            <h4 className="text-sm font-semibold text-gray-900 mb-3">Processing Settings</h4>
            <div className="space-y-3">
              <div>
                <label className="block text-sm text-gray-700 mb-1">
                  Chunk Size
                  <span className="text-xs text-gray-500 ml-1">(for vector embedding)</span>
                </label>
                <input
                  type="number"
                  min="100"
                  max="2000"
                  step="100"
                  value={options.processing_settings.chunk_size}
                  onChange={(e) => updateProcessingSetting('chunk_size', parseInt(e.target.value))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm text-gray-700 mb-1">
                  Chunk Overlap
                  <span className="text-xs text-gray-500 ml-1">(characters)</span>
                </label>
                <input
                  type="number"
                  min="0"
                  max="500"
                  step="50"
                  value={options.processing_settings.chunk_overlap}
                  onChange={(e) => updateProcessingSetting('chunk_overlap', parseInt(e.target.value))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm text-gray-700 mb-1">Max Retries</label>
                <input
                  type="number"
                  min="1"
                  max="5"
                  value={options.processing_settings.max_retries}
                  onChange={(e) => updateProcessingSetting('max_retries', parseInt(e.target.value))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

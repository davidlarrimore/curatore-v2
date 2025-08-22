// app/settings/page.tsx
'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Settings } from '@/components/Settings'
import { systemApi } from '@/lib/api'
import { QualityThresholds, OCRSettings } from '@/types'

export default function SettingsPage() {
  const router = useRouter()
  const [qualityThresholds, setQualityThresholds] = useState<QualityThresholds>({
    conversion: 70,
    clarity: 7,
    completeness: 7,
    relevance: 7,
    markdown: 7
  })
  const [ocrSettings, setOCRSettings] = useState<OCRSettings>({
    language: 'eng',
    psm: 3
  })
  const [autoOptimize, setAutoOptimize] = useState(true)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    loadSettings()
  }, [])

  const loadSettings = async () => {
    try {
      const config = await systemApi.getConfig()
      setQualityThresholds(config.quality_thresholds)
      setOCRSettings(config.ocr_settings)
      setAutoOptimize(config.auto_optimize)
    } catch (error) {
      console.error('Failed to load settings:', error)
    } finally {
      setIsLoading(false)
    }
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading settings...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow-sm border-b">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">⚙️ Settings</h1>
              <p className="text-gray-600 mt-1">Configure processing options and quality thresholds</p>
            </div>
            <button
              type="button"
              onClick={() => router.push('/process')}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              📚 Back to Processing
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Settings
          qualityThresholds={qualityThresholds}
          onQualityThresholdsChange={setQualityThresholds}
          ocrSettings={ocrSettings}
          onOCRSettingsChange={setOCRSettings}
          autoOptimize={autoOptimize}
          onAutoOptimizeChange={setAutoOptimize}
        />
      </div>
    </div>
  )
}
'use client'

import { ProcessingOptions } from '@/types'
import { HelpCircle } from 'lucide-react'
import { useState, useEffect } from 'react'
import { connectionsApi } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'

interface OptionsEditorProps {
  options: ProcessingOptions
  onChange: (options: ProcessingOptions) => void
}

interface ExtractionConnection {
  id: string
  name: string
  connection_type: string
  is_active: boolean
  is_default: boolean
}

export function OptionsEditor({ options, onChange }: OptionsEditorProps) {
  const { accessToken } = useAuth()
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [extractionConnections, setExtractionConnections] = useState<ExtractionConnection[]>([])
  const [loadingConnections, setLoadingConnections] = useState(true)

  // Fetch extraction connections on mount
  useEffect(() => {
    const fetchConnections = async () => {
      if (!accessToken) {
        setLoadingConnections(false)
        return
      }

      try {
        const response = await connectionsApi.listConnections(accessToken)
        // Filter for extraction type connections that are active
        const extractionConns = response.connections.filter(
          conn => conn.connection_type === 'extraction' && conn.is_active
        )
        setExtractionConnections(extractionConns)

        // Auto-select default connection if extraction_engine is not set
        if (!options.extraction_engine && extractionConns.length > 0) {
          const defaultConn = extractionConns.find(conn => conn.is_default)
          if (defaultConn) {
            onChange({ ...options, extraction_engine: defaultConn.id })
          } else if (extractionConns.length === 1) {
            // If only one connection, auto-select it
            onChange({ ...options, extraction_engine: extractionConns[0].id })
          }
        }
      } catch (error) {
        console.error('Failed to fetch extraction connections:', error)
      } finally {
        setLoadingConnections(false)
      }
    }

    fetchConnections()
  }, [accessToken])

  const updateOCRSetting = (key: keyof ProcessingOptions['ocr_settings'], value: any) => {
    onChange({
      ...options,
      ocr_settings: {
        ...options.ocr_settings,
        [key]: value
      }
    })
  }

  return (
    <div className="space-y-6">
      {/* Extraction Engine Selection */}
      <div className="flex items-center justify-between p-4 bg-gray-50 border border-gray-200 rounded-lg">
        <div className="flex items-center gap-2">
          <label htmlFor="extraction-engine" className="text-sm font-medium text-gray-900">
            Extraction Engine
          </label>
          <div className="group relative">
            <HelpCircle className="w-4 h-4 text-gray-400 cursor-help" />
            <div className="absolute right-0 bottom-full mb-2 hidden group-hover:block w-64 p-2 bg-gray-900 text-white text-xs rounded shadow-lg z-10">
              Choose which extraction service to use for this job. Services are configured in the Connections page.
            </div>
          </div>
        </div>
        <select
          id="extraction-engine"
          value={options.extraction_engine ?? ''}
          onChange={(e) => onChange({ ...options, extraction_engine: e.target.value })}
          disabled={loadingConnections}
          className="px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loadingConnections ? (
            <option value="">Loading connections...</option>
          ) : extractionConnections.length === 0 ? (
            <option value="">No extraction services configured</option>
          ) : (
            <>
              <option value="">Select extraction service...</option>
              {extractionConnections.map((conn) => (
                <option key={conn.id} value={conn.id}>
                  {conn.name}{conn.is_default ? ' (Default)' : ''}
                </option>
              ))}
            </>
          )}
        </select>
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
                    <label className="block text-sm text-gray-700 mb-1">PSM Mode</label>
                    <select
                      value={options.ocr_settings.psm}
                      onChange={(e) => updateOCRSetting('psm', parseInt(e.target.value))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="3">Auto (Default)</option>
                      <option value="4">Single Column</option>
                      <option value="6">Uniform Block</option>
                      <option value="11">Sparse Text</option>
                    </select>
                  </div>
            </div>
          </div>

        </div>
      )}
    </div>
  )
}

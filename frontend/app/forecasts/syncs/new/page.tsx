'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { forecastsApi, ForecastSyncCreateRequest } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  TrendingUp,
  ChevronLeft,
  AlertTriangle,
  Loader2,
  Building2,
  Globe,
  FileSpreadsheet,
  Check,
  X,
  Plus,
  Hash,
  Filter,
} from 'lucide-react'

// AG Agency options with IDs from the API
const AG_AGENCIES = [
  { id: 2, name: 'General Services Administration' },
  { id: 4, name: 'Department of the Interior' },
  { id: 5, name: 'Department of Labor' },
  { id: 6, name: 'Small Business Administration' },
  { id: 7, name: 'Office of Personnel Management' },
  { id: 8, name: 'Department of Veterans Affairs' },
  { id: 13, name: 'Department of Commerce' },
  { id: 14, name: 'Social Security Administration' },
  { id: 15, name: 'Department of Health and Human Services' },
  { id: 17, name: 'Nuclear Regulatory Commission' },
  { id: 19, name: 'Federal Communications Commission' },
  { id: 20, name: 'Department of Transportation' },
  { id: 21, name: 'Department of State' },
]

// Source type options
const sourceOptions = [
  {
    id: 'ag',
    name: 'Acquisition Gateway (AG)',
    description: 'GSA multi-agency acquisition forecasts from over 20 federal agencies',
    icon: Building2,
    color: 'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400',
    features: ['Multi-agency data', 'NAICS filtering', 'Award status tracking'],
  },
  {
    id: 'apfs',
    name: 'DHS APFS',
    description: 'Department of Homeland Security Acquisition Planning Forecast System',
    icon: Globe,
    color: 'bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400',
    features: ['DHS components', 'Contract vehicles', 'Small business programs'],
  },
  {
    id: 'state',
    name: 'State Department',
    description: 'Department of State procurement forecast from published Excel files',
    icon: FileSpreadsheet,
    color: 'bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400',
    features: ['International operations', 'Monthly updates', 'Excel-based'],
  },
]

const frequencyOptions = [
  { id: 'manual', name: 'Manual', description: 'Sync only when manually triggered' },
  { id: 'hourly', name: 'Hourly', description: 'Sync every hour' },
  { id: 'daily', name: 'Daily', description: 'Sync once per day' },
]

function NewSyncForm() {
  const { token } = useAuth()
  const router = useRouter()
  const [step, setStep] = useState(1)
  const [selectedSource, setSelectedSource] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [frequency, setFrequency] = useState('manual')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // AG-specific filter state
  const [selectedAgencyId, setSelectedAgencyId] = useState<number | null>(null)
  const [naicsCodes, setNaicsCodes] = useState<string[]>([])
  const [newNaicsCode, setNewNaicsCode] = useState('')

  // Add NAICS code(s) - accepts comma-separated input like SAM.gov
  const addNaicsCode = () => {
    const input = newNaicsCode.trim()
    if (!input) return

    // Split by comma, trim each, filter empty and duplicates
    const newCodes = input
      .split(',')
      .map(c => c.trim())
      .filter(c => c && !naicsCodes.includes(c))

    if (newCodes.length > 0) {
      setNaicsCodes([...naicsCodes, ...newCodes])
    }
    setNewNaicsCode('')
  }

  // Remove NAICS code
  const removeNaicsCode = (code: string) => {
    setNaicsCodes(naicsCodes.filter(c => c !== code))
  }

  // Handle NAICS input key press
  const handleNaicsKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      addNaicsCode()
    }
  }

  const handleCreate = async () => {
    if (!token || !selectedSource || !name.trim()) return

    setSubmitting(true)
    setError(null)

    try {
      // Build filter_config based on source type
      let filterConfig: Record<string, any> = {}

      // AG-specific: agency filter (server-side)
      if (selectedSource === 'ag' && selectedAgencyId) {
        filterConfig.agency_ids = [selectedAgencyId]
      }

      // NAICS codes for client-side filtering - available for ALL source types
      if (naicsCodes.length > 0) {
        filterConfig.naics_codes = naicsCodes
      }

      const data: ForecastSyncCreateRequest = {
        name: name.trim(),
        source_type: selectedSource as 'ag' | 'apfs' | 'state',
        sync_frequency: frequency as 'manual' | 'hourly' | 'daily',
        filter_config: filterConfig,
        automation_config: {},
      }

      const sync = await forecastsApi.createSync(token, data)
      router.push(`/forecasts/syncs/${sync.id}`)
    } catch (err: any) {
      setError(err.message || 'Failed to create sync')
      setSubmitting(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link
          href="/forecasts/syncs"
          className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
        >
          <ChevronLeft className="w-5 h-5 text-gray-500" />
        </Link>
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">
            Create Forecast Sync
          </h1>
          <p className="text-gray-500 dark:text-gray-400">
            Connect to a federal acquisition forecast data source
          </p>
        </div>
      </div>

      {/* Progress */}
      <div className="flex items-center gap-4">
        <div className={`flex items-center gap-2 ${step >= 1 ? 'text-emerald-600' : 'text-gray-400'}`}>
          <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
            step >= 1 ? 'bg-emerald-100 dark:bg-emerald-900/30' : 'bg-gray-100 dark:bg-gray-800'
          }`}>
            {step > 1 ? <Check className="w-4 h-4" /> : '1'}
          </div>
          <span className="font-medium">Select Source</span>
        </div>
        <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
        <div className={`flex items-center gap-2 ${step >= 2 ? 'text-emerald-600' : 'text-gray-400'}`}>
          <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
            step >= 2 ? 'bg-emerald-100 dark:bg-emerald-900/30' : 'bg-gray-100 dark:bg-gray-800'
          }`}>
            2
          </div>
          <span className="font-medium">Configure</span>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 rounded-lg flex items-center gap-2 text-red-600 dark:text-red-400">
          <AlertTriangle className="w-5 h-5" />
          <span>{error}</span>
        </div>
      )}

      {/* Step 1: Select Source */}
      {step === 1 && (
        <div className="space-y-4">
          <h2 className="text-lg font-medium text-gray-900 dark:text-white">
            Choose a data source
          </h2>
          <div className="grid gap-4">
            {sourceOptions.map((source) => {
              const Icon = source.icon
              const isSelected = selectedSource === source.id

              return (
                <button
                  key={source.id}
                  onClick={() => setSelectedSource(source.id)}
                  className={`w-full p-6 rounded-xl border-2 text-left transition-all ${
                    isSelected
                      ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20'
                      : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                  }`}
                >
                  <div className="flex items-start gap-4">
                    <div className={`p-3 rounded-lg ${source.color}`}>
                      <Icon className="w-6 h-6" />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center justify-between">
                        <h3 className="font-semibold text-gray-900 dark:text-white">
                          {source.name}
                        </h3>
                        {isSelected && (
                          <div className="w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center">
                            <Check className="w-3 h-3 text-white" />
                          </div>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                        {source.description}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {source.features.map((feature) => (
                          <span
                            key={feature}
                            className="px-2 py-1 text-xs rounded bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400"
                          >
                            {feature}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>

          <div className="flex justify-end pt-4">
            <Button
              variant="primary"
              onClick={() => setStep(2)}
              disabled={!selectedSource}
            >
              Continue
            </Button>
          </div>
        </div>
      )}

      {/* Step 2: Configure */}
      {step === 2 && (
        <div className="space-y-6">
          <h2 className="text-lg font-medium text-gray-900 dark:text-white">
            Configure your sync
          </h2>

          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 space-y-6">
            {/* Name */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Sync Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={`My ${sourceOptions.find(s => s.id === selectedSource)?.name} Sync`}
                className="w-full px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
              />
            </div>

            {/* Frequency */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Sync Frequency
              </label>
              <div className="grid grid-cols-3 gap-3">
                {frequencyOptions.map((option) => (
                  <button
                    key={option.id}
                    onClick={() => setFrequency(option.id)}
                    className={`p-4 rounded-lg border-2 text-left transition-all ${
                      frequency === option.id
                        ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20'
                        : 'border-gray-200 dark:border-gray-700 hover:border-gray-300'
                    }`}
                  >
                    <div className="font-medium text-gray-900 dark:text-white">
                      {option.name}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                      {option.description}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Filter Options - show for all source types */}
            <div className="space-y-6 pt-6 border-t border-gray-200 dark:border-gray-700">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                <Filter className="w-4 h-4" />
                Filter Options
              </h3>

              {/* AG-specific Agency Filter */}
              {selectedSource === 'ag' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Agency (Optional)
                  </label>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
                    Select a specific agency to filter forecasts, or leave blank for all agencies.
                  </p>
                  <select
                    value={selectedAgencyId || ''}
                    onChange={(e) => setSelectedAgencyId(e.target.value ? parseInt(e.target.value) : null)}
                    className="w-full px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
                  >
                    <option value="">All Agencies</option>
                    {AG_AGENCIES.map((agency) => (
                      <option key={agency.id} value={agency.id}>
                        {agency.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* NAICS Filter - available for all source types */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  NAICS Codes (Optional)
                </label>
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
                  Filter by standard NAICS codes (e.g., 541511, 541512). Enter codes separated by commas.
                  {selectedSource === 'ag' && ' All agency forecasts are pulled, then filtered to show only matching NAICS codes.'}
                  {selectedSource === 'apfs' && ' All DHS forecasts are pulled, then filtered to show only matching NAICS codes.'}
                  {selectedSource === 'state' && ' All State Dept forecasts are parsed, then filtered to show only matching NAICS codes.'}
                </p>

                {/* Selected NAICS codes */}
                {naicsCodes.length > 0 && (
                  <div className="flex flex-wrap gap-2 mb-3">
                    {naicsCodes.map((code) => (
                      <span
                        key={code}
                        className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 text-sm"
                      >
                        <Hash className="w-3 h-3" />
                        {code}
                        <button
                          onClick={() => removeNaicsCode(code)}
                          className="ml-1 hover:text-emerald-900 dark:hover:text-emerald-100"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                )}

                {/* Add NAICS code input */}
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={newNaicsCode}
                    onChange={(e) => setNewNaicsCode(e.target.value)}
                    onKeyPress={handleNaicsKeyPress}
                    placeholder="e.g., 541511, 541512"
                    className="flex-1 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
                  />
                  <Button
                    variant="outline"
                    onClick={addNaicsCode}
                    disabled={!newNaicsCode.trim()}
                  >
                    <Plus className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </div>

            {/* Source Info */}
            <div className="p-4 rounded-lg bg-gray-50 dark:bg-gray-700/50">
              <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                <TrendingUp className="w-4 h-4" />
                <span>
                  Source: <strong className="text-gray-900 dark:text-white">
                    {sourceOptions.find(s => s.id === selectedSource)?.name}
                  </strong>
                </span>
              </div>
              {selectedSource === 'ag' && (selectedAgencyId || naicsCodes.length > 0) ? (
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {selectedAgencyId && `Agency: ${AG_AGENCIES.find(a => a.id === selectedAgencyId)?.name}`}
                  {selectedAgencyId && naicsCodes.length > 0 && ' • '}
                  {naicsCodes.length > 0 && `${naicsCodes.length} NAICS filter${naicsCodes.length > 1 ? 's' : ''}`}
                </p>
              ) : (
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {selectedSource === 'ag'
                    ? 'No filters applied - will sync all forecasts from all agencies.'
                    : 'You can configure additional filters after creating the sync.'
                  }
                </p>
              )}
            </div>
          </div>

          <div className="flex justify-between pt-4">
            <Button variant="outline" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button
              variant="primary"
              onClick={handleCreate}
              disabled={!name.trim() || submitting}
            >
              {submitting ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Creating...
                </>
              ) : (
                'Create Sync'
              )}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function NewForecastSyncPage() {
  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <NewSyncForm />
        </div>
      </div>
    </ProtectedRoute>
  )
}

'use client'

import { useState, useEffect } from 'react'
import { useRouter, useParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { useOrgUrl } from '@/lib/org-url-context'
import { forecastsApi, ForecastSync } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import {
  ChevronLeft,
  AlertTriangle,
  Loader2,
  Save,
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

const frequencyOptions: Array<{ id: 'manual' | 'hourly' | 'daily', name: string, description: string }> = [
  { id: 'manual', name: 'Manual', description: 'Sync only when manually triggered' },
  { id: 'hourly', name: 'Hourly', description: 'Sync every hour' },
  { id: 'daily', name: 'Daily', description: 'Sync once per day' },
]

// Source type display config
const sourceTypeConfig: Record<string, { label: string; color: string }> = {
  ag: {
    label: 'Acquisition Gateway',
    color: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
  },
  apfs: {
    label: 'DHS APFS',
    color: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400',
  },
  state: {
    label: 'State Dept',
    color: 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400',
  },
}

function EditSyncForm() {
  const { token } = useAuth()
  const { orgSlug } = useOrgUrl()
  const router = useRouter()
  const params = useParams()
  const syncId = params.id as string

  // Helper for org-scoped URLs
  const orgUrl = (path: string) => `/orgs/${orgSlug}${path}`

  const [sync, setSync] = useState<ForecastSync | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Form state
  const [name, setName] = useState('')
  const [frequency, setFrequency] = useState<'manual' | 'hourly' | 'daily'>('manual')
  const [selectedAgencyId, setSelectedAgencyId] = useState<number | null>(null)
  const [naicsCodes, setNaicsCodes] = useState<string[]>([])
  const [newNaicsCode, setNewNaicsCode] = useState('')

  useEffect(() => {
    loadSync()
  }, [token, syncId])

  const loadSync = async () => {
    if (!token || !syncId) return
    setLoading(true)
    setError(null)

    try {
      const syncData = await forecastsApi.getSync(token, syncId)
      setSync(syncData)

      // Populate form with existing values
      setName(syncData.name)
      setFrequency(syncData.sync_frequency as 'manual' | 'hourly' | 'daily')

      const filterConfig = syncData.filter_config || {}
      if (filterConfig.agency_ids && (filterConfig.agency_ids as number[]).length > 0) {
        setSelectedAgencyId((filterConfig.agency_ids as number[])[0])
      }
      if (filterConfig.naics_codes) {
        setNaicsCodes(filterConfig.naics_codes as string[])
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load sync'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  // Add NAICS code(s) - accepts comma-separated input
  const addNaicsCode = () => {
    const input = newNaicsCode.trim()
    if (!input) return

    const newCodes = input
      .split(',')
      .map(c => c.trim())
      .filter(c => c && !naicsCodes.includes(c))

    if (newCodes.length > 0) {
      setNaicsCodes([...naicsCodes, ...newCodes])
    }
    setNewNaicsCode('')
  }

  const removeNaicsCode = (code: string) => {
    setNaicsCodes(naicsCodes.filter(c => c !== code))
  }

  const handleNaicsKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      addNaicsCode()
    }
  }

  const handleSave = async () => {
    if (!token || !sync || !name.trim()) return

    setSaving(true)
    setError(null)

    try {
      // Build filter_config
      const filterConfig: Record<string, number[] | string[]> = {}

      // AG-specific: agency filter
      if (sync.source_type === 'ag' && selectedAgencyId) {
        filterConfig.agency_ids = [selectedAgencyId]
      }

      // NAICS codes for all source types
      if (naicsCodes.length > 0) {
        filterConfig.naics_codes = naicsCodes
      }

      await forecastsApi.updateSync(token, sync.id, {
        name: name.trim(),
        sync_frequency: frequency,
        filter_config: filterConfig,
      })

      router.push(orgUrl(`/syncs/forecasts/syncs/${sync.id}`))
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to save sync'
      setError(message)
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-emerald-500" />
      </div>
    )
  }

  if (error && !sync) {
    return (
      <div className="p-6 bg-red-50 dark:bg-red-900/20 rounded-lg">
        <div className="flex items-center gap-2 text-red-600 dark:text-red-400">
          <AlertTriangle className="w-5 h-5" />
          <span>{error}</span>
        </div>
        <Link href={orgUrl('/syncs/forecasts/syncs')}>
          <Button variant="outline" className="mt-4">
            Back to Syncs
          </Button>
        </Link>
      </div>
    )
  }

  if (!sync) return null

  const config = sourceTypeConfig[sync.source_type]

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link
          href={orgUrl(`/syncs/forecasts/syncs/${sync.id}`)}
          className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
        >
          <ChevronLeft className="w-5 h-5 text-gray-500" />
        </Link>
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">
              Edit Sync
            </h1>
            <span className={`px-2 py-1 text-xs font-medium rounded ${config?.color || 'bg-gray-100 text-gray-800'}`}>
              {config?.label || sync.source_type.toUpperCase()}
            </span>
          </div>
          <p className="text-gray-500 dark:text-gray-400">
            Update sync configuration and filters
          </p>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 rounded-lg flex items-center gap-2 text-red-600 dark:text-red-400">
          <AlertTriangle className="w-5 h-5" />
          <span>{error}</span>
        </div>
      )}

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

        {/* Filter Options */}
        <div className="space-y-6 pt-6 border-t border-gray-200 dark:border-gray-700">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <Filter className="w-4 h-4" />
            Filter Options
          </h3>

          {/* AG-specific Agency Filter */}
          {sync.source_type === 'ag' && (
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
              Forecasts are pulled from the source, then filtered to show only matching NAICS codes.
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
      </div>

      {/* Actions */}
      <div className="flex justify-end gap-3">
        <Link href={orgUrl(`/syncs/forecasts/syncs/${sync.id}`)}>
          <Button variant="outline">Cancel</Button>
        </Link>
        <Button
          variant="primary"
          onClick={handleSave}
          disabled={!name.trim() || saving}
        >
          {saving ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Saving...
            </>
          ) : (
            <>
              <Save className="w-4 h-4 mr-2" />
              Save Changes
            </>
          )}
        </Button>
      </div>
    </div>
  )
}

export default function EditForecastSyncPage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <EditSyncForm />
      </div>
    </div>
  )
}

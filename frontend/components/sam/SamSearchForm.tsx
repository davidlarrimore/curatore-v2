'use client'

import { useState, FormEvent, useEffect, useRef } from 'react'
import { useAuth } from '@/lib/auth-context'
import { samApi, SamSearch, SamPreviewResult } from '@/lib/api'
import { Button } from '../ui/Button'
import {
  AlertTriangle,
  Loader2,
  X,
  Search,
  CheckCircle,
  Building2,
  Plus,
  FlaskConical,
} from 'lucide-react'

interface SamSearchFormProps {
  search?: SamSearch | null
  onSuccess: () => void
  onCancel: () => void
}

export default function SamSearchForm({
  search,
  onSuccess,
  onCancel,
}: SamSearchFormProps) {
  const { token } = useAuth()

  // Basic fields
  const [name, setName] = useState(search?.name || '')
  const [description, setDescription] = useState(search?.description || '')
  const [pullFrequency, setPullFrequency] = useState<'manual' | 'hourly' | 'daily'>(search?.pull_frequency || 'manual')

  // Search config fields
  const [naicsCodes, setNaicsCodes] = useState<string[]>(
    search?.search_config?.naics_codes || []
  )
  const [newNaics, setNewNaics] = useState('')
  const [pscCodes, setPscCodes] = useState<string[]>(
    search?.search_config?.psc_codes || []
  )
  const [newPsc, setNewPsc] = useState('')
  const [keyword, setKeyword] = useState(search?.search_config?.keyword || '')
  const [setAsideCodes, setSetAsideCodes] = useState<string[]>(
    search?.search_config?.set_aside_codes || []
  )
  const [noticeTypes, setNoticeTypes] = useState<string[]>(
    search?.search_config?.notice_types || ['o', 'p', 'k']
  )
  const [activeOnly, setActiveOnly] = useState(
    search?.search_config?.active_only !== false
  )
  const [downloadAttachments, setDownloadAttachments] = useState(
    search?.search_config?.download_attachments !== false
  )
  const [dateRange, setDateRange] = useState(
    search?.search_config?.date_range || 'last_30_days'
  )
  const [department, setDepartment] = useState(
    search?.search_config?.department || ''
  )

  // Date range options
  const dateRangeOptions = [
    { value: 'today', label: 'Today' },
    { value: 'yesterday', label: 'Yesterday' },
    { value: 'last_7_days', label: 'Last 7 Days' },
    { value: 'last_30_days', label: 'Last 30 Days' },
    { value: 'last_90_days', label: 'Last 90 Days' },
  ]

  // Form state
  const [isLoading, setIsLoading] = useState(false)
  const [isTesting, setIsTesting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<SamPreviewResult[] | null>(null)
  const [testTotal, setTestTotal] = useState<number | null>(null)

  // Track if component has mounted (to skip effect on initial render)
  const hasMounted = useRef(false)

  // Modal effects: lock body scroll and handle Escape key
  useEffect(() => {
    // Lock body scroll
    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    // Handle Escape key
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isLoading) {
        onCancel()
      }
    }
    document.addEventListener('keydown', handleEscape)

    return () => {
      document.body.style.overflow = originalOverflow
      document.removeEventListener('keydown', handleEscape)
    }
  }, [onCancel, isLoading])

  // Reset test results when search configuration changes (not name/description)
  // Skip on initial mount - only reset when user actually changes something
  useEffect(() => {
    if (!hasMounted.current) {
      hasMounted.current = true
      return
    }
    // User changed a config option, clear previous test results
    setTestResults(null)
    setTestTotal(null)
  }, [
    naicsCodes,
    pscCodes,
    keyword,
    setAsideCodes,
    noticeTypes,
    activeOnly,
    downloadAttachments,
    dateRange,
    department,
  ])

  // Notice type options (SAM.gov API v2 ptype values)
  // See: https://open.gsa.gov/api/opportunities-api/
  const noticeTypeOptions = [
    { value: 'o', label: 'Combined Synopsis/Solicitation' },
    { value: 'p', label: 'Presolicitation' },
    { value: 'r', label: 'Solicitation' },
    { value: 's', label: 'Special Notice' },
    { value: 'k', label: 'Sources Sought' },
    { value: 'i', label: 'Intent to Bundle' },
    { value: 'a', label: 'Award Notice' },
    { value: 'g', label: 'Sale of Surplus Property' },
  ]

  // Set-aside options
  const setAsideOptions = [
    { value: 'SBA', label: 'Small Business' },
    { value: '8A', label: '8(a) Program' },
    { value: 'HUBZ', label: 'HUBZone' },
    { value: 'SDVOSB', label: 'Service-Disabled Veteran' },
    { value: 'WOSB', label: 'Women-Owned Small Business' },
    { value: 'EDWOSB', label: 'Economically Disadvantaged WOSB' },
  ]

  // Build search config
  const buildSearchConfig = () => ({
    naics_codes: naicsCodes,
    psc_codes: pscCodes,
    keyword: keyword || undefined,
    set_aside_codes: setAsideCodes,
    notice_types: noticeTypes,
    active_only: activeOnly,
    download_attachments: downloadAttachments,
    date_range: dateRange,
    department: department || undefined,
  })

  // Add NAICS code
  const addNaicsCode = () => {
    const code = newNaics.trim()
    if (code && !naicsCodes.includes(code)) {
      setNaicsCodes([...naicsCodes, code])
      setNewNaics('')
    }
  }

  // Remove NAICS code
  const removeNaicsCode = (code: string) => {
    setNaicsCodes(naicsCodes.filter((c) => c !== code))
  }

  // Add PSC code
  const addPscCode = () => {
    const code = newPsc.trim().toUpperCase()
    if (code && !pscCodes.includes(code)) {
      setPscCodes([...pscCodes, code])
      setNewPsc('')
    }
  }

  // Remove PSC code
  const removePscCode = (code: string) => {
    setPscCodes(pscCodes.filter((c) => c !== code))
  }

  // Toggle notice type
  const toggleNoticeType = (type: string) => {
    if (noticeTypes.includes(type)) {
      setNoticeTypes(noticeTypes.filter((t) => t !== type))
    } else {
      setNoticeTypes([...noticeTypes, type])
    }
  }

  // Toggle set-aside
  const toggleSetAside = (code: string) => {
    if (setAsideCodes.includes(code)) {
      setSetAsideCodes(setAsideCodes.filter((c) => c !== code))
    } else {
      setSetAsideCodes([...setAsideCodes, code])
    }
  }

  // Test search configuration
  const handleTest = async () => {
    if (!token) {
      console.log('[SamSearchForm] handleTest: No token, aborting')
      return
    }

    console.log('[SamSearchForm] handleTest: Starting test...')
    setIsTesting(true)
    setError(null)

    try {
      const searchConfig = buildSearchConfig()
      console.log('[SamSearchForm] handleTest: Search config:', searchConfig)

      const result = await samApi.previewSearch(token, {
        search_config: searchConfig,
        limit: 10,
      })

      console.log('[SamSearchForm] handleTest: API result:', result)

      if (!result.success) {
        console.log('[SamSearchForm] handleTest: API returned success=false:', result.message)
        setError(result.message || 'Test failed')
        return
      }

      const results = result.sample_results || []
      const total = result.total_matching || 0
      console.log('[SamSearchForm] handleTest: Setting results:', { results, total })
      setTestResults(results)
      setTestTotal(total)
    } catch (err: any) {
      console.error('[SamSearchForm] handleTest: Error:', err)
      setError(err.message || 'Failed to test search')
    } finally {
      setIsTesting(false)
    }
  }

  // Submit form
  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!token || !name) return

    setIsLoading(true)
    setError(null)

    try {
      const data = {
        name,
        description: description || undefined,
        search_config: buildSearchConfig(),
        pull_frequency: pullFrequency,
      }

      if (search?.id) {
        // Edit existing search
        await samApi.updateSearch(token, search.id, data)
      } else {
        // Create new search (including cloned searches)
        await samApi.createSearch(token, data)
      }

      onSuccess()
    } catch (err: any) {
      setError(err.message || 'Failed to save search')
    } finally {
      setIsLoading(false)
    }
  }

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'N/A'
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm transition-opacity"
        onClick={onCancel}
      />

      {/* Modal container */}
      <div className="flex min-h-full items-start justify-center pt-8 pb-4 px-4">
        <div
          className="relative bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl shadow-2xl overflow-hidden w-full max-w-2xl max-h-[85vh] flex flex-col animate-in fade-in zoom-in-95 duration-200"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Gradient header */}
          <div className="relative bg-gradient-to-r from-blue-600 via-indigo-600 to-blue-600 px-6 py-5 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-white">
              {search?.id ? 'Edit SAM.gov Search' : 'Create SAM.gov Search'}
            </h2>
            <p className="text-blue-100 text-sm mt-0.5">
              Configure your federal opportunity search parameters
            </p>
          </div>
          <button
            onClick={onCancel}
            className="p-2 rounded-lg text-white/80 hover:text-white hover:bg-white/10 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

      </div>

      <form onSubmit={handleSubmit} className="p-6 overflow-y-auto flex-1">
        {error && (
          <div className="mb-6 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-red-600 dark:text-red-400" />
              <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          </div>
        )}

        <div className="space-y-6">
            {/* Basic Info */}
            <div className="space-y-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 flex items-center gap-2">
                <Building2 className="w-4 h-4" />
                Basic Information
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Search Name *
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g., IT Services Opportunities"
                    required
                    className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Pull Frequency
                  </label>
                  <select
                    value={pullFrequency}
                    onChange={(e) => setPullFrequency(e.target.value as 'manual' | 'hourly' | 'daily')}
                    className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
                  >
                    <option value="manual">Manual</option>
                    <option value="daily">Daily</option>
                    <option value="hourly">Hourly</option>
                  </select>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Brief description of this search..."
                  rows={2}
                  className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 resize-none"
                />
              </div>
            </div>

            {/* Search Filters */}
            <div className="space-y-4 pt-4 border-t border-gray-200 dark:border-gray-700">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 flex items-center gap-2">
                <Search className="w-4 h-4" />
                Search Filters
              </h3>

              {/* NAICS Codes */}
              <div className="space-y-2">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  NAICS Codes
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={newNaics}
                    onChange={(e) => setNewNaics(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addNaicsCode())}
                    placeholder="e.g., 541512"
                    className="flex-1 px-4 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
                  />
                  <Button type="button" variant="secondary" onClick={addNaicsCode}>
                    <Plus className="w-4 h-4" />
                  </Button>
                </div>
                {naicsCodes.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {naicsCodes.map((code) => (
                      <span
                        key={code}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                      >
                        {code}
                        <button
                          type="button"
                          onClick={() => removeNaicsCode(code)}
                          className="ml-1 hover:text-blue-900 dark:hover:text-blue-100"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* PSC Codes */}
              <div className="space-y-2">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  PSC Codes
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={newPsc}
                    onChange={(e) => setNewPsc(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addPscCode())}
                    placeholder="e.g., D302"
                    className="flex-1 px-4 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
                  />
                  <Button type="button" variant="secondary" onClick={addPscCode}>
                    <Plus className="w-4 h-4" />
                  </Button>
                </div>
                {pscCodes.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {pscCodes.map((code) => (
                      <span
                        key={code}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300"
                      >
                        {code}
                        <button
                          type="button"
                          onClick={() => removePscCode(code)}
                          className="ml-1 hover:text-purple-900 dark:hover:text-purple-100"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Keyword */}
              <div className="space-y-1.5">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Keyword Search
                </label>
                <input
                  type="text"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  placeholder="e.g., software development"
                  className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
                />
              </div>

              {/* Department / Agency */}
              <div className="space-y-1.5">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Department / Agency
                </label>
                <input
                  type="text"
                  value={department}
                  onChange={(e) => setDepartment(e.target.value)}
                  placeholder="e.g., HOMELAND SECURITY, DEPARTMENT OF"
                  className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
                />
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Filter by organization name (partial match supported)
                </p>
              </div>

              {/* Date Range */}
              <div className="space-y-1.5">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Posted Date Range
                </label>
                <select
                  value={dateRange}
                  onChange={(e) => setDateRange(e.target.value)}
                  className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
                >
                  {dateRangeOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Filter opportunities by when they were posted
                </p>
              </div>

              {/* Notice Types */}
              <div className="space-y-2">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Notice Types
                </label>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                  {noticeTypeOptions.map((option) => (
                    <label
                      key={option.value}
                      className={`flex items-center p-2.5 border rounded-lg cursor-pointer transition-all ${
                        noticeTypes.includes(option.value)
                          ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                          : 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={noticeTypes.includes(option.value)}
                        onChange={() => toggleNoticeType(option.value)}
                        className="sr-only"
                      />
                      <span className="text-xs text-gray-700 dark:text-gray-300">
                        {option.label}
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              {/* Set-Aside */}
              <div className="space-y-2">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Set-Aside Types
                </label>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                  {setAsideOptions.map((option) => (
                    <label
                      key={option.value}
                      className={`flex items-center p-2.5 border rounded-lg cursor-pointer transition-all ${
                        setAsideCodes.includes(option.value)
                          ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20'
                          : 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={setAsideCodes.includes(option.value)}
                        onChange={() => toggleSetAside(option.value)}
                        className="sr-only"
                      />
                      <span className="text-xs text-gray-700 dark:text-gray-300">
                        {option.label}
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              {/* Toggles */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <label className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-700 rounded-xl cursor-pointer">
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">Active Only</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Only show active opportunities</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={activeOnly}
                    onChange={(e) => setActiveOnly(e.target.checked)}
                    className="w-5 h-5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                </label>

                <label className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-700 rounded-xl cursor-pointer">
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">Download Attachments</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Auto-download opportunity files</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={downloadAttachments}
                    onChange={(e) => setDownloadAttachments(e.target.checked)}
                    className="w-5 h-5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                </label>
              </div>
            </div>

            {/* Test Results Section - shown inline when test results exist */}
            {testResults !== null && (
              <div className="space-y-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 flex items-center gap-2">
                  <FlaskConical className="w-4 h-4" />
                  Test Results
                </h3>

                {/* Results Summary */}
                <div className="p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-100 dark:border-blue-900/50 rounded-lg">
                  <div className="flex items-center gap-3">
                    <CheckCircle className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                    <div>
                      <p className="text-sm font-medium text-blue-800 dark:text-blue-200">
                        Found {testTotal?.toLocaleString()} matching opportunities
                      </p>
                      {testTotal !== null && testTotal > 10 && (
                        <p className="text-xs text-blue-600 dark:text-blue-400">
                          Showing first 10 of {testTotal.toLocaleString()} results
                        </p>
                      )}
                    </div>
                  </div>
                </div>

                {/* Results Table */}
                {testResults.length > 0 ? (
                  <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                    <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                      <thead className="bg-gray-50 dark:bg-gray-900/50">
                        <tr>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Title
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Solicitation #
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Agency
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Posted
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Due
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                        {testResults.map((result, idx) => (
                          <tr key={result.notice_id || idx} className="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                            <td className="px-3 py-2 text-sm text-gray-900 dark:text-white">
                              <div className="max-w-[200px] truncate" title={result.title}>
                                {result.title}
                              </div>
                              {result.naics_code && (
                                <span className="mt-0.5 inline-block px-1.5 py-0.5 text-xs bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded">
                                  {result.naics_code}
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-2 text-xs font-mono text-gray-600 dark:text-gray-400">
                              {result.solicitation_number || '-'}
                            </td>
                            <td className="px-3 py-2 text-xs text-gray-600 dark:text-gray-400">
                              <div className="max-w-[120px] truncate" title={result.agency || ''}>
                                {result.agency || '-'}
                              </div>
                            </td>
                            <td className="px-3 py-2 text-xs text-gray-600 dark:text-gray-400 whitespace-nowrap">
                              {formatDate(result.posted_date)}
                            </td>
                            <td className="px-3 py-2 text-xs text-gray-600 dark:text-gray-400 whitespace-nowrap">
                              {formatDate(result.response_deadline)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="p-4 text-center text-sm text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-900/50 rounded-lg">
                    No results found matching your criteria.
                  </div>
                )}
              </div>
            )}

            {/* Actions */}
            <div className="flex items-center justify-end gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
              <button
                type="button"
                onClick={onCancel}
                className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              >
                Cancel
              </button>
              <Button
                type="button"
                variant="secondary"
                onClick={handleTest}
                disabled={isTesting || !name}
                className="gap-2"
              >
                {isTesting ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <FlaskConical className="w-4 h-4" />
                )}
                Test
              </Button>
              <Button
                type="submit"
                disabled={isLoading || !name}
                className="gap-2"
              >
                {isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
                {search?.id ? 'Update Search' : 'Create Search'}
              </Button>
            </div>
          </div>
      </form>
        </div>
      </div>
    </div>
  )
}

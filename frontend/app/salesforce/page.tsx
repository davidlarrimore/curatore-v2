'use client'

import { useState, useEffect, useCallback, useRef, DragEvent } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { useActiveJobs } from '@/lib/context-shims'
import { useJobProgressByType } from '@/lib/useJobProgress'
import { JobProgressPanelByType } from '@/components/ui/JobProgressPanel'
import { salesforceApi, SalesforceStats } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  Database,
  RefreshCw,
  AlertTriangle,
  Building2,
  Users,
  Target,
  Upload,
  ArrowRight,
  DollarSign,
  TrendingUp,
  CheckCircle2,
  FileUp,
  FileArchive,
  ExternalLink,
} from 'lucide-react'
import clsx from 'clsx'

export default function SalesforceDashboardPage() {
  return (
    <ProtectedRoute>
      <SalesforceDashboardContent />
    </ProtectedRoute>
  )
}

function SalesforceDashboardContent() {
  const router = useRouter()
  const { token } = useAuth()
  const { addJob } = useActiveJobs()
  const fileInputRef = useRef<HTMLInputElement>(null)

  // State
  const [stats, setStats] = useState<SalesforceStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState('')
  const [uploadMessage, setUploadMessage] = useState('')
  const [lastRunId, setLastRunId] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)

  // Track Salesforce import jobs and auto-refresh on completion
  useJobProgressByType('salesforce_import', { onComplete: () => loadData() })

  // Load data
  const loadData = useCallback(async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const dashboardStats = await salesforceApi.getStats(token)
      setStats(dashboardStats)
    } catch (err: any) {
      setError(err.message || 'Failed to load dashboard data')
    } finally {
      setIsLoading(false)
    }
  }, [token])

  useEffect(() => {
    if (token) {
      loadData()
    }
  }, [token, loadData])

  // Handle file upload (shared between input and drag-drop)
  const handleFileUpload = async (file: File) => {
    if (!token) return

    if (!file.name.toLowerCase().endsWith('.zip')) {
      setError('Please select a .zip file')
      return
    }

    setIsUploading(true)
    setError('')
    setUploadMessage('')
    setLastRunId(null)

    try {
      const result = await salesforceApi.importData(token, file)

      // Track the job in the activity monitor
      if (result.run_id) {
        addJob({
          runId: result.run_id,
          jobType: 'salesforce_import',
          displayName: `Import: ${file.name}`,
          resourceId: result.run_id,
          resourceType: 'salesforce',
        })
        setLastRunId(result.run_id)
      }

      setUploadMessage(`Import started for ${file.name}`)
      // WebSocket hook handles refresh on job completion
    } catch (err: any) {
      setError(err.message || 'Failed to start import')
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  // Handle file input change
  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      await handleFileUpload(file)
    }
  }

  // Drag and drop handlers
  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    // Only set dragging to false if we're leaving the drop zone entirely
    const rect = e.currentTarget.getBoundingClientRect()
    const x = e.clientX
    const y = e.clientY
    if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
      setIsDragging(false)
    }
  }, [])

  const handleDrop = useCallback(async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)

    const files = e.dataTransfer?.files
    if (files && files.length > 0) {
      await handleFileUpload(files[0])
    }
  }, [token])

  // Format currency
  const formatCurrency = (value: number | null | undefined) => {
    if (value == null) return '$0'
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)
  }

  // Check if data exists
  const hasData = stats && (stats.accounts.total > 0 || stats.contacts.total > 0 || stats.opportunities.total > 0)

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 text-white shadow-lg shadow-cyan-500/25">
                <Database className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  Salesforce CRM
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  Manage imported Salesforce data
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                onClick={loadData}
                disabled={isLoading}
                className="gap-2"
              >
                <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip"
                onChange={handleFileSelect}
                className="hidden"
              />
              <Button
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="gap-2"
              >
                {isUploading ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Upload className="w-4 h-4" />
                )}
                {isUploading ? 'Uploading...' : 'Import Data'}
              </Button>
            </div>
          </div>
        </div>

        {/* Success Message */}
        {uploadMessage && (
          <div className="mb-6 p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-green-800 dark:text-green-200">
                <CheckCircle2 className="w-5 h-5" />
                <span>{uploadMessage}</span>
              </div>
              {lastRunId && (
                <Link
                  href={`/admin/queue?run_id=${lastRunId}`}
                  className="flex items-center gap-1 text-sm text-green-700 dark:text-green-300 hover:text-green-900 dark:hover:text-green-100 font-medium"
                >
                  View Job
                  <ExternalLink className="w-4 h-4" />
                </Link>
              )}
            </div>
          </div>
        )}

        {/* Active Import Jobs */}
        <JobProgressPanelByType jobType="salesforce_import" variant="compact" className="mb-6 space-y-2" />

        {/* Error State */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
            <div className="flex items-center gap-2 text-red-800 dark:text-red-200">
              <AlertTriangle className="w-5 h-5" />
              <span>{error}</span>
            </div>
          </div>
        )}

        {/* Loading State */}
        {isLoading && (
          <div className="flex items-center justify-center py-12">
            <RefreshCw className="w-8 h-8 animate-spin text-gray-400" />
          </div>
        )}

        {/* No Data State with Drag & Drop */}
        {!isLoading && !hasData && (
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            className={clsx(
              "bg-white dark:bg-gray-800 rounded-xl border-2 border-dashed p-12 text-center transition-all duration-200",
              isDragging
                ? "border-cyan-500 bg-cyan-50 dark:bg-cyan-900/20"
                : "border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500"
            )}
          >
            <div className={clsx(
              "flex items-center justify-center w-16 h-16 mx-auto mb-4 rounded-full transition-colors",
              isDragging
                ? "bg-cyan-100 dark:bg-cyan-900/50"
                : "bg-cyan-100 dark:bg-cyan-900/30"
            )}>
              {isDragging ? (
                <FileArchive className="w-8 h-8 text-cyan-600 dark:text-cyan-400" />
              ) : (
                <FileUp className="w-8 h-8 text-cyan-600 dark:text-cyan-400" />
              )}
            </div>
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
              {isDragging ? 'Drop your file here' : 'No Salesforce Data Yet'}
            </h2>
            <p className="text-gray-500 dark:text-gray-400 mb-6 max-w-md mx-auto">
              {isDragging
                ? 'Release to upload your Salesforce export zip file'
                : 'Drag and drop a zip file here, or click the button below to select one. The zip should contain Account, Contact, and Opportunity CSV exports.'}
            </p>
            {!isDragging && (
              <Button
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="gap-2"
              >
                {isUploading ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Upload className="w-4 h-4" />
                )}
                {isUploading ? 'Uploading...' : 'Select Zip File'}
              </Button>
            )}
          </div>
        )}

        {/* Stats Cards */}
        {!isLoading && hasData && stats && (
          <>
            {/* Drag & Drop Zone when data exists */}
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              className={clsx(
                "mb-6 rounded-xl border-2 border-dashed p-4 text-center transition-all duration-200",
                isDragging
                  ? "border-cyan-500 bg-cyan-50 dark:bg-cyan-900/20"
                  : "border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50"
              )}
            >
              <div className="flex items-center justify-center gap-3">
                {isDragging ? (
                  <>
                    <FileArchive className="w-5 h-5 text-cyan-600 dark:text-cyan-400" />
                    <span className="text-cyan-600 dark:text-cyan-400 font-medium">
                      Drop to import new data
                    </span>
                  </>
                ) : (
                  <>
                    <Upload className="w-5 h-5 text-gray-400" />
                    <span className="text-gray-500 dark:text-gray-400 text-sm">
                      Drag and drop a new Salesforce export zip here to update data
                    </span>
                  </>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
              {/* Accounts Card */}
              <Link href="/salesforce/accounts">
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 hover:shadow-lg hover:border-cyan-300 dark:hover:border-cyan-600 transition-all cursor-pointer">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-purple-100 dark:bg-purple-900/30">
                      <Building2 className="w-5 h-5 text-purple-600 dark:text-purple-400" />
                    </div>
                    <ArrowRight className="w-5 h-5 text-gray-400" />
                  </div>
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">
                    {stats.accounts.total.toLocaleString()}
                  </div>
                  <div className="text-sm text-gray-500 dark:text-gray-400">Accounts</div>
                </div>
              </Link>

              {/* Contacts Card */}
              <Link href="/salesforce/contacts">
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 hover:shadow-lg hover:border-cyan-300 dark:hover:border-cyan-600 transition-all cursor-pointer">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-blue-100 dark:bg-blue-900/30">
                      <Users className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                    </div>
                    <ArrowRight className="w-5 h-5 text-gray-400" />
                  </div>
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">
                    {stats.contacts.total.toLocaleString()}
                  </div>
                  <div className="text-sm text-gray-500 dark:text-gray-400">Contacts</div>
                </div>
              </Link>

              {/* Opportunities Card */}
              <Link href="/salesforce/opportunities">
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 hover:shadow-lg hover:border-cyan-300 dark:hover:border-cyan-600 transition-all cursor-pointer">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-green-100 dark:bg-green-900/30">
                      <Target className="w-5 h-5 text-green-600 dark:text-green-400" />
                    </div>
                    <ArrowRight className="w-5 h-5 text-gray-400" />
                  </div>
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">
                    {stats.opportunities.total.toLocaleString()}
                  </div>
                  <div className="text-sm text-gray-500 dark:text-gray-400">Opportunities</div>
                </div>
              </Link>

              {/* Pipeline Value Card */}
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-amber-100 dark:bg-amber-900/30">
                    <DollarSign className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                  </div>
                </div>
                <div className="text-2xl font-bold text-gray-900 dark:text-white">
                  {formatCurrency(stats.opportunities.open_value)}
                </div>
                <div className="text-sm text-gray-500 dark:text-gray-400">
                  Open Pipeline ({stats.opportunities.open} opps)
                </div>
              </div>
            </div>

            {/* Pipeline Summary */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
              {/* Won Deals */}
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                <div className="flex items-center gap-3 mb-4">
                  <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-green-100 dark:bg-green-900/30">
                    <TrendingUp className="w-5 h-5 text-green-600 dark:text-green-400" />
                  </div>
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Won Deals</h3>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="text-3xl font-bold text-green-600 dark:text-green-400">
                      {stats.opportunities.won.toLocaleString()}
                    </div>
                    <div className="text-sm text-gray-500 dark:text-gray-400">Opportunities Won</div>
                  </div>
                  <div>
                    <div className="text-3xl font-bold text-green-600 dark:text-green-400">
                      {formatCurrency(stats.opportunities.won_value)}
                    </div>
                    <div className="text-sm text-gray-500 dark:text-gray-400">Total Value Won</div>
                  </div>
                </div>
              </div>

              {/* Stage Breakdown */}
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                  Pipeline by Stage
                </h3>
                <div className="space-y-3">
                  {stats.opportunities.by_stage.slice(0, 5).map((stage) => (
                    <div key={stage.stage} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-gray-700 dark:text-gray-300">{stage.stage}</span>
                        <span className="text-xs text-gray-500 dark:text-gray-400">({stage.count})</span>
                      </div>
                      <span className="text-sm font-medium text-gray-900 dark:text-white">
                        {formatCurrency(stage.value)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Account Types */}
            {stats.accounts.by_type && stats.accounts.by_type.length > 0 && (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                  Accounts by Type
                </h3>
                <div className="flex flex-wrap gap-3">
                  {stats.accounts.by_type.map((item) => (
                    <div
                      key={item.type}
                      className="px-4 py-2 bg-gray-100 dark:bg-gray-700 rounded-lg"
                    >
                      <span className="text-sm font-medium text-gray-900 dark:text-white">
                        {item.type}
                      </span>
                      <span className="ml-2 text-sm text-gray-500 dark:text-gray-400">
                        ({item.count})
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

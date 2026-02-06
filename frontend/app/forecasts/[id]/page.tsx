'use client'

import { useState, useEffect, use, useCallback } from 'react'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { forecastsApi, Forecast } from '@/lib/api'
import { formatDate as formatDateUtil } from '@/lib/date-utils'
import ForecastBreadcrumbs from '@/components/forecasts/ForecastBreadcrumbs'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  TrendingUp,
  AlertTriangle,
  Calendar,
  Building2,
  ExternalLink,
  Hash,
  User,
  Mail,
  Briefcase,
  MapPin,
  FileText,
  Clock,
  Tag,
} from 'lucide-react'

interface PageProps {
  params: Promise<{ id: string }>
}

export default function ForecastDetailPage({ params }: PageProps) {
  return (
    <ProtectedRoute>
      <ForecastDetailContent params={params} />
    </ProtectedRoute>
  )
}

function ForecastDetailContent({ params }: PageProps) {
  const resolvedParams = use(params)
  const forecastId = resolvedParams.id
  const { token } = useAuth()

  // State
  const [forecast, setForecast] = useState<Forecast | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  // Source type labels and colors
  const sourceTypeConfig: Record<string, { label: string; shortLabel: string; color: string; gradient: string }> = {
    ag: {
      label: 'GSA Acquisition Gateway',
      shortLabel: 'AG',
      color: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300',
      gradient: 'from-blue-500 to-indigo-600',
    },
    apfs: {
      label: 'DHS APFS',
      shortLabel: 'DHS',
      color: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300',
      gradient: 'from-emerald-500 to-teal-600',
    },
    state: {
      label: 'State Department',
      shortLabel: 'State',
      color: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300',
      gradient: 'from-purple-500 to-pink-600',
    },
  }

  // Load forecast details
  const loadForecast = useCallback(async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const data = await forecastsApi.getForecastById(token, forecastId)
      setForecast(data)
    } catch (err: any) {
      setError(err.message || 'Failed to load forecast')
    } finally {
      setIsLoading(false)
    }
  }, [token, forecastId])

  useEffect(() => {
    if (token) {
      loadForecast()
    }
  }, [token, loadForecast])

  const formatDate = (dateStr: string | null) => formatDateUtil(dateStr)

  const config = forecast ? (sourceTypeConfig[forecast.source_type] || sourceTypeConfig.ag) : sourceTypeConfig.ag

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Breadcrumbs */}
        <ForecastBreadcrumbs
          items={[
            { label: forecast?.title || 'Forecast' },
          ]}
        />

        {/* Error State */}
        {error && (
          <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
            <div className="flex items-center gap-3">
              <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
              <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
            </div>
          </div>
        )}

        {/* Loading State */}
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-12 h-12 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-emerald-500 animate-spin" />
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading forecast...</p>
          </div>
        ) : forecast ? (
          <>
            {/* Header */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 mb-6">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-4 flex-1">
                  <div className={`flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br ${config.gradient} text-white shadow-lg shadow-emerald-500/25`}>
                    <TrendingUp className="w-6 h-6" />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <span className={`px-2.5 py-0.5 text-xs font-medium rounded-full ${config.color}`}>
                        {config.label}
                      </span>
                      {forecast.fiscal_year && (
                        <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300">
                          FY{forecast.fiscal_year}
                        </span>
                      )}
                      {forecast.set_aside_type && (
                        <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300">
                          {forecast.set_aside_type}
                        </span>
                      )}
                    </div>
                    <h1 className="text-xl font-bold text-gray-900 dark:text-white mb-1">
                      {forecast.title || 'Untitled Forecast'}
                    </h1>
                    <p className="text-sm font-mono text-gray-500 dark:text-gray-400">
                      {forecast.source_id}
                    </p>
                  </div>
                </div>
              </div>

              {/* Meta info grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 pt-6 border-t border-gray-100 dark:border-gray-700">
                {forecast.agency_name && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Agency</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-1.5">
                      <Building2 className="w-4 h-4 text-gray-400" />
                      {forecast.agency_name}
                    </p>
                  </div>
                )}
                {forecast.naics_codes && forecast.naics_codes.length > 0 && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">NAICS Code</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-1.5">
                      <Hash className="w-4 h-4 text-gray-400" />
                      {forecast.naics_codes[0]?.code || 'N/A'}
                    </p>
                  </div>
                )}
                {forecast.fiscal_year && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Fiscal Year</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-1.5">
                      <Calendar className="w-4 h-4 text-gray-400" />
                      FY{forecast.fiscal_year}
                    </p>
                  </div>
                )}
                {forecast.estimated_award_quarter && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Award Quarter</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-1.5">
                      <Clock className="w-4 h-4 text-gray-400" />
                      {forecast.estimated_award_quarter}
                    </p>
                  </div>
                )}
              </div>

              {/* Additional metadata row */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
                {forecast.contract_type && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Contract Type</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">
                      {forecast.contract_type}
                    </p>
                  </div>
                )}
                {forecast.contract_vehicle && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Contract Vehicle</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">
                      {forecast.contract_vehicle}
                    </p>
                  </div>
                )}
                {forecast.acquisition_phase && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Acquisition Phase</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">
                      {forecast.acquisition_phase}
                    </p>
                  </div>
                )}
                {forecast.estimated_solicitation_date && (
                  <div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Est. Solicitation Date</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-1.5">
                      <Calendar className="w-4 h-4 text-gray-400" />
                      {formatDate(forecast.estimated_solicitation_date)}
                    </p>
                  </div>
                )}
              </div>
            </div>

            {/* Description */}
            {forecast.description && (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 mb-6">
                <div className="flex items-center gap-2 mb-4">
                  <FileText className="w-5 h-5 text-gray-400" />
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Description</h2>
                </div>
                <div className="prose prose-sm dark:prose-invert max-w-none text-gray-700 dark:text-gray-300">
                  <p className="whitespace-pre-wrap">{forecast.description}</p>
                </div>
              </div>
            )}

            {/* NAICS Details */}
            {forecast.naics_codes && forecast.naics_codes.length > 0 && (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 mb-6">
                <div className="flex items-center gap-2 mb-4">
                  <Tag className="w-5 h-5 text-gray-400" />
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">NAICS Codes</h2>
                </div>
                <div className="space-y-2">
                  {forecast.naics_codes.map((naics, idx) => (
                    <div key={idx} className="flex items-start gap-2">
                      <span className="font-mono text-sm text-indigo-600 dark:text-indigo-400 font-medium">
                        {naics.code}
                      </span>
                      {naics.description && (
                        <span className="text-sm text-gray-600 dark:text-gray-400">
                          - {naics.description}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Place of Performance */}
            {(forecast.pop_city || forecast.pop_state || forecast.pop_country) && (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 mb-6">
                <div className="flex items-center gap-2 mb-4">
                  <MapPin className="w-5 h-5 text-gray-400" />
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Place of Performance</h2>
                </div>
                <p className="text-sm text-gray-700 dark:text-gray-300">
                  {[forecast.pop_city, forecast.pop_state, forecast.pop_country]
                    .filter(Boolean)
                    .join(', ')}
                </p>
                {(forecast.pop_start_date || forecast.pop_end_date) && (
                  <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700">
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Period of Performance</p>
                    <p className="text-sm text-gray-700 dark:text-gray-300">
                      {formatDate(forecast.pop_start_date)} - {formatDate(forecast.pop_end_date)}
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* Contact Information */}
            {(forecast.poc_name || forecast.poc_email || forecast.sbs_name || forecast.sbs_email) && (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 mb-6">
                <div className="flex items-center gap-2 mb-4">
                  <User className="w-5 h-5 text-gray-400" />
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Contact Information</h2>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Primary Contact */}
                  {(forecast.poc_name || forecast.poc_email) && (
                    <div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-2 uppercase font-medium">Primary Contact</p>
                      {forecast.poc_name && (
                        <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-2">
                          <User className="w-4 h-4 text-gray-400" />
                          {forecast.poc_name}
                        </p>
                      )}
                      {forecast.poc_email && (
                        <a
                          href={`mailto:${forecast.poc_email}`}
                          className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-2 mt-1"
                        >
                          <Mail className="w-4 h-4" />
                          {forecast.poc_email}
                        </a>
                      )}
                    </div>
                  )}

                  {/* Small Business Specialist */}
                  {(forecast.sbs_name || forecast.sbs_email) && (
                    <div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-2 uppercase font-medium">Small Business Specialist</p>
                      {forecast.sbs_name && (
                        <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-2">
                          <Briefcase className="w-4 h-4 text-gray-400" />
                          {forecast.sbs_name}
                        </p>
                      )}
                      {forecast.sbs_email && (
                        <a
                          href={`mailto:${forecast.sbs_email}`}
                          className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-2 mt-1"
                        >
                          <Mail className="w-4 h-4" />
                          {forecast.sbs_email}
                        </a>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Incumbent Contractor */}
            {forecast.incumbent_contractor && (
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 mb-6">
                <div className="flex items-center gap-2 mb-4">
                  <Building2 className="w-5 h-5 text-gray-400" />
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Incumbent Contractor</h2>
                </div>
                <p className="text-sm text-gray-700 dark:text-gray-300">
                  {forecast.incumbent_contractor}
                </p>
              </div>
            )}

            {/* Timestamps */}
            <div className="bg-gray-50 dark:bg-gray-900/50 rounded-xl border border-gray-200 dark:border-gray-700 p-4 mb-6">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs text-gray-500 dark:text-gray-400">
                <div>
                  <p className="mb-1">First Seen</p>
                  <p className="font-medium text-gray-700 dark:text-gray-300">
                    {formatDate(forecast.first_seen_at)}
                  </p>
                </div>
                <div>
                  <p className="mb-1">Last Updated</p>
                  <p className="font-medium text-gray-700 dark:text-gray-300">
                    {formatDate(forecast.last_updated_at)}
                  </p>
                </div>
                {forecast.indexed_at && (
                  <div>
                    <p className="mb-1">Indexed</p>
                    <p className="font-medium text-gray-700 dark:text-gray-300">
                      {formatDate(forecast.indexed_at)}
                    </p>
                  </div>
                )}
                <div>
                  <p className="mb-1">Source</p>
                  <p className="font-medium text-gray-700 dark:text-gray-300">
                    {config.label}
                  </p>
                </div>
              </div>
            </div>

            {/* Source Link */}
            {forecast.source_url && (
              <div className="text-center">
                <a
                  href={forecast.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
                >
                  View Original Source
                  <ExternalLink className="w-4 h-4" />
                </a>
              </div>
            )}
          </>
        ) : (
          <div className="text-center py-16">
            <TrendingUp className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <p className="text-gray-500 dark:text-gray-400">Forecast not found.</p>
            <Link
              href="/forecasts"
              className="inline-flex items-center gap-2 mt-4 text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              Back to Forecasts
            </Link>
          </div>
        )}
      </div>
    </div>
  )
}

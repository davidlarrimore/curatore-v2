'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { salesforceApi, SalesforceOpportunity } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  Target,
  RefreshCw,
  AlertTriangle,
  ArrowLeft,
  Building2,
  DollarSign,
  Calendar,
  CheckCircle,
  XCircle,
  TrendingUp,
  Percent,
  Clock,
  FileText,
} from 'lucide-react'

export default function SalesforceOpportunityDetailPage() {
  return (
    <ProtectedRoute>
      <SalesforceOpportunityDetailContent />
    </ProtectedRoute>
  )
}

function SalesforceOpportunityDetailContent() {
  const params = useParams()
  const router = useRouter()
  const { token } = useAuth()
  const opportunityId = params.id as string

  // State
  const [opportunity, setOpportunity] = useState<SalesforceOpportunity | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  // Load data
  const loadData = useCallback(async () => {
    if (!token || !opportunityId) return

    setIsLoading(true)
    setError('')

    try {
      const oppRes = await salesforceApi.getOpportunity(token, opportunityId)
      setOpportunity(oppRes)
    } catch (err: any) {
      setError(err.message || 'Failed to load opportunity')
    } finally {
      setIsLoading(false)
    }
  }, [token, opportunityId])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Format currency
  const formatCurrency = (value: number | null | undefined) => {
    if (value == null) return '-'
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950 flex items-center justify-center">
        <RefreshCw className="w-8 h-8 animate-spin text-gray-400" />
      </div>
    )
  }

  if (error || !opportunity) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="p-6 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl">
            <div className="flex items-center gap-2 text-red-800 dark:text-red-200">
              <AlertTriangle className="w-5 h-5" />
              <span>{error || 'Opportunity not found'}</span>
            </div>
            <Link href="/salesforce/opportunities" className="mt-4 inline-block text-cyan-600 dark:text-cyan-400 hover:underline">
              Back to Opportunities
            </Link>
          </div>
        </div>
      </div>
    )
  }

  // Determine status
  const getStatusDisplay = () => {
    if (opportunity.is_won) {
      return {
        label: 'Won',
        icon: CheckCircle,
        colorClass: 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-200',
      }
    }
    if (opportunity.is_closed) {
      return {
        label: 'Lost',
        icon: XCircle,
        colorClass: 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-200',
      }
    }
    return {
      label: 'Open',
      icon: Clock,
      colorClass: 'bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-200',
    }
  }

  const status = getStatusDisplay()
  const StatusIcon = status.icon

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-4">
          <Link href="/salesforce" className="hover:text-gray-900 dark:hover:text-white">
            Salesforce
          </Link>
          <span>/</span>
          <Link href="/salesforce/opportunities" className="hover:text-gray-900 dark:hover:text-white">
            Opportunities
          </Link>
          <span>/</span>
          <span className="text-gray-900 dark:text-white truncate max-w-[200px]">{opportunity.name}</span>
        </div>

        {/* Header */}
        <div className="mb-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="flex items-start gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-green-500 to-emerald-600 text-white shadow-lg shadow-green-500/25">
                <Target className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  {opportunity.name}
                </h1>
                <div className="flex flex-wrap items-center gap-3 mt-2">
                  <span className={`flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ${status.colorClass}`}>
                    <StatusIcon className="w-3 h-3" />
                    {status.label}
                  </span>
                  {opportunity.stage_name && (
                    <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-200">
                      {opportunity.stage_name}
                    </span>
                  )}
                  {opportunity.opportunity_type && (
                    <span className="text-sm text-gray-500 dark:text-gray-400">
                      {opportunity.opportunity_type}
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-2">
                  SF ID: {opportunity.salesforce_id}
                </p>
              </div>
            </div>
            <Button
              variant="secondary"
              onClick={loadData}
              disabled={isLoading}
              className="gap-2"
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </div>
        </div>

        {/* Key Metrics */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          {/* Amount */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400 mb-1">
              <DollarSign className="w-4 h-4" />
              <span className="text-xs">Amount</span>
            </div>
            <div className="text-xl font-bold text-gray-900 dark:text-white">
              {formatCurrency(opportunity.amount)}
            </div>
          </div>

          {/* Probability */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400 mb-1">
              <Percent className="w-4 h-4" />
              <span className="text-xs">Probability</span>
            </div>
            <div className="text-xl font-bold text-gray-900 dark:text-white">
              {opportunity.probability != null ? `${opportunity.probability}%` : '-'}
            </div>
          </div>

          {/* Close Date */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400 mb-1">
              <Calendar className="w-4 h-4" />
              <span className="text-xs">Close Date</span>
            </div>
            <div className="text-xl font-bold text-gray-900 dark:text-white">
              {opportunity.close_date ? new Date(opportunity.close_date).toLocaleDateString() : '-'}
            </div>
          </div>

          {/* Fiscal */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400 mb-1">
              <TrendingUp className="w-4 h-4" />
              <span className="text-xs">Fiscal</span>
            </div>
            <div className="text-xl font-bold text-gray-900 dark:text-white">
              {opportunity.fiscal_year || '-'}{opportunity.fiscal_quarter ? ` ${opportunity.fiscal_quarter}` : ''}
            </div>
          </div>
        </div>

        {/* Details Card */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Details</h2>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Account */}
            {opportunity.account_name && (
              <div className="flex items-center gap-3">
                <Building2 className="w-5 h-5 text-gray-400" />
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Account</div>
                  <Link
                    href={`/salesforce/accounts/${opportunity.account_id}`}
                    className="text-sm text-cyan-600 dark:text-cyan-400 hover:underline"
                  >
                    {opportunity.account_name}
                  </Link>
                </div>
              </div>
            )}

            {/* Lead Source */}
            {opportunity.lead_source && (
              <div className="flex items-center gap-3">
                <TrendingUp className="w-5 h-5 text-gray-400" />
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Lead Source</div>
                  <div className="text-sm text-gray-900 dark:text-white">{opportunity.lead_source}</div>
                </div>
              </div>
            )}

            {/* Role */}
            {opportunity.role && (
              <div className="flex items-center gap-3">
                <Target className="w-5 h-5 text-gray-400" />
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Role</div>
                  <div className="text-sm text-gray-900 dark:text-white">{opportunity.role}</div>
                </div>
              </div>
            )}
          </div>

          {/* Description */}
          {opportunity.description && (
            <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
              <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400 mb-2">
                <FileText className="w-4 h-4" />
                <span className="text-sm font-medium">Description</span>
              </div>
              <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                {opportunity.description}
              </p>
            </div>
          )}
        </div>

        {/* Integration Links */}
        {(opportunity.linked_sharepoint_folder_id || opportunity.linked_sam_solicitation_id) && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Linked Resources</h2>
            <div className="space-y-3">
              {opportunity.linked_sharepoint_folder_id && (
                <Link
                  href={`/sharepoint-sync/${opportunity.linked_sharepoint_folder_id}`}
                  className="flex items-center gap-2 text-cyan-600 dark:text-cyan-400 hover:underline"
                >
                  <Building2 className="w-4 h-4" />
                  View SharePoint Folder
                </Link>
              )}
              {opportunity.linked_sam_solicitation_id && (
                <Link
                  href={`/sam/solicitations/${opportunity.linked_sam_solicitation_id}`}
                  className="flex items-center gap-2 text-cyan-600 dark:text-cyan-400 hover:underline"
                >
                  <FileText className="w-4 h-4" />
                  View SAM.gov Solicitation
                </Link>
              )}
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="mt-6 flex flex-wrap gap-3">
          {opportunity.account_id && (
            <Link href={`/salesforce/accounts/${opportunity.account_id}`}>
              <Button variant="secondary" className="gap-2">
                <Building2 className="w-4 h-4" />
                View Account
              </Button>
            </Link>
          )}
        </div>
      </div>
    </div>
  )
}

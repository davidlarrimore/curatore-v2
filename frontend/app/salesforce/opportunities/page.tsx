'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { salesforceApi, SalesforceOpportunity } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  Target,
  RefreshCw,
  AlertTriangle,
  Search,
  ChevronLeft,
  ChevronRight,
  ArrowLeft,
  DollarSign,
  Calendar,
  CheckCircle,
  XCircle,
} from 'lucide-react'

export default function SalesforceOpportunitiesPage() {
  return (
    <ProtectedRoute>
      <SalesforceOpportunitiesContent />
    </ProtectedRoute>
  )
}

function SalesforceOpportunitiesContent() {
  const router = useRouter()
  const { token } = useAuth()

  // State
  const [opportunities, setOpportunities] = useState<SalesforceOpportunity[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  // Filters
  const [keyword, setKeyword] = useState('')
  const [stageName, setStageName] = useState('')
  const [opportunityType, setOpportunityType] = useState('')
  const [isOpen, setIsOpen] = useState<boolean | undefined>(undefined)
  const [stages, setStages] = useState<string[]>([])
  const [types, setTypes] = useState<string[]>([])

  // Pagination
  const [page, setPage] = useState(1)
  const limit = 25

  // Load filter options
  const loadFilterOptions = useCallback(async () => {
    if (!token) return
    try {
      const [stagesRes, typesRes] = await Promise.all([
        salesforceApi.getStages(token),
        salesforceApi.getOpportunityTypes(token),
      ])
      setStages(stagesRes.options)
      setTypes(typesRes.options)
    } catch (err) {
      // Silently fail for filter options
    }
  }, [token])

  // Load data
  const loadData = useCallback(async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const offset = (page - 1) * limit
      const result = await salesforceApi.listOpportunities(token, {
        keyword: keyword || undefined,
        stage_name: stageName || undefined,
        opportunity_type: opportunityType || undefined,
        is_open: isOpen,
        limit,
        offset,
      })
      setOpportunities(result.items)
      setTotal(result.total)
    } catch (err: any) {
      setError(err.message || 'Failed to load opportunities')
    } finally {
      setIsLoading(false)
    }
  }, [token, page, keyword, stageName, opportunityType, isOpen])

  useEffect(() => {
    loadFilterOptions()
  }, [loadFilterOptions])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Handle search
  const handleSearch = () => {
    setPage(1)
    loadData()
  }

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

  // Pagination
  const totalPages = Math.ceil(total / limit)

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-4">
            <Link href="/salesforce" className="hover:text-gray-900 dark:hover:text-white flex items-center gap-1">
              <ArrowLeft className="w-4 h-4" />
              Salesforce
            </Link>
          </div>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-green-500 to-emerald-600 text-white shadow-lg shadow-green-500/25">
                <Target className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  Opportunities
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  {total.toLocaleString()} opportunities
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

        {/* Filters */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 mb-6">
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex-1">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input
                  type="text"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                  placeholder="Search opportunities..."
                  className="w-full pl-10 pr-4 py-2 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
                />
              </div>
            </div>
            <select
              value={stageName}
              onChange={(e) => { setStageName(e.target.value); setPage(1); }}
              className="px-4 py-2 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
            >
              <option value="">All Stages</option>
              {stages.map((stage) => (
                <option key={stage} value={stage}>{stage}</option>
              ))}
            </select>
            <select
              value={opportunityType}
              onChange={(e) => { setOpportunityType(e.target.value); setPage(1); }}
              className="px-4 py-2 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
            >
              <option value="">All Types</option>
              {types.map((type) => (
                <option key={type} value={type}>{type}</option>
              ))}
            </select>
            <select
              value={isOpen === undefined ? '' : isOpen.toString()}
              onChange={(e) => {
                setIsOpen(e.target.value === '' ? undefined : e.target.value === 'true')
                setPage(1)
              }}
              className="px-4 py-2 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
            >
              <option value="">All Status</option>
              <option value="true">Open</option>
              <option value="false">Closed</option>
            </select>
            <Button onClick={handleSearch} className="gap-2">
              <Search className="w-4 h-4" />
              Search
            </Button>
          </div>
        </div>

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

        {/* Opportunities Table */}
        {!isLoading && opportunities.length > 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50 dark:bg-gray-900">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Name</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Account</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Stage</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Amount</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Close Date</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {opportunities.map((opp) => (
                    <tr
                      key={opp.id}
                      onClick={() => router.push(`/salesforce/opportunities/${opp.id}`)}
                      className="hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
                    >
                      <td className="px-6 py-4">
                        <div className="text-sm font-medium text-gray-900 dark:text-white">
                          {opp.name}
                        </div>
                        {opp.opportunity_type && (
                          <div className="text-xs text-gray-500 dark:text-gray-400">
                            {opp.opportunity_type}
                          </div>
                        )}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                        {opp.account_name || '-'}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        {opp.stage_name && (
                          <span className="px-2 py-1 text-xs font-medium rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-200">
                            {opp.stage_name}
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center gap-1 text-sm text-gray-900 dark:text-white">
                          <DollarSign className="w-4 h-4 text-gray-400" />
                          {formatCurrency(opp.amount)}
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        {opp.close_date && (
                          <div className="flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400">
                            <Calendar className="w-4 h-4" />
                            {new Date(opp.close_date).toLocaleDateString()}
                          </div>
                        )}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        {opp.is_won ? (
                          <span className="flex items-center gap-1 text-green-600 dark:text-green-400 text-sm">
                            <CheckCircle className="w-4 h-4" />
                            Won
                          </span>
                        ) : opp.is_closed ? (
                          <span className="flex items-center gap-1 text-red-600 dark:text-red-400 text-sm">
                            <XCircle className="w-4 h-4" />
                            Lost
                          </span>
                        ) : (
                          <span className="text-sm text-amber-600 dark:text-amber-400">
                            Open
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex items-center justify-between">
                <div className="text-sm text-gray-500 dark:text-gray-400">
                  Showing {((page - 1) * limit) + 1} to {Math.min(page * limit, total)} of {total}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </Button>
                  <span className="text-sm text-gray-700 dark:text-gray-300">
                    Page {page} of {totalPages}
                  </span>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                  >
                    <ChevronRight className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Empty State */}
        {!isLoading && opportunities.length === 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-12 text-center">
            <Target className="w-12 h-12 mx-auto mb-4 text-gray-400" />
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
              No Opportunities Found
            </h2>
            <p className="text-gray-500 dark:text-gray-400">
              {keyword || stageName || opportunityType || isOpen !== undefined
                ? 'Try adjusting your search filters'
                : 'Import Salesforce data to see opportunities here'}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

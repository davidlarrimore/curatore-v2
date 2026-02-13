'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { useOrgUrl } from '@/lib/org-url-context'
import { salesforceApi, SalesforceAccount, SalesforceContact, SalesforceOpportunity } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import {
  Building2,
  RefreshCw,
  AlertTriangle,
  Globe,
  Phone,
  MapPin,
  Users,
  Target,
  Mail,
  DollarSign,
  Calendar,
  CheckCircle,
  XCircle,
  ExternalLink,
} from 'lucide-react'

interface Address {
  street?: string
  city?: string
  state?: string
  postal_code?: string
  country?: string
}

export default function SalesforceAccountDetailPage() {
  const params = useParams()
  const router = useRouter()
  const { token } = useAuth()
  const { orgSlug } = useOrgUrl()
  const accountId = params.id as string

  // Helper for org-scoped URLs
  const orgUrl = (path: string) => `/orgs/${orgSlug}${path}`

  // State
  const [account, setAccount] = useState<SalesforceAccount | null>(null)
  const [contacts, setContacts] = useState<SalesforceContact[]>([])
  const [opportunities, setOpportunities] = useState<SalesforceOpportunity[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState<'contacts' | 'opportunities'>('contacts')

  // Load data
  const loadData = useCallback(async () => {
    if (!token || !accountId) return

    setIsLoading(true)
    setError('')

    try {
      const [accountRes, contactsRes, oppsRes] = await Promise.all([
        salesforceApi.getAccount(token, accountId),
        salesforceApi.getAccountContacts(token, accountId),
        salesforceApi.getAccountOpportunities(token, accountId),
      ])
      setAccount(accountRes)
      setContacts(contactsRes.items)
      setOpportunities(oppsRes.items)
    } catch (err: unknown) {
      const error = err as { message?: string }
      setError(error.message || 'Failed to load account')
    } finally {
      setIsLoading(false)
    }
  }, [token, accountId])

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

  // Format address
  const formatAddress = (address: Address | null | undefined) => {
    if (!address) return null
    const parts = [address.street, address.city, address.state, address.postal_code, address.country]
      .filter(Boolean)
    return parts.length > 0 ? parts.join(', ') : null
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950 flex items-center justify-center">
        <RefreshCw className="w-8 h-8 animate-spin text-gray-400" />
      </div>
    )
  }

  if (error || !account) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="p-6 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl">
            <div className="flex items-center gap-2 text-red-800 dark:text-red-200">
              <AlertTriangle className="w-5 h-5" />
              <span>{error || 'Account not found'}</span>
            </div>
            <Link href={orgUrl('/syncs/salesforce/accounts')} className="mt-4 inline-block text-cyan-600 dark:text-cyan-400 hover:underline">
              Back to Accounts
            </Link>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-4">
          <Link href={orgUrl('/syncs/salesforce')} className="hover:text-gray-900 dark:hover:text-white">
            Salesforce
          </Link>
          <span>/</span>
          <Link href={orgUrl('/syncs/salesforce/accounts')} className="hover:text-gray-900 dark:hover:text-white">
            Accounts
          </Link>
          <span>/</span>
          <span className="text-gray-900 dark:text-white">{account.name}</span>
        </div>

        {/* Header */}
        <div className="mb-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="flex items-start gap-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-purple-500 to-indigo-600 text-white shadow-lg shadow-purple-500/25">
                <Building2 className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  {account.name}
                </h1>
                <div className="flex items-center gap-3 mt-1">
                  {account.account_type && (
                    <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-purple-100 dark:bg-purple-900/30 text-purple-800 dark:text-purple-200">
                      {account.account_type}
                    </span>
                  )}
                  {account.industry && (
                    <span className="text-sm text-gray-500 dark:text-gray-400">
                      {account.industry}
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                  SF ID: {account.salesforce_id}
                </p>
              </div>
            </div>
            <div className="flex gap-2">
              <a
                href={`https://amivero.lightning.force.com/lightning/r/Account/${account.salesforce_id}/view`}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button variant="secondary" className="gap-2">
                  <ExternalLink className="w-4 h-4" />
                  View in Salesforce
                </Button>
              </a>
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
        </div>

        {/* Account Details Card */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 mb-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {/* Contact Info */}
            {account.phone && (
              <div className="flex items-center gap-3">
                <Phone className="w-5 h-5 text-gray-400" />
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Phone</div>
                  <div className="text-sm text-gray-900 dark:text-white">{account.phone}</div>
                </div>
              </div>
            )}
            {account.website && (
              <div className="flex items-center gap-3">
                <Globe className="w-5 h-5 text-gray-400" />
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Website</div>
                  <a
                    href={account.website.startsWith('http') ? account.website : `https://${account.website}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-cyan-600 dark:text-cyan-400 hover:underline"
                  >
                    {account.website}
                  </a>
                </div>
              </div>
            )}

            {/* Addresses */}
            {formatAddress(account.billing_address as Address) && (
              <div className="flex items-start gap-3">
                <MapPin className="w-5 h-5 text-gray-400 mt-0.5" />
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Billing Address</div>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {formatAddress(account.billing_address as Address)}
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Description */}
          {account.description && (
            <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
              <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">Description</h3>
              <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                {account.description}
              </p>
            </div>
          )}

          {/* Small Business Flags */}
          {account.small_business_flags && Object.keys(account.small_business_flags).length > 0 && (
            <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
              <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
                Small Business Certifications
              </h3>
              <div className="flex flex-wrap gap-2">
                {Object.entries(account.small_business_flags).map(([key, value]) => (
                  value && (
                    <span
                      key={key}
                      className="px-2 py-1 text-xs font-medium rounded-full bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-200"
                    >
                      {key.replace(/_/g, ' ').toUpperCase()}
                    </span>
                  )
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Tabs */}
        <div className="border-b border-gray-200 dark:border-gray-700 mb-6">
          <nav className="flex gap-6">
            <button
              onClick={() => setActiveTab('contacts')}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'contacts'
                  ? 'border-cyan-500 text-cyan-600 dark:text-cyan-400'
                  : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <Users className="w-4 h-4" />
                Contacts ({contacts.length})
              </div>
            </button>
            <button
              onClick={() => setActiveTab('opportunities')}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'opportunities'
                  ? 'border-cyan-500 text-cyan-600 dark:text-cyan-400'
                  : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <Target className="w-4 h-4" />
                Opportunities ({opportunities.length})
              </div>
            </button>
          </nav>
        </div>

        {/* Contacts Tab */}
        {activeTab === 'contacts' && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            {contacts.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50 dark:bg-gray-900">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Name</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Title</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Email</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Phone</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                    {contacts.map((contact) => (
                      <tr
                        key={contact.id}
                        onClick={() => router.push(orgUrl(`/syncs/salesforce/contacts/${contact.id}`))}
                        className="hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
                      >
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm font-medium text-gray-900 dark:text-white">
                            {contact.first_name} {contact.last_name}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                          {contact.title || '-'}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          {contact.email ? (
                            <a
                              href={`mailto:${contact.email}`}
                              onClick={(e) => e.stopPropagation()}
                              className="text-sm text-cyan-600 dark:text-cyan-400 hover:underline flex items-center gap-1"
                            >
                              <Mail className="w-4 h-4" />
                              {contact.email}
                            </a>
                          ) : (
                            <span className="text-sm text-gray-400">-</span>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                          {contact.phone || '-'}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          {contact.is_current_employee !== false ? (
                            <span className="flex items-center gap-1 text-green-600 dark:text-green-400 text-sm">
                              <CheckCircle className="w-4 h-4" />
                              Active
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 text-gray-400 text-sm">
                              <XCircle className="w-4 h-4" />
                              Former
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-12 text-center">
                <Users className="w-12 h-12 mx-auto mb-4 text-gray-400" />
                <p className="text-gray-500 dark:text-gray-400">No contacts for this account</p>
              </div>
            )}
          </div>
        )}

        {/* Opportunities Tab */}
        {activeTab === 'opportunities' && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            {opportunities.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50 dark:bg-gray-900">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Name</th>
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
                        onClick={() => router.push(orgUrl(`/syncs/salesforce/opportunities/${opp.id}`))}
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
            ) : (
              <div className="p-12 text-center">
                <Target className="w-12 h-12 mx-auto mb-4 text-gray-400" />
                <p className="text-gray-500 dark:text-gray-400">No opportunities for this account</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

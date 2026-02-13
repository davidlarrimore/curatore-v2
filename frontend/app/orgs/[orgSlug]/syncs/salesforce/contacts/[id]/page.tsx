'use client'

import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { useOrgUrl } from '@/lib/org-url-context'
import { salesforceApi, SalesforceContact } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import {
  Users,
  RefreshCw,
  AlertTriangle,
  Mail,
  Phone,
  Smartphone,
  Building2,
  MapPin,
  CheckCircle,
  XCircle,
  Briefcase,
  ExternalLink,
} from 'lucide-react'

interface Address {
  street?: string
  city?: string
  state?: string
  postal_code?: string
  country?: string
}

export default function SalesforceContactDetailPage() {
  const params = useParams()
  const { token } = useAuth()
  const { orgSlug } = useOrgUrl()
  const contactId = params.id as string

  // Helper for org-scoped URLs
  const orgUrl = (path: string) => `/orgs/${orgSlug}${path}`

  // State
  const [contact, setContact] = useState<SalesforceContact | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  // Load data
  const loadData = useCallback(async () => {
    if (!token || !contactId) return

    setIsLoading(true)
    setError('')

    try {
      const contactRes = await salesforceApi.getContact(token, contactId)
      setContact(contactRes)
    } catch (err: unknown) {
      const error = err as { message?: string }
      setError(error.message || 'Failed to load contact')
    } finally {
      setIsLoading(false)
    }
  }, [token, contactId])

  useEffect(() => {
    loadData()
  }, [loadData])

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

  if (error || !contact) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="p-6 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl">
            <div className="flex items-center gap-2 text-red-800 dark:text-red-200">
              <AlertTriangle className="w-5 h-5" />
              <span>{error || 'Contact not found'}</span>
            </div>
            <Link href={orgUrl('/syncs/salesforce/contacts')} className="mt-4 inline-block text-cyan-600 dark:text-cyan-400 hover:underline">
              Back to Contacts
            </Link>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-4">
          <Link href={orgUrl('/syncs/salesforce')} className="hover:text-gray-900 dark:hover:text-white">
            Salesforce
          </Link>
          <span>/</span>
          <Link href={orgUrl('/syncs/salesforce/contacts')} className="hover:text-gray-900 dark:hover:text-white">
            Contacts
          </Link>
          <span>/</span>
          <span className="text-gray-900 dark:text-white">{contact.first_name} {contact.last_name}</span>
        </div>

        {/* Header */}
        <div className="mb-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="flex items-start gap-4">
              <div className="flex items-center justify-center w-16 h-16 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 text-white shadow-lg shadow-blue-500/25">
                <span className="text-xl font-bold">
                  {contact.first_name?.[0] || ''}{contact.last_name[0]}
                </span>
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  {contact.first_name} {contact.last_name}
                </h1>
                {contact.title && (
                  <div className="flex items-center gap-2 mt-1 text-gray-600 dark:text-gray-300">
                    <Briefcase className="w-4 h-4" />
                    <span>{contact.title}</span>
                  </div>
                )}
                <div className="flex items-center gap-2 mt-2">
                  {contact.is_current_employee !== false ? (
                    <span className="flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-200">
                      <CheckCircle className="w-3 h-3" />
                      Active Employee
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                      <XCircle className="w-3 h-3" />
                      Former Employee
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-2">
                  SF ID: {contact.salesforce_id}
                </p>
              </div>
            </div>
            <div className="flex gap-2">
              <a
                href={`https://amivero.lightning.force.com/lightning/r/Contact/${contact.salesforce_id}/view`}
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

        {/* Contact Details Card */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Contact Information</h2>

          <div className="space-y-4">
            {/* Account */}
            {contact.account_name && (
              <div className="flex items-center gap-3">
                <Building2 className="w-5 h-5 text-gray-400" />
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Account</div>
                  <Link
                    href={orgUrl(`/syncs/salesforce/accounts/${contact.account_id}`)}
                    className="text-sm text-cyan-600 dark:text-cyan-400 hover:underline"
                  >
                    {contact.account_name}
                  </Link>
                </div>
              </div>
            )}

            {/* Email */}
            {contact.email && (
              <div className="flex items-center gap-3">
                <Mail className="w-5 h-5 text-gray-400" />
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Email</div>
                  <a
                    href={`mailto:${contact.email}`}
                    className="text-sm text-cyan-600 dark:text-cyan-400 hover:underline"
                  >
                    {contact.email}
                  </a>
                </div>
              </div>
            )}

            {/* Phone */}
            {contact.phone && (
              <div className="flex items-center gap-3">
                <Phone className="w-5 h-5 text-gray-400" />
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Phone</div>
                  <a
                    href={`tel:${contact.phone}`}
                    className="text-sm text-gray-900 dark:text-white hover:text-cyan-600 dark:hover:text-cyan-400"
                  >
                    {contact.phone}
                  </a>
                </div>
              </div>
            )}

            {/* Mobile */}
            {contact.mobile_phone && (
              <div className="flex items-center gap-3">
                <Smartphone className="w-5 h-5 text-gray-400" />
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Mobile</div>
                  <a
                    href={`tel:${contact.mobile_phone}`}
                    className="text-sm text-gray-900 dark:text-white hover:text-cyan-600 dark:hover:text-cyan-400"
                  >
                    {contact.mobile_phone}
                  </a>
                </div>
              </div>
            )}

            {/* Department */}
            {contact.department && (
              <div className="flex items-center gap-3">
                <Building2 className="w-5 h-5 text-gray-400" />
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Department</div>
                  <div className="text-sm text-gray-900 dark:text-white">{contact.department}</div>
                </div>
              </div>
            )}

            {/* Mailing Address */}
            {formatAddress(contact.mailing_address as Address) && (
              <div className="flex items-start gap-3">
                <MapPin className="w-5 h-5 text-gray-400 mt-0.5" />
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Mailing Address</div>
                  <div className="text-sm text-gray-900 dark:text-white">
                    {formatAddress(contact.mailing_address as Address)}
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700 flex flex-wrap gap-3">
            {contact.email && (
              <a href={`mailto:${contact.email}`}>
                <Button variant="secondary" size="sm" className="gap-2">
                  <Mail className="w-4 h-4" />
                  Send Email
                </Button>
              </a>
            )}
            {contact.phone && (
              <a href={`tel:${contact.phone}`}>
                <Button variant="secondary" size="sm" className="gap-2">
                  <Phone className="w-4 h-4" />
                  Call
                </Button>
              </a>
            )}
            {contact.account_id && (
              <Link href={orgUrl(`/syncs/salesforce/accounts/${contact.account_id}`)}>
                <Button variant="secondary" size="sm" className="gap-2">
                  <Building2 className="w-4 h-4" />
                  View Account
                </Button>
              </Link>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

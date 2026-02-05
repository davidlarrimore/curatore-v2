'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/lib/auth-context'
import { salesforceApi, SalesforceContact } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import {
  Users,
  RefreshCw,
  AlertTriangle,
  Search,
  ChevronLeft,
  ChevronRight,
  ArrowLeft,
  Mail,
  Phone,
  CheckCircle,
  XCircle,
} from 'lucide-react'

export default function SalesforceContactsPage() {
  return (
    <ProtectedRoute>
      <SalesforceContactsContent />
    </ProtectedRoute>
  )
}

function SalesforceContactsContent() {
  const router = useRouter()
  const { token } = useAuth()

  // State
  const [contacts, setContacts] = useState<SalesforceContact[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  // Filters
  const [keyword, setKeyword] = useState('')
  const [currentOnly, setCurrentOnly] = useState(false)

  // Pagination
  const [page, setPage] = useState(1)
  const limit = 25

  // Load data
  const loadData = useCallback(async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const offset = (page - 1) * limit
      const result = await salesforceApi.listContacts(token, {
        keyword: keyword || undefined,
        current_only: currentOnly,
        limit,
        offset,
      })
      setContacts(result.items)
      setTotal(result.total)
    } catch (err: any) {
      setError(err.message || 'Failed to load contacts')
    } finally {
      setIsLoading(false)
    }
  }, [token, page, keyword, currentOnly])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Handle search
  const handleSearch = () => {
    setPage(1)
    loadData()
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
              <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 text-white shadow-lg shadow-blue-500/25">
                <Users className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">
                  Contacts
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  {total.toLocaleString()} contacts
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
                  placeholder="Search contacts..."
                  className="w-full pl-10 pr-4 py-2 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
                />
              </div>
            </div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={currentOnly}
                onChange={(e) => { setCurrentOnly(e.target.checked); setPage(1); }}
                className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-cyan-600 focus:ring-cyan-500"
              />
              <span className="text-sm text-gray-700 dark:text-gray-300">Current employees only</span>
            </label>
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

        {/* Contacts Table */}
        {!isLoading && contacts.length > 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50 dark:bg-gray-900">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Name</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Title</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Account</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Email</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Phone</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {contacts.map((contact) => (
                    <tr
                      key={contact.id}
                      onClick={() => router.push(`/salesforce/contacts/${contact.id}`)}
                      className="hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
                    >
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="text-sm font-medium text-gray-900 dark:text-white">
                          {contact.first_name} {contact.last_name}
                        </div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">
                          {contact.salesforce_id}
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                        {contact.title || '-'}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                        {contact.account_name || '-'}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        {contact.email ? (
                          <a
                            href={`mailto:${contact.email}`}
                            onClick={(e) => e.stopPropagation()}
                            className="flex items-center gap-1 text-sm text-cyan-600 dark:text-cyan-400 hover:underline"
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
        {!isLoading && contacts.length === 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-12 text-center">
            <Users className="w-12 h-12 mx-auto mb-4 text-gray-400" />
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
              No Contacts Found
            </h2>
            <p className="text-gray-500 dark:text-gray-400">
              {keyword || currentOnly
                ? 'Try adjusting your search filters'
                : 'Import Salesforce data to see contacts here'}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

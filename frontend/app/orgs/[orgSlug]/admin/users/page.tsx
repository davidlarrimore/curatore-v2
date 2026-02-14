'use client'

/**
 * Organization-scoped user membership management page.
 *
 * Shows all system users with toggle switches to control
 * organization membership. Admin users are always shown as members.
 */

import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '@/lib/auth-context'
import { useOrgUrl } from '@/lib/org-url-context'
import { usersApi } from '@/lib/api'
import { Badge } from '@/components/ui/Badge'
import { Users, Search, Loader2, Star } from 'lucide-react'
import toast from 'react-hot-toast'

interface MembershipUser {
  id: string
  email: string
  username: string
  full_name?: string
  role: string
  is_active: boolean
  is_member?: boolean | null
  is_primary_org?: boolean | null
  created_at: string
  last_login_at?: string | null
}

export default function UsersPage() {
  const { token } = useAuth()
  const { orgSlug } = useOrgUrl()
  const [users, setUsers] = useState<MembershipUser[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [toggling, setToggling] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const pageSize = 50

  const loadUsers = useCallback(async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const response = await usersApi.listAllUsers(token, {
        search: searchQuery || undefined,
        skip: page * pageSize,
        limit: pageSize,
      })
      setUsers(response.users as MembershipUser[])
      setTotal(response.total)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load users'
      setError(message)
    } finally {
      setIsLoading(false)
    }
  }, [token, searchQuery, page])

  useEffect(() => {
    loadUsers()
  }, [loadUsers])

  // Reset page when search changes
  useEffect(() => {
    setPage(0)
  }, [searchQuery])

  const handleToggle = async (userId: string, currentIsMember: boolean) => {
    if (!token) return

    const newValue = !currentIsMember
    setToggling(userId)

    try {
      await usersApi.updateUser(token, userId, { is_member: newValue })
      // Optimistic update
      setUsers((prev) =>
        prev.map((u) =>
          u.id === userId ? { ...u, is_member: newValue } : u
        )
      )
      toast.success(newValue ? 'User added to organization' : 'User removed from organization')
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to toggle membership'
      toast.error(message)
    } finally {
      setToggling(null)
    }
  }

  const getRoleBadgeVariant = (role: string): 'default' | 'secondary' | 'success' | 'warning' | 'error' | 'info' => {
    switch (role) {
      case 'admin':
        return 'error'
      case 'member':
        return 'info'
      default:
        return 'secondary'
    }
  }

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="h-full flex flex-col bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      {/* Header */}
      <div className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex justify-between items-center">
            <div className="flex items-center space-x-4">
              <div className="p-2.5 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl shadow-lg shadow-indigo-500/25">
                <Users className="h-6 w-6 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Org Members</h1>
                <p className="mt-0.5 text-sm text-gray-600 dark:text-gray-400">
                  Toggle user access to this organization
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          {error && (
            <div className="mb-6 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/50 p-4">
              <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          {/* Search */}
          <div className="mb-6">
            <div className="relative max-w-md">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400" />
              <input
                type="text"
                placeholder="Search by email, username, or name..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              />
            </div>
          </div>

          {/* Users Table */}
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm overflow-hidden">
            {isLoading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-8 w-8 text-indigo-600 dark:text-indigo-400 animate-spin" />
                <span className="ml-3 text-gray-600 dark:text-gray-400">Loading users...</span>
              </div>
            ) : (
              <>
                <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                  <thead className="bg-gray-50 dark:bg-gray-800/50">
                    <tr>
                      <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                        User
                      </th>
                      <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                        Role
                      </th>
                      <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                        Status
                      </th>
                      <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                        Org Access
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                    {users.map((user) => {
                      const isAdmin = user.role === 'admin'
                      const isMember = user.is_member ?? false
                      const isToggling = toggling === user.id
                      return (
                        <tr key={user.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-gray-900 dark:text-white">
                                  {user.full_name || user.username}
                                </span>
                                {user.is_primary_org && (
                                  <span title="Primary organization" className="text-amber-500">
                                    <Star className="h-3.5 w-3.5 fill-current" />
                                  </span>
                                )}
                              </div>
                              <div className="text-sm text-gray-500 dark:text-gray-400">
                                {user.email}
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <Badge variant={getRoleBadgeVariant(user.role)}>
                              {user.role}
                            </Badge>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <Badge variant={user.is_active ? 'success' : 'secondary'}>
                              {user.is_active ? 'Active' : 'Inactive'}
                            </Badge>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div className="flex items-center gap-3">
                              <button
                                type="button"
                                role="switch"
                                aria-checked={isMember}
                                disabled={isAdmin || isToggling}
                                onClick={() => handleToggle(user.id, isMember)}
                                className={`
                                  relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent
                                  transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2
                                  ${isMember ? 'bg-indigo-600' : 'bg-gray-200 dark:bg-gray-700'}
                                  ${isAdmin || isToggling ? 'opacity-60 cursor-not-allowed' : ''}
                                `}
                              >
                                <span
                                  className={`
                                    pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0
                                    transition duration-200 ease-in-out
                                    ${isMember ? 'translate-x-5' : 'translate-x-0'}
                                  `}
                                />
                              </button>
                              {isAdmin && (
                                <span className="text-xs text-gray-500 dark:text-gray-400">
                                  Always (admin)
                                </span>
                              )}
                              {isToggling && (
                                <Loader2 className="h-4 w-4 text-indigo-600 animate-spin" />
                              )}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>

                {users.length === 0 && (
                  <div className="text-center py-12">
                    <Users className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
                    <p className="text-sm font-medium text-gray-900 dark:text-white mb-1">No users found</p>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {searchQuery ? 'Try a different search term.' : 'No users in the system yet.'}
                    </p>
                  </div>
                )}

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-between px-6 py-3 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
                    <p className="text-sm text-gray-700 dark:text-gray-300">
                      Showing {page * pageSize + 1}-{Math.min((page + 1) * pageSize, total)} of {total}
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setPage((p) => Math.max(0, p - 1))}
                        disabled={page === 0}
                        className="px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Prev
                      </button>
                      <button
                        onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                        disabled={page >= totalPages - 1}
                        className="px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Next
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

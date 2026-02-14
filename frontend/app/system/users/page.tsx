'use client'

/**
 * System Users page.
 *
 * View all users across all organizations. Includes invite user form.
 */

import { useState, useEffect } from 'react'
import {
  Users,
  Search,
  Shield,
  UserCheck,
  UserPlus,
  Building2,
  Mail,
  RefreshCw,
} from 'lucide-react'
import { useAuth } from '@/lib/auth-context'
import { usersApi } from '@/lib/api'
import UserInviteForm from '@/components/users/UserInviteForm'
import toast from 'react-hot-toast'

interface User {
  id: string
  email: string
  username: string
  full_name?: string
  role: string
  organization_id: string | null
  organization_name?: string
  is_active: boolean
}

const roleColors: Record<string, string> = {
  admin: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400',
  member: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
}

export default function SystemUsersPage() {
  const { token } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [showInviteForm, setShowInviteForm] = useState(false)

  const loadUsers = async () => {
    if (!token) return

    try {
      const data = await usersApi.listAllUsers(token)
      setUsers(data.users as User[])
    } catch (error) {
      console.error('Failed to load users:', error)
      toast.error('Failed to load users')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadUsers()
  }, [token])

  const handleInviteSuccess = async () => {
    setShowInviteForm(false)
    await loadUsers()
  }

  const filteredUsers = searchQuery
    ? users.filter(
        (user) =>
          user.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
          user.username.toLowerCase().includes(searchQuery.toLowerCase()) ||
          user.full_name?.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : users

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-600"></div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            All Users
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            View and manage users across all organizations
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowInviteForm(!showInviteForm)}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors"
          >
            <UserPlus className="h-4 w-4" />
            Invite User
          </button>
          <button
            onClick={loadUsers}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* Invite Form */}
      {showInviteForm && (
        <UserInviteForm
          onSuccess={handleInviteSuccess}
          onCancel={() => setShowInviteForm(false)}
        />
      )}

      {/* Search and Filters */}
      <div className="flex items-center gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400" />
          <input
            type="text"
            placeholder="Search users by name, email, or username..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
          />
        </div>
      </div>

      {/* Users Table */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead className="bg-gray-50 dark:bg-gray-900/50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                User
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Organization
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Role
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Status
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
            {filteredUsers.map((user) => (
              <tr key={user.id} className="hover:bg-gray-50 dark:hover:bg-gray-900/30">
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center">
                      <span className="text-sm font-medium text-white">
                        {user.username.charAt(0).toUpperCase()}
                      </span>
                    </div>
                    <div>
                      <p className="font-medium text-gray-900 dark:text-white">
                        {user.full_name || user.username}
                      </p>
                      <p className="text-sm text-gray-500 dark:text-gray-400 flex items-center gap-1">
                        <Mail className="h-3 w-3" />
                        {user.email}
                      </p>
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  {user.organization_name ? (
                    <div className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                      <Building2 className="h-4 w-4 text-gray-400" />
                      {user.organization_name}
                    </div>
                  ) : (
                    <span className="text-sm text-amber-600 dark:text-amber-400 flex items-center gap-1">
                      <Shield className="h-4 w-4" />
                      System Admin
                    </span>
                  )}
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <span className={`px-2.5 py-1 text-xs font-medium rounded-full ${roleColors[user.role] || roleColors.member}`}>
                    {user.role}
                  </span>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  {user.is_active ? (
                    <span className="flex items-center gap-1 text-sm text-green-600 dark:text-green-400">
                      <UserCheck className="h-4 w-4" />
                      Active
                    </span>
                  ) : (
                    <span className="text-sm text-gray-500 dark:text-gray-400">
                      Inactive
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {filteredUsers.length === 0 && (
          <div className="text-center py-12">
            <Users className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <p className="text-gray-500 dark:text-gray-400">
              {searchQuery ? 'No users match your search' : 'No users found'}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@/lib/auth-context'
import { usersApi } from '@/lib/api'
import { formatDate } from '@/lib/date-utils'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import UserInviteForm from '@/components/users/UserInviteForm'
import UserEditForm from '@/components/users/UserEditForm'
import { Users, UserPlus, Loader2 } from 'lucide-react'

interface User {
  id: string
  email: string
  username: string
  full_name?: string
  role: string
  organization_id: string
  is_active: boolean
  created_at: string
  last_login?: string
}

export default function UsersPage() {
  return (
    <ProtectedRoute requiredRole="admin">
      <UsersContent />
    </ProtectedRoute>
  )
}

function UsersContent() {
  const { token, user: currentUser } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [showInviteForm, setShowInviteForm] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)

  useEffect(() => {
    if (token) {
      loadUsers()
    }
  }, [token])

  const loadUsers = async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const response = await usersApi.listUsers(token)
      setUsers(response.users)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load users')
    } finally {
      setIsLoading(false)
    }
  }

  const handleInviteSuccess = async () => {
    setShowInviteForm(false)
    await loadUsers()
  }

  const handleEditSuccess = async () => {
    setEditingUser(null)
    await loadUsers()
  }

  const handleToggleActive = async (userId: string, isActive: boolean) => {
    if (!token) return
    if (!confirm(`Are you sure you want to ${isActive ? 'deactivate' : 'activate'} this user?`)) return

    try {
      await usersApi.updateUser(token, userId, { is_active: !isActive })
      await loadUsers()
    } catch (err: unknown) {
      alert(`Failed to update user: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  const handleDelete = async (userId: string) => {
    if (!token) return
    if (!confirm('Are you sure you want to delete this user? This action cannot be undone.')) return

    try {
      await usersApi.deleteUser(token, userId)
      await loadUsers()
    } catch (err: unknown) {
      alert(`Failed to delete user: ${err instanceof Error ? err.message : String(err)}`)
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

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="text-center">
          <Loader2 className="h-12 w-12 text-indigo-600 dark:text-indigo-400 animate-spin mx-auto" />
          <p className="mt-4 text-gray-600 dark:text-gray-400">Loading users...</p>
        </div>
      </div>
    )
  }

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
                <h1 className="text-2xl font-bold text-gray-900 dark:text-white">User Management</h1>
                <p className="mt-0.5 text-sm text-gray-600 dark:text-gray-400">
                  Invite users, manage roles, and control access
                </p>
              </div>
            </div>
            <Button onClick={() => setShowInviteForm(true)} className="inline-flex items-center">
              <UserPlus className="w-4 h-4 mr-2" />
              Invite User
            </Button>
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

          {showInviteForm && (
            <div className="mb-8">
              <UserInviteForm
                onSuccess={handleInviteSuccess}
                onCancel={() => setShowInviteForm(false)}
              />
            </div>
          )}

          {editingUser && (
            <div className="mb-8">
              <UserEditForm
                user={editingUser}
                onSuccess={handleEditSuccess}
                onCancel={() => setEditingUser(null)}
              />
            </div>
          )}

          {/* Users Table */}
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm overflow-hidden">
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
                    Last Login
                  </th>
                  <th className="px-6 py-3.5 text-right text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                {users.map((user) => (
                  <tr key={user.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <div>
                          <div className="text-sm font-medium text-gray-900 dark:text-white">
                            {user.full_name || user.username}
                            {user.id === currentUser?.id && (
                              <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">(You)</span>
                            )}
                          </div>
                          <div className="text-sm text-gray-500 dark:text-gray-400">
                            {user.email}
                          </div>
                          <div className="text-xs text-gray-400 dark:text-gray-500">
                            @{user.username}
                          </div>
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
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                      {user.last_login ? formatDate(user.last_login) : 'Never'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => setEditingUser(user)}
                        >
                          Edit
                        </Button>
                        {user.id !== currentUser?.id && (
                          <>
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => handleToggleActive(user.id, user.is_active)}
                            >
                              {user.is_active ? 'Deactivate' : 'Activate'}
                            </Button>
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() => handleDelete(user.id)}
                            >
                              Delete
                            </Button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {users.length === 0 && (
              <div className="text-center py-12">
                <Users className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
                <p className="text-sm font-medium text-gray-900 dark:text-white mb-1">No users found</p>
                <p className="text-sm text-gray-500 dark:text-gray-400">Invite users to get started.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

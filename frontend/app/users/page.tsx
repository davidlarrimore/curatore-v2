'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@/lib/auth-context'
import { usersApi } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import UserInviteForm from '@/components/users/UserInviteForm'
import UserEditForm from '@/components/users/UserEditForm'

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
    } catch (err: any) {
      setError(err.detail || err.message || 'Failed to load users')
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
    } catch (err: any) {
      alert(`Failed to update user: ${err.detail || err.message}`)
    }
  }

  const handleDelete = async (userId: string) => {
    if (!token) return
    if (!confirm('Are you sure you want to delete this user? This action cannot be undone.')) return

    try {
      await usersApi.deleteUser(token, userId)
      await loadUsers()
    } catch (err: any) {
      alert(`Failed to delete user: ${err.detail || err.message}`)
    }
  }

  const getRoleBadgeVariant = (role: string) => {
    switch (role) {
      case 'admin':
        return 'error'
      case 'user':
        return 'primary'
      default:
        return 'secondary'
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-gray-600 dark:text-gray-400">Loading users...</p>
      </div>
    )
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-7xl">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">User Management</h1>
          <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
            Invite users, manage roles, and control access
          </p>
        </div>
        <Button onClick={() => setShowInviteForm(true)}>
          + Invite User
        </Button>
      </div>

      {error && (
        <div className="mb-6 rounded-md bg-red-50 dark:bg-red-900/20 p-4">
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
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead className="bg-gray-50 dark:bg-gray-900">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                User
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Role
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Status
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Last Login
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
            {users.map((user) => (
              <tr key={user.id} className="hover:bg-gray-50 dark:hover:bg-gray-900">
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
                  {user.last_login ? new Date(user.last_login).toLocaleDateString() : 'Never'}
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
            <p className="text-gray-600 dark:text-gray-400">No users found</p>
          </div>
        )}
      </div>
    </div>
  )
}

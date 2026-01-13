'use client'

import { useState, FormEvent } from 'react'
import { useAuth } from '@/lib/auth-context'
import { usersApi } from '@/lib/api'
import { Button } from '../ui/Button'

interface UserInviteFormProps {
  onSuccess: () => void
  onCancel: () => void
}

export default function UserInviteForm({ onSuccess, onCancel }: UserInviteFormProps) {
  const { token } = useAuth()
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState('user')
  const [sendEmail, setSendEmail] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [temporaryPassword, setTemporaryPassword] = useState('')

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!token) return

    setIsLoading(true)
    setError('')
    setTemporaryPassword('')

    try {
      const response = await usersApi.inviteUser(token, {
        email,
        full_name: fullName || undefined,
        role,
        send_email: sendEmail,
      })

      if (response.temporary_password) {
        setTemporaryPassword(response.temporary_password)
        alert(`✅ User invited successfully!\n\nTemporary Password: ${response.temporary_password}\n\nPlease save this password as it won't be shown again.`)
      } else {
        alert('✅ User invited successfully! An email has been sent with login instructions.')
      }

      onSuccess()
    } catch (err: any) {
      setError(err.detail || err.message || 'Failed to invite user')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
      <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
        Invite New User
      </h2>

      {error && (
        <div className="mb-4 rounded-md bg-red-50 dark:bg-red-900/20 p-4">
          <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
        </div>
      )}

      {temporaryPassword && (
        <div className="mb-4 rounded-md bg-green-50 dark:bg-green-900/20 p-4">
          <p className="text-sm font-semibold text-green-800 dark:text-green-200 mb-2">
            Temporary Password (save this!):
          </p>
          <code className="block p-2 bg-white dark:bg-gray-900 rounded text-sm">
            {temporaryPassword}
          </code>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="email" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Email Address *
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            placeholder="user@example.com"
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
          />
        </div>

        <div>
          <label htmlFor="fullName" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Full Name
          </label>
          <input
            id="fullName"
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="John Doe"
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
          />
        </div>

        <div>
          <label htmlFor="role" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Role
          </label>
          <select
            id="role"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
          >
            <option value="user">User</option>
            <option value="admin">Admin</option>
          </select>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            Admins can manage users, connections, and organization settings
          </p>
        </div>

        <div>
          <label className="flex items-center">
            <input
              type="checkbox"
              checked={sendEmail}
              onChange={(e) => setSendEmail(e.target.checked)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="ml-2 text-sm text-gray-700 dark:text-gray-300">
              Send email invitation (if unchecked, a temporary password will be generated)
            </span>
          </label>
        </div>

        <div className="flex gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
          <Button type="submit" disabled={isLoading}>
            {isLoading ? 'Inviting...' : 'Invite User'}
          </Button>
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </div>
  )
}

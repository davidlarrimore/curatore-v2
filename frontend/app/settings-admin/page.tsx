'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@/lib/auth-context'
import { settingsApi } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'

export default function SettingsAdminPage() {
  return (
    <ProtectedRoute requiredRole="admin">
      <SettingsAdminContent />
    </ProtectedRoute>
  )
}

function SettingsAdminContent() {
  const { token, user } = useAuth()
  const [orgSettings, setOrgSettings] = useState<Record<string, any>>({})
  const [userSettings, setUserSettings] = useState<Record<string, any>>({})
  const [editedOrgSettings, setEditedOrgSettings] = useState<Record<string, any>>({})
  const [editedUserSettings, setEditedUserSettings] = useState<Record<string, any>>({})
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState<'organization' | 'user'>('organization')
  const [showMergedPreview, setShowMergedPreview] = useState(false)

  useEffect(() => {
    if (token) {
      loadSettings()
    }
  }, [token])

  const loadSettings = async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const [orgData, userData] = await Promise.all([
        settingsApi.getOrganizationSettings(token),
        settingsApi.getUserSettings(token),
      ])

      setOrgSettings(orgData.settings || {})
      setEditedOrgSettings(orgData.settings || {})
      setUserSettings(userData.settings || {})
      setEditedUserSettings(userData.settings || {})
    } catch (err: any) {
      setError(err.detail || err.message || 'Failed to load settings')
    } finally {
      setIsLoading(false)
    }
  }

  const handleSaveOrgSettings = async () => {
    if (!token) return

    setIsSaving(true)
    setError('')

    try {
      await settingsApi.updateOrganizationSettings(token, editedOrgSettings)
      setOrgSettings(editedOrgSettings)
      alert('✅ Organization settings saved successfully!')
    } catch (err: any) {
      setError(err.detail || err.message || 'Failed to save organization settings')
    } finally {
      setIsSaving(false)
    }
  }

  const handleSaveUserSettings = async () => {
    if (!token) return

    setIsSaving(true)
    setError('')

    try {
      await settingsApi.updateUserSettings(token, editedUserSettings)
      setUserSettings(editedUserSettings)
      alert('✅ User settings saved successfully!')
    } catch (err: any) {
      setError(err.detail || err.message || 'Failed to save user settings')
    } finally {
      setIsSaving(false)
    }
  }

  const handleOrgSettingChange = (key: string, value: any) => {
    setEditedOrgSettings(prev => ({ ...prev, [key]: value }))
  }

  const handleUserSettingChange = (key: string, value: any) => {
    setEditedUserSettings(prev => ({ ...prev, [key]: value }))
  }

  const getMergedSettings = () => {
    return { ...orgSettings, ...userSettings }
  }

  const renderSettingField = (key: string, value: any, onChange: (key: string, value: any) => void) => {
    const isNumber = typeof value === 'number'
    const isBoolean = typeof value === 'boolean'

    if (isBoolean) {
      return (
        <label className="flex items-center space-x-2">
          <input
            type="checkbox"
            checked={value}
            onChange={(e) => onChange(key, e.target.checked)}
            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <span className="text-sm text-gray-700 dark:text-gray-300">{key}</span>
        </label>
      )
    }

    return (
      <div>
        <label htmlFor={key} className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          {key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
        </label>
        <input
          id={key}
          type={isNumber ? 'number' : 'text'}
          value={value}
          onChange={(e) => onChange(key, isNumber ? Number(e.target.value) : e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
        />
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-gray-600 dark:text-gray-400">Loading settings...</p>
      </div>
    )
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-5xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Settings Management</h1>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
          Configure organization-wide and user-specific settings
        </p>
      </div>

      {error && (
        <div className="mb-6 rounded-md bg-red-50 dark:bg-red-900/20 p-4">
          <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
        </div>
      )}

      {/* Tabs */}
      <div className="mb-6 border-b border-gray-200 dark:border-gray-700">
        <nav className="flex space-x-8">
          <button
            onClick={() => setActiveTab('organization')}
            className={`py-4 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'organization'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            Organization Settings
          </button>
          <button
            onClick={() => setActiveTab('user')}
            className={`py-4 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'user'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            User Settings
          </button>
        </nav>
      </div>

      {/* Settings Content */}
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
        {activeTab === 'organization' ? (
          <div className="space-y-6">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Organization-Wide Settings
              </h2>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                These settings apply to all users in your organization. They can be overridden by individual user settings.
              </p>
            </div>

            <div className="space-y-4">
              {Object.entries(editedOrgSettings).map(([key, value]) => (
                <div key={key}>
                  {renderSettingField(key, value, handleOrgSettingChange)}
                </div>
              ))}
            </div>

            <div className="flex gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
              <Button onClick={handleSaveOrgSettings} disabled={isSaving}>
                {isSaving ? 'Saving...' : 'Save Organization Settings'}
              </Button>
              <Button variant="secondary" onClick={loadSettings}>
                Reset
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                User-Specific Settings
              </h2>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                These settings override organization defaults for user <strong>{user?.username}</strong>.
              </p>
            </div>

            <div className="space-y-4">
              {Object.entries(editedUserSettings).map(([key, value]) => (
                <div key={key}>
                  {renderSettingField(key, value, handleUserSettingChange)}
                </div>
              ))}
            </div>

            <div className="flex gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
              <Button onClick={handleSaveUserSettings} disabled={isSaving}>
                {isSaving ? 'Saving...' : 'Save User Settings'}
              </Button>
              <Button variant="secondary" onClick={loadSettings}>
                Reset
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Merged Settings Preview */}
      <div className="mt-6">
        <button
          onClick={() => setShowMergedPreview(!showMergedPreview)}
          className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
        >
          {showMergedPreview ? 'Hide' : 'Show'} Merged Settings Preview
        </button>

        {showMergedPreview && (
          <div className="mt-4 bg-gray-50 dark:bg-gray-900 rounded-lg p-4 border border-gray-200 dark:border-gray-700">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">
              Effective Settings (Organization + User Overrides)
            </h3>
            <pre className="text-xs text-gray-700 dark:text-gray-300 overflow-auto">
              {JSON.stringify(getMergedSettings(), null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}

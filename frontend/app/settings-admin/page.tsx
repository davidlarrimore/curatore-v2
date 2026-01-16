'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@/lib/auth-context'
import { settingsApi } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import { JobStatsWidget } from '@/components/admin/JobStatsWidget'

export default function SettingsAdminPage() {
  return (
    <ProtectedRoute requiredRole="org_admin">
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
  const [activeTab, setActiveTab] = useState<'organization' | 'user' | 'jobs'>('organization')
  const [showMergedPreview, setShowMergedPreview] = useState(false)

  // Job management settings
  const [jobConcurrencyLimit, setJobConcurrencyLimit] = useState(3)
  const [jobRetentionDays, setJobRetentionDays] = useState(30)

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

      // Load job management settings from organization settings
      if (orgData.settings) {
        setJobConcurrencyLimit(orgData.settings.job_concurrency_limit || 3)
        setJobRetentionDays(orgData.settings.job_retention_days || 30)
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load settings')
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
      setError(err.message || 'Failed to save organization settings')
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
      setError(err.message || 'Failed to save user settings')
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

  const handleSaveJobSettings = async () => {
    if (!token) return

    setIsSaving(true)
    setError('')

    try {
      const updatedSettings = {
        ...editedOrgSettings,
        job_concurrency_limit: jobConcurrencyLimit,
        job_retention_days: jobRetentionDays
      }
      await settingsApi.updateOrganizationSettings(token, updatedSettings)
      setOrgSettings(updatedSettings)
      setEditedOrgSettings(updatedSettings)
      alert('✅ Job management settings saved successfully!')
    } catch (err: any) {
      setError(err.message || 'Failed to save job settings')
    } finally {
      setIsSaving(false)
    }
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
          <button
            onClick={() => setActiveTab('jobs')}
            className={`py-4 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'jobs'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            Job Management
          </button>
        </nav>
      </div>

      {/* Settings Content */}
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
        {activeTab === 'organization' && (
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
        )}

        {activeTab === 'user' && (
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

        {activeTab === 'jobs' && (
          <div className="space-y-6">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Job Management
              </h2>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                Monitor job activity and configure processing settings across your organization.
              </p>
            </div>

            {/* Job Statistics Widget */}
            <JobStatsWidget />

            {/* Settings Section */}
            <div className="border-t border-gray-200 dark:border-gray-700 pt-6">
              <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-4">
                Job Processing Settings
              </h3>
            </div>

            <div className="space-y-6">
              {/* Concurrent Job Limit */}
              <div>
                <label htmlFor="job-concurrency" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Concurrent Job Limit
                </label>
                <select
                  id="job-concurrency"
                  value={jobConcurrencyLimit}
                  onChange={(e) => setJobConcurrencyLimit(Number(e.target.value))}
                  className="w-full max-w-xs px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                >
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(num => (
                    <option key={num} value={num}>{num}</option>
                  ))}
                </select>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  Maximum number of jobs that can run simultaneously per organization
                </p>
              </div>

              {/* Job Retention Days */}
              <div>
                <label htmlFor="job-retention" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Job Retention Period
                </label>
                <select
                  id="job-retention"
                  value={jobRetentionDays}
                  onChange={(e) => setJobRetentionDays(Number(e.target.value))}
                  className="w-full max-w-xs px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                >
                  <option value={7}>7 days</option>
                  <option value={30}>30 days</option>
                  <option value={90}>90 days</option>
                  <option value={0}>Indefinite (never delete)</option>
                </select>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  How long to keep completed job records before automatic cleanup
                </p>
              </div>

              {/* Info Box */}
              <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
                <div className="flex">
                  <div className="flex-shrink-0">
                    <svg className="h-5 w-5 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <div className="ml-3">
                    <h3 className="text-sm font-medium text-blue-800 dark:text-blue-200">
                      About Job Management
                    </h3>
                    <div className="mt-2 text-sm text-blue-700 dark:text-blue-300">
                      <ul className="list-disc list-inside space-y-1">
                        <li>Concurrent job limit prevents resource exhaustion</li>
                        <li>Job retention helps maintain storage efficiency</li>
                        <li>Changes take effect immediately for new jobs</li>
                        <li>Running jobs continue with original settings</li>
                      </ul>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="flex gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
              <Button onClick={handleSaveJobSettings} disabled={isSaving}>
                {isSaving ? 'Saving...' : 'Save Job Settings'}
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

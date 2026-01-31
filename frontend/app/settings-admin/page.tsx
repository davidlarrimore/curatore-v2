'use client'

import { useState, useEffect } from 'react'
import { useSearchParams } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { settingsApi, systemApi, usersApi } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import InfrastructureHealthPanel from '@/components/admin/InfrastructureHealthPanel'
import SystemMaintenanceTab from '@/components/admin/SystemMaintenanceTab'
import UserInviteForm from '@/components/users/UserInviteForm'
import UserEditForm from '@/components/users/UserEditForm'
import {
  Settings,
  Building2,
  User,
  Server,
  Info,
  Loader2,
  ChevronDown,
  ChevronUp,
  FileText,
  Lock,
  Users,
  UserPlus,
  Wrench,
} from 'lucide-react'

interface UserData {
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
  const searchParams = useSearchParams()
  const initialTab = searchParams.get('tab') as 'organization' | 'user' | 'infrastructure' | 'users' | 'maintenance' | null
  const [activeTab, setActiveTab] = useState<'organization' | 'user' | 'infrastructure' | 'users' | 'maintenance'>(initialTab || 'organization')
  const [showMergedPreview, setShowMergedPreview] = useState(false)

  // Users management state
  const [users, setUsers] = useState<UserData[]>([])
  const [showInviteForm, setShowInviteForm] = useState(false)
  const [editingUser, setEditingUser] = useState<UserData | null>(null)

  // Extraction engine settings
  const [availableEngines, setAvailableEngines] = useState<Array<{
    id: string
    name: string
    display_name: string
    description: string
  }>>([])
  const [defaultEngine, setDefaultEngine] = useState<string>('')
  const [defaultEngineSource, setDefaultEngineSource] = useState<string | null>(null)
  const [isEngineFromConfig, setIsEngineFromConfig] = useState(false)

  useEffect(() => {
    if (token) {
      loadSettings()
    }
  }, [token])

  useEffect(() => {
    if (token && activeTab === 'users') {
      loadUsers()
    }
  }, [token, activeTab])

  const loadSettings = async () => {
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      // Load organization settings and extraction engines
      const [orgData, enginesData] = await Promise.all([
        settingsApi.getOrganizationSettings(token),
        systemApi.getExtractionEngines(),
      ])

      // Try to load user settings, but don't fail if endpoint doesn't exist
      let userData = { settings: {} }
      try {
        userData = await settingsApi.getUserSettings(token)
      } catch (userErr: any) {
        console.warn('User settings not available:', userErr.message)
      }

      setOrgSettings(orgData.settings || {})
      setEditedOrgSettings(orgData.settings || {})
      setUserSettings(userData.settings || {})
      setEditedUserSettings(userData.settings || {})

      // Load extraction engine settings
      if (enginesData && Array.isArray(enginesData.engines)) {
        console.log('Loaded engines:', enginesData.engines)
        setAvailableEngines(enginesData.engines)
        setDefaultEngineSource(enginesData.default_engine_source)
        setIsEngineFromConfig(enginesData.default_engine_source === 'config.yml')

        // If default is from config.yml, use that; otherwise use org setting
        if (enginesData.default_engine_source === 'config.yml') {
          setDefaultEngine(enginesData.default_engine || '')
        } else {
          setDefaultEngine(orgData.settings?.default_extraction_engine || enginesData.default_engine || '')
        }
      } else {
        console.warn('No engines data or invalid format:', enginesData)
        setAvailableEngines([])
      }
    } catch (err: any) {
      console.error('Failed to load settings:', err)
      setError(err.message || 'Failed to load settings')
    } finally {
      setIsLoading(false)
    }
  }

  const loadUsers = async () => {
    if (!token) return

    try {
      const response = await usersApi.listUsers(token)
      setUsers(response.users)
    } catch (err: any) {
      setError(err.message || 'Failed to load users')
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
      alert(`Failed to update user: ${err.message}`)
    }
  }

  const handleDeleteUser = async (userId: string) => {
    if (!token) return
    if (!confirm('Are you sure you want to delete this user? This action cannot be undone.')) return

    try {
      await usersApi.deleteUser(token, userId)
      await loadUsers()
    } catch (err: any) {
      alert(`Failed to delete user: ${err.message}`)
    }
  }

  const getRoleBadgeVariant = (role: string): 'default' | 'secondary' | 'success' | 'warning' | 'error' | 'info' => {
    switch (role) {
      case 'admin':
        return 'error'
      case 'user':
        return 'info'
      default:
        return 'secondary'
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

  const handleSaveExtractionEngine = async () => {
    if (!token) return

    setIsSaving(true)
    setError('')

    try {
      const updatedSettings = {
        ...editedOrgSettings,
        default_extraction_engine: defaultEngine
      }
      await settingsApi.updateOrganizationSettings(token, updatedSettings)
      setOrgSettings(updatedSettings)
      setEditedOrgSettings(updatedSettings)
      alert('✅ Default extraction engine saved successfully!')
    } catch (err: any) {
      setError(err.message || 'Failed to save extraction engine')
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
            className="rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-500 bg-white dark:bg-gray-800"
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
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
        />
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
        <div className="text-center">
          <Loader2 className="h-12 w-12 text-indigo-600 dark:text-indigo-400 animate-spin mx-auto" />
          <p className="mt-4 text-gray-600 dark:text-gray-400">Loading settings...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      {/* Header */}
      <div className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center space-x-4">
            <div className="p-2.5 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl shadow-lg shadow-indigo-500/25">
              <Settings className="h-6 w-6 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Settings Management</h1>
              <p className="mt-0.5 text-sm text-gray-600 dark:text-gray-400">
                Configure organization-wide and user-specific settings
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          {error && (
            <div className="mb-6 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/50 p-4">
              <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          {/* Tabs */}
          <div className="mb-6 border-b border-gray-200 dark:border-gray-700">
            <nav className="flex space-x-8">
              <button
                onClick={() => setActiveTab('organization')}
                className={`flex items-center py-4 px-1 border-b-2 font-medium text-sm ${
                  activeTab === 'organization'
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
                }`}
              >
                <Building2 className="w-4 h-4 mr-2" />
                Organization
              </button>
              <button
                onClick={() => setActiveTab('user')}
                className={`flex items-center py-4 px-1 border-b-2 font-medium text-sm ${
                  activeTab === 'user'
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
                }`}
              >
                <User className="w-4 h-4 mr-2" />
                User Settings
              </button>
              <button
                onClick={() => setActiveTab('infrastructure')}
                className={`flex items-center py-4 px-1 border-b-2 font-medium text-sm ${
                  activeTab === 'infrastructure'
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
                }`}
              >
                <Server className="w-4 h-4 mr-2" />
                Infrastructure
              </button>
              <button
                onClick={() => setActiveTab('users')}
                className={`flex items-center py-4 px-1 border-b-2 font-medium text-sm ${
                  activeTab === 'users'
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
                }`}
              >
                <Users className="w-4 h-4 mr-2" />
                Users
              </button>
              <button
                onClick={() => setActiveTab('maintenance')}
                className={`flex items-center py-4 px-1 border-b-2 font-medium text-sm ${
                  activeTab === 'maintenance'
                    ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
                }`}
              >
                <Wrench className="w-4 h-4 mr-2" />
                Maintenance
              </button>
            </nav>
          </div>

          {/* Settings Content */}
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm p-6">
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

            {/* Default Extraction Engine Section */}
            <div className="border-b border-gray-200 dark:border-gray-700 pb-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-500 flex items-center justify-center text-white shadow-lg">
                  <FileText className="w-5 h-5" />
                </div>
                <div className="flex-1">
                  <h3 className="text-base font-semibold text-gray-900 dark:text-white">
                    Default Extraction Engine
                  </h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                    Choose which engine to use for document extraction by default
                  </p>
                </div>
              </div>

              {isEngineFromConfig && (
                <div className="mb-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/50 rounded-lg p-4">
                  <div className="flex">
                    <div className="flex-shrink-0">
                      <Lock className="h-5 w-5 text-amber-500 dark:text-amber-400" />
                    </div>
                    <div className="ml-3">
                      <h4 className="text-sm font-medium text-amber-800 dark:text-amber-200">
                        Configured in config.yml
                      </h4>
                      <div className="mt-1 text-sm text-amber-700 dark:text-amber-300">
                        The default extraction engine is set in <code className="bg-amber-100 dark:bg-amber-900/50 px-1 py-0.5 rounded">config.yml</code> and cannot be changed here.
                        To change it, update the <code className="bg-amber-100 dark:bg-amber-900/50 px-1 py-0.5 rounded">extraction.default_engine</code> setting in your configuration file.
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <div>
                <label htmlFor="default-extraction-engine" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Extraction Engine
                </label>
                <select
                  id="default-extraction-engine"
                  value={defaultEngine}
                  onChange={(e) => setDefaultEngine(e.target.value)}
                  disabled={isEngineFromConfig || availableEngines.length === 0}
                  className={`w-full max-w-lg px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white ${
                    isEngineFromConfig || availableEngines.length === 0 ? 'opacity-50 cursor-not-allowed' : ''
                  }`}
                >
                  {availableEngines.length === 0 && (
                    <option value="">Loading engines...</option>
                  )}
                  {availableEngines.map((engine) => (
                    <option key={engine.id} value={engine.name}>
                      {engine.display_name}
                    </option>
                  ))}
                </select>
                {defaultEngine && availableEngines.length > 0 && (
                  <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                    {availableEngines.find((e) => e.name === defaultEngine)?.description}
                  </p>
                )}
                {availableEngines.length === 0 && !isLoading && (
                  <p className="mt-2 text-sm text-amber-600 dark:text-amber-400">
                    No extraction engines available. Check your config.yml file.
                  </p>
                )}
              </div>

              {!isEngineFromConfig && (
                <div className="flex gap-3 pt-4">
                  <Button onClick={handleSaveExtractionEngine} disabled={isSaving}>
                    {isSaving ? 'Saving...' : 'Save Extraction Engine'}
                  </Button>
                  <Button variant="secondary" onClick={loadSettings}>
                    Reset
                  </Button>
                </div>
              )}
            </div>

            <div className="space-y-4">
              {Object.entries(editedOrgSettings).filter(([key]) => key !== 'default_extraction_engine').map(([key, value]) => (
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

            {activeTab === 'infrastructure' && (
              <InfrastructureHealthPanel />
            )}

            {activeTab === 'users' && (
              <div className="space-y-6">
                <div>
                  <div className="flex justify-between items-center mb-4">
                    <div>
                      <h2 className="text-lg font-semibold text-gray-900 dark:text-white">User Management</h2>
                      <p className="text-sm text-gray-600 dark:text-gray-400 mt-0.5">
                        Invite users, manage roles, and control access
                      </p>
                    </div>
                    <Button onClick={() => setShowInviteForm(true)} className="inline-flex items-center">
                      <UserPlus className="w-4 h-4 mr-2" />
                      Invite User
                    </Button>
                  </div>
                </div>

                {showInviteForm && (
                  <div className="mb-6">
                    <UserInviteForm
                      onSuccess={handleInviteSuccess}
                      onCancel={() => setShowInviteForm(false)}
                    />
                  </div>
                )}

                {editingUser && (
                  <div className="mb-6">
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
                      {users.map((userItem) => (
                        <tr key={userItem.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div className="flex items-center">
                              <div>
                                <div className="text-sm font-medium text-gray-900 dark:text-white">
                                  {userItem.full_name || userItem.username}
                                  {userItem.id === user?.id && (
                                    <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">(You)</span>
                                  )}
                                </div>
                                <div className="text-sm text-gray-500 dark:text-gray-400">
                                  {userItem.email}
                                </div>
                                <div className="text-xs text-gray-400 dark:text-gray-500">
                                  @{userItem.username}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <Badge variant={getRoleBadgeVariant(userItem.role)}>
                              {userItem.role}
                            </Badge>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <Badge variant={userItem.is_active ? 'success' : 'secondary'}>
                              {userItem.is_active ? 'Active' : 'Inactive'}
                            </Badge>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                            {userItem.last_login ? new Date(userItem.last_login).toLocaleDateString() : 'Never'}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                            <div className="flex justify-end gap-2">
                              <Button
                                variant="secondary"
                                size="sm"
                                onClick={() => setEditingUser(userItem)}
                              >
                                Edit
                              </Button>
                              {userItem.id !== user?.id && (
                                <>
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    onClick={() => handleToggleActive(userItem.id, userItem.is_active)}
                                  >
                                    {userItem.is_active ? 'Deactivate' : 'Activate'}
                                  </Button>
                                  <Button
                                    variant="destructive"
                                    size="sm"
                                    onClick={() => handleDeleteUser(userItem.id)}
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
            )}

            {activeTab === 'maintenance' && (
              <SystemMaintenanceTab onError={(msg) => setError(msg)} />
            )}
          </div>

          {/* Merged Settings Preview */}
          <div className="mt-6">
            <button
              onClick={() => setShowMergedPreview(!showMergedPreview)}
              className="inline-flex items-center text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              {showMergedPreview ? (
                <>
                  <ChevronUp className="w-4 h-4 mr-1" />
                  Hide Merged Settings Preview
                </>
              ) : (
                <>
                  <ChevronDown className="w-4 h-4 mr-1" />
                  Show Merged Settings Preview
                </>
              )}
            </button>

            {showMergedPreview && (
              <div className="mt-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg p-4 border border-gray-200 dark:border-gray-700">
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
      </div>
    </div>
  )
}

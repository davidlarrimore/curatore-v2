'use client'

import { useState, useEffect, FormEvent } from 'react'
import { useAuth } from '@/lib/auth-context'
import { connectionsApi } from '@/lib/api'
import { Button } from '../ui/Button'
import { FolderSync, FileText, Check, ChevronRight, AlertTriangle, Loader2, X, Link2 } from 'lucide-react'

interface Connection {
  id: string
  name: string
  connection_type: string
  config: Record<string, any>
  is_default: boolean
  is_active: boolean
  is_managed?: boolean
  managed_by?: string
}

interface ConnectionType {
  type: string
  display_name: string
  description: string
  config_schema: any
  example_config: Record<string, any>
}

interface ConnectionFormProps {
  connection?: Connection | null
  onSuccess: () => void
  onCancel: () => void
}

type Step = 'select-type' | 'configure' | 'review'

export default function ConnectionForm({ connection, onSuccess, onCancel }: ConnectionFormProps) {
  const { token } = useAuth()
  const [currentStep, setCurrentStep] = useState<Step>(connection ? 'configure' : 'select-type')
  const [connectionTypes, setConnectionTypes] = useState<ConnectionType[]>([])
  const [selectedType, setSelectedType] = useState(connection?.connection_type || '')
  const [name, setName] = useState(connection?.name || '')
  const [config, setConfig] = useState<Record<string, any>>(connection?.config || {})
  const [isDefault, setIsDefault] = useState(connection?.is_default || false)
  const [testOnSave, setTestOnSave] = useState(true)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const loadConnectionTypes = async () => {
      try {
        const response = await connectionsApi.listConnectionTypes(token || undefined)
        setConnectionTypes(response.types)

        // If editing, load the existing config
        if (connection) {
          setSelectedType(connection.connection_type)
          setConfig(connection.config)
        } else if (response.types.length > 0 && !selectedType) {
          // Default to first type if creating new
          setSelectedType(response.types[0].type)
          setConfig(response.types[0].example_config || {})
        }
      } catch (err: any) {
        setError(err.message || 'Failed to load connection types')
      }
    }

    loadConnectionTypes()
  }, [connection, token])

  const selectedTypeInfo = connectionTypes.find(t => t.type === selectedType)

  const handleTypeChange = (newType: string) => {
    setSelectedType(newType)
    const typeInfo = connectionTypes.find(t => t.type === newType)
    if (typeInfo) {
      setConfig(typeInfo.example_config || {})
    }
  }

  const handleTypeSelect = (type: string) => {
    handleTypeChange(type)
    setCurrentStep('configure')
  }

  const handleConfigChange = (key: string, value: any) => {
    setConfig(prev => ({ ...prev, [key]: value }))
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      const data = {
        name,
        connection_type: selectedType,
        config,
        is_default: isDefault,
        test_on_save: testOnSave,
      }

      if (connection) {
        await connectionsApi.updateConnection(token, connection.id, data)
      } else {
        await connectionsApi.createConnection(token, data)
      }

      onSuccess()
    } catch (err: any) {
      setError(err.message || `Failed to ${connection ? 'update' : 'create'} connection`)
    } finally {
      setIsLoading(false)
    }
  }

  const getConnectionTypeIcon = (type: string) => {
    switch (type) {
      case 'microsoft_graph':
        return <FolderSync className="w-6 h-6" />
      case 'extraction':
        return <FileText className="w-6 h-6" />
      default:
        return <Link2 className="w-6 h-6" />
    }
  }

  const getTypeGradient = (type: string) => {
    switch (type) {
      case 'microsoft_graph':
        return 'from-blue-500 to-cyan-500'
      case 'extraction':
        return 'from-emerald-500 to-teal-500'
      default:
        return 'from-gray-500 to-gray-600'
    }
  }

  const renderConfigField = (key: string, schema: any) => {
    const value = config[key] || ''
    const fieldType = schema.type === 'string' ? 'text' : schema.type === 'integer' || schema.type === 'number' ? 'number' : 'text'
    const isSecret = key.toLowerCase().includes('secret') || key.toLowerCase().includes('password') || key.toLowerCase().includes('key')
    const isDoclingOcrField = key === 'docling_ocr_enabled'
    const isDoclingSelected = config.engine_type === 'docling'

    if (schema.type === 'boolean') {
      const checked = typeof config[key] === 'boolean' ? config[key] : Boolean(schema.default)
      const isDisabled = isDoclingOcrField && !isDoclingSelected

      return (
        <div key={key} className="space-y-1.5">
          <div className="flex items-center gap-2">
            <input
              id={key}
              type="checkbox"
              checked={checked}
              disabled={isDisabled}
              onChange={(e) => handleConfigChange(key, e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-60"
            />
            <label htmlFor={key} className="text-sm font-medium text-gray-700 dark:text-gray-300">
              {schema.title || key}
            </label>
          </div>
          {schema.description && (
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {schema.description}
              {isDoclingOcrField && !isDoclingSelected ? ' (Docling only)' : ''}
            </p>
          )}
        </div>
      )
    }

    return (
      <div key={key} className="space-y-1.5">
        <label htmlFor={key} className="block text-sm font-medium text-gray-700 dark:text-gray-300">
          {schema.title || key}
        </label>
        {schema.description && (
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {schema.description}
          </p>
        )}
        <input
          id={key}
          type={isSecret ? 'password' : fieldType}
          value={value}
          onChange={(e) => handleConfigChange(key, e.target.value)}
          placeholder={schema.default != null ? String(schema.default) : ''}
          className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 transition-all"
          required={schema.required}
        />
      </div>
    )
  }

  const renderStepIndicator = () => {
    const steps = [
      { id: 'select-type', label: 'Type' },
      { id: 'configure', label: 'Configure' },
      { id: 'review', label: 'Review' }
    ]

    if (connection) return null

    const currentStepIndex = steps.findIndex(s => s.id === currentStep)

    return (
      <div className="mb-8">
        <div className="flex items-center justify-center">
          {steps.map((step, index) => (
            <div key={step.id} className="flex items-center">
              <div className="flex flex-col items-center">
                <div
                  className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-medium transition-all ${
                    index < currentStepIndex
                      ? 'bg-indigo-600 text-white'
                      : index === currentStepIndex
                      ? 'bg-indigo-600 text-white ring-4 ring-indigo-100 dark:ring-indigo-900/50'
                      : 'bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-500'
                  }`}
                >
                  {index < currentStepIndex ? (
                    <Check className="w-4 h-4" />
                  ) : (
                    index + 1
                  )}
                </div>
                <span className={`mt-2 text-xs font-medium ${
                  index <= currentStepIndex
                    ? 'text-indigo-600 dark:text-indigo-400'
                    : 'text-gray-400 dark:text-gray-500'
                }`}>
                  {step.label}
                </span>
              </div>
              {index < steps.length - 1 && (
                <div className={`w-12 sm:w-16 h-0.5 mx-2 transition-all ${
                  index < currentStepIndex
                    ? 'bg-indigo-600'
                    : 'bg-gray-200 dark:bg-gray-700'
                }`} />
              )}
            </div>
          ))}
        </div>
      </div>
    )
  }

  const renderSelectType = () => {
    return (
      <div className="space-y-6">
        <div className="text-center mb-8">
          <h3 className="text-xl font-semibold text-gray-900 dark:text-white">
            Choose Connection Type
          </h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Select the type of service you want to connect
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {connectionTypes.map((type) => (
            <button
              key={type.type}
              type="button"
              onClick={() => handleTypeSelect(type.type)}
              className="group relative p-5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-lg transition-all duration-200 text-left"
            >
              <div className="flex flex-col items-center text-center space-y-3">
                <div className={`p-3 rounded-xl bg-gradient-to-br ${getTypeGradient(type.type)} text-white group-hover:scale-110 transition-transform shadow-lg`}>
                  {getConnectionTypeIcon(type.type)}
                </div>
                <div>
                  <h4 className="text-base font-semibold text-gray-900 dark:text-white group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors">
                    {type.display_name}
                  </h4>
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
                    {type.description}
                  </p>
                </div>
              </div>
              <ChevronRight className="absolute top-1/2 right-3 -translate-y-1/2 w-5 h-5 text-gray-300 dark:text-gray-600 group-hover:text-indigo-500 group-hover:translate-x-1 transition-all" />
            </button>
          ))}
        </div>
      </div>
    )
  }

  const renderConfigure = () => {
    if (!selectedTypeInfo || !selectedTypeInfo.config_schema) {
      return <p className="text-sm text-gray-500 dark:text-gray-400">No configuration schema available</p>
    }

    const schema = selectedTypeInfo.config_schema
    const properties = schema.properties || {}

    return (
      <div className="space-y-6">
        <div className="text-center mb-6">
          <div className={`inline-flex items-center justify-center p-3 rounded-xl bg-gradient-to-br ${getTypeGradient(selectedType)} text-white mb-4 shadow-lg`}>
            {getConnectionTypeIcon(selectedType)}
          </div>
          <h3 className="text-xl font-semibold text-gray-900 dark:text-white">
            Configure {selectedTypeInfo.display_name}
          </h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            {selectedTypeInfo.description}
          </p>
        </div>

        <div className="bg-gray-50 dark:bg-gray-900/50 rounded-xl p-5 border border-gray-100 dark:border-gray-800 space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="connection-name" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              Connection Name
            </label>
            <input
              id="connection-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Production Microsoft Graph"
              required
              className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 transition-all"
            />
          </div>

          <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
            <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-4">Connection Settings</h4>
            <div className="space-y-4">
              {Object.entries(properties).map(([key, fieldSchema]: [string, any]) =>
                renderConfigField(key, fieldSchema)
              )}
            </div>
          </div>
        </div>
      </div>
    )
  }

  const renderReview = () => {
    if (!selectedTypeInfo) return null

    return (
      <div className="space-y-6">
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center p-3 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-500 text-white mb-4 shadow-lg">
            <Check className="w-6 h-6" />
          </div>
          <h3 className="text-xl font-semibold text-gray-900 dark:text-white">
            Review Connection
          </h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Verify your connection details before saving
          </p>
        </div>

        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
          <div className={`bg-gradient-to-r ${getTypeGradient(selectedType)} px-5 py-4`}>
            <div className="flex items-center gap-3">
              <div className="p-2 bg-white/20 rounded-lg">
                {getConnectionTypeIcon(selectedType)}
              </div>
              <div className="text-white">
                <h4 className="font-semibold">{name}</h4>
                <p className="text-sm text-white/80">
                  {selectedTypeInfo.display_name}
                </p>
              </div>
            </div>
          </div>

          <div className="p-5 space-y-3">
            {Object.entries(config).map(([key, value]) => {
              const isSecret = key.toLowerCase().includes('secret') || key.toLowerCase().includes('password') || key.toLowerCase().includes('key')

              return (
                <div key={key} className="flex items-center justify-between py-2 border-b border-gray-100 dark:border-gray-700 last:border-0">
                  <span className="text-sm text-gray-500 dark:text-gray-400 capitalize">
                    {key.replace(/_/g, ' ')}
                  </span>
                  <span className="text-sm text-gray-900 dark:text-white font-mono bg-gray-50 dark:bg-gray-900 px-2.5 py-1 rounded-md max-w-[200px] truncate">
                    {isSecret ? '••••••••' : String(value) || 'Not set'}
                  </span>
                </div>
              )
            })}
          </div>
        </div>

        {/* Toggle options */}
        <div className="space-y-3">
          <label className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-700 rounded-xl cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
            <div>
              <p className="text-sm font-medium text-gray-900 dark:text-white">
                Set as default connection
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                Use this connection by default for {selectedTypeInfo.display_name}
              </p>
            </div>
            <div className="relative">
              <input
                type="checkbox"
                checked={isDefault}
                onChange={(e) => setIsDefault(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-indigo-300 dark:peer-focus:ring-indigo-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-indigo-600"></div>
            </div>
          </label>

          {!connection && (
            <label className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-700 rounded-xl cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
              <div>
                <p className="text-sm font-medium text-gray-900 dark:text-white">
                  Test connection before saving
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  Verify that the connection works before creating it
                </p>
              </div>
              <div className="relative">
                <input
                  type="checkbox"
                  checked={testOnSave}
                  onChange={(e) => setTestOnSave(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-indigo-300 dark:peer-focus:ring-indigo-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-indigo-600"></div>
              </div>
            </label>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl shadow-xl overflow-hidden">
      {/* Header */}
      <div className="relative bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-600 px-6 py-5">
        <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iNjAiIHZpZXdCb3g9IjAgMCA2MCA2MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxwYXRoIGQ9Ik0zNiAxOGMtNi42MjcgMC0xMiA1LjM3My0xMiAxMnM1LjM3MyAxMiAxMiAxMiAxMi01LjM3MyAxMi0xMi01LjM3My0xMi0xMi0xMnptMCAxOGMtMy4zMTQgMC02LTIuNjg2LTYtNnMyLjY4Ni02IDYtNiA2IDIuNjg2IDYgNi0yLjY4NiA2LTYgNnoiIGZpbGw9IiNmZmYiIGZpbGwtb3BhY2l0eT0iLjA1Ii8+PC9nPjwvc3ZnPg==')] opacity-30"></div>
        <div className="relative flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-white">
              {connection ? 'Edit Connection' : 'New Connection'}
            </h2>
            <p className="text-indigo-100 text-sm mt-0.5">
              {connection ? 'Update your connection settings' : 'Set up a new service connection'}
            </p>
          </div>
          <button
            onClick={onCancel}
            className="p-2 text-white/80 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      </div>

      <div className="p-6">
        {/* Error */}
        {error && (
          <div className="mb-6 flex items-center gap-3 p-4 bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 rounded-xl">
            <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0" />
            <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
          </div>
        )}

        {/* Managed warning */}
        {connection?.is_managed && (
          <div className="mb-6 flex items-start gap-3 p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-100 dark:border-amber-900/50 rounded-xl">
            <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
                Managed Connection
              </p>
              <p className="mt-1 text-sm text-amber-700 dark:text-amber-300">
                This connection is managed by environment variables and cannot be edited through the UI.
                {connection.managed_by && (
                  <span className="block mt-1 text-xs opacity-80">{connection.managed_by}</span>
                )}
              </p>
            </div>
          </div>
        )}

        {renderStepIndicator()}

        <form onSubmit={handleSubmit}>
          {currentStep === 'select-type' && renderSelectType()}
          {currentStep === 'configure' && renderConfigure()}
          {currentStep === 'review' && renderReview()}

          {/* Footer */}
          <div className="flex items-center justify-between pt-6 mt-6 border-t border-gray-200 dark:border-gray-700">
            <div>
              {currentStep === 'configure' && !connection && (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setCurrentStep('select-type')}
                  className="gap-1"
                >
                  <ChevronRight className="w-4 h-4 rotate-180" />
                  Back
                </Button>
              )}
              {currentStep === 'review' && (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setCurrentStep('configure')}
                  className="gap-1"
                >
                  <ChevronRight className="w-4 h-4 rotate-180" />
                  Back
                </Button>
              )}
            </div>

            <div className="flex gap-3">
              <Button type="button" variant="secondary" onClick={onCancel}>
                Cancel
              </Button>
              {currentStep === 'configure' && (
                <Button
                  type="button"
                  onClick={() => setCurrentStep('review')}
                  disabled={!name || !selectedType}
                  className="gap-1"
                >
                  Continue
                  <ChevronRight className="w-4 h-4" />
                </Button>
              )}
              {currentStep === 'review' && (
                <Button type="submit" disabled={isLoading} className="gap-2">
                  {isLoading ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Saving...
                    </>
                  ) : (
                    <>
                      <Check className="w-4 h-4" />
                      {connection ? 'Update Connection' : 'Create Connection'}
                    </>
                  )}
                </Button>
              )}
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}

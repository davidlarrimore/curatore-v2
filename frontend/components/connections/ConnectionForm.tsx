'use client'

import { useState, useEffect, FormEvent } from 'react'
import { useAuth } from '@/lib/auth-context'
import { connectionsApi } from '@/lib/api'
import { Button } from '../ui/Button'

interface Connection {
  id: string
  name: string
  connection_type: string
  config: Record<string, any>
  is_default: boolean
  is_active: boolean
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

export default function ConnectionForm({ connection, onSuccess, onCancel }: ConnectionFormProps) {
  const { token } = useAuth()
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

  const renderConfigField = (key: string, schema: any) => {
    const value = config[key] || ''
    const fieldType = schema.type === 'string' ? 'text' : schema.type === 'integer' || schema.type === 'number' ? 'number' : 'text'
    const isSecret = key.toLowerCase().includes('secret') || key.toLowerCase().includes('password') || key.toLowerCase().includes('key')

    return (
      <div key={key}>
        <label htmlFor={key} className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          {schema.title || key}
          {schema.description && (
            <span className="block text-xs text-gray-500 dark:text-gray-400 font-normal">
              {schema.description}
            </span>
          )}
        </label>
        <input
          id={key}
          type={isSecret ? 'password' : fieldType}
          value={value}
          onChange={(e) => handleConfigChange(key, e.target.value)}
          placeholder={schema.default || ''}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
          required={schema.required}
        />
      </div>
    )
  }

  const renderConfigForm = () => {
    if (!selectedTypeInfo || !selectedTypeInfo.config_schema) {
      return <p className="text-sm text-gray-600 dark:text-gray-400">No configuration schema available</p>
    }

    const schema = selectedTypeInfo.config_schema
    const properties = schema.properties || {}

    return (
      <div className="space-y-4">
        {Object.entries(properties).map(([key, fieldSchema]: [string, any]) =>
          renderConfigField(key, fieldSchema)
        )}
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
      <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
        {connection ? 'Edit Connection' : 'New Connection'}
      </h2>

      {error && (
        <div className="mb-4 rounded-md bg-red-50 dark:bg-red-900/20 p-4">
          <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <div>
          <label htmlFor="connection-type" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Connection Type
          </label>
          <select
            id="connection-type"
            value={selectedType}
            onChange={(e) => handleTypeChange(e.target.value)}
            disabled={!!connection}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white disabled:opacity-50"
          >
            {connectionTypes.map(type => (
              <option key={type.type} value={type.type}>
                {type.display_name}
              </option>
            ))}
          </select>
          {selectedTypeInfo && (
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              {selectedTypeInfo.description}
            </p>
          )}
        </div>

        <div>
          <label htmlFor="connection-name" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Connection Name
          </label>
          <input
            id="connection-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g., Primary OpenAI LLM"
            required
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
          />
        </div>

        <div>
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Configuration</h3>
          {renderConfigForm()}
        </div>

        <div className="space-y-3">
          <label className="flex items-center">
            <input
              type="checkbox"
              checked={isDefault}
              onChange={(e) => setIsDefault(e.target.checked)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="ml-2 text-sm text-gray-700 dark:text-gray-300">
              Set as default connection for this type
            </span>
          </label>

          {!connection && (
            <label className="flex items-center">
              <input
                type="checkbox"
                checked={testOnSave}
                onChange={(e) => setTestOnSave(e.target.checked)}
                className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="ml-2 text-sm text-gray-700 dark:text-gray-300">
                Test connection before saving
              </span>
            </label>
          )}
        </div>

        <div className="flex gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
          <Button type="submit" disabled={isLoading}>
            {isLoading ? 'Saving...' : connection ? 'Update Connection' : 'Create Connection'}
          </Button>
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </div>
  )
}

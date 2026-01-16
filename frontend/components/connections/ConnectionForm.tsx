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

type Step = 'select-type' | 'select-provider' | 'configure' | 'review'

interface LLMProvider {
  id: string
  name: string
  baseUrl: string
  requiresIAM?: boolean
  description: string
}

const LLM_PROVIDERS: LLMProvider[] = [
  {
    id: 'openai',
    name: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
    description: 'GPT-4, GPT-3.5, and other OpenAI models'
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    baseUrl: 'https://api.anthropic.com/v1',
    description: 'Claude 3 Opus, Sonnet, and Haiku models'
  },
  {
    id: 'google',
    name: 'Google Gemini',
    baseUrl: 'https://generativelanguage.googleapis.com/v1',
    description: 'Gemini Pro and Ultra models'
  },
  {
    id: 'bedrock',
    name: 'AWS Bedrock',
    baseUrl: 'https://bedrock-runtime.us-east-1.amazonaws.com',
    requiresIAM: true,
    description: 'AWS Bedrock foundation models'
  },
  {
    id: 'custom',
    name: 'Custom / OpenAI-Compatible',
    baseUrl: '',
    description: 'Ollama, LM Studio, or other compatible APIs'
  }
]

export default function ConnectionForm({ connection, onSuccess, onCancel }: ConnectionFormProps) {
  const { token } = useAuth()
  const [currentStep, setCurrentStep] = useState<Step>(connection ? 'configure' : 'select-type')
  const [connectionTypes, setConnectionTypes] = useState<ConnectionType[]>([])
  const [selectedType, setSelectedType] = useState(connection?.connection_type || '')
  const [selectedProvider, setSelectedProvider] = useState<LLMProvider | null>(null)
  const [name, setName] = useState(connection?.name || '')
  const [config, setConfig] = useState<Record<string, any>>(connection?.config || {})
  const [isDefault, setIsDefault] = useState(connection?.is_default || false)
  const [testOnSave, setTestOnSave] = useState(true)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')

  // LLM-specific state
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [isFetchingModels, setIsFetchingModels] = useState(false)
  const [modelsFetched, setModelsFetched] = useState(false)
  const [requiresManualModel, setRequiresManualModel] = useState(false)

  useEffect(() => {
    const loadConnectionTypes = async () => {
      try {
        const response = await connectionsApi.listConnectionTypes(token || undefined)
        setConnectionTypes(response.types)

        // If editing, load the existing config
        if (connection) {
          setSelectedType(connection.connection_type)
          setConfig(connection.config)

          // Try to determine provider from base_url if it's an LLM connection
          if (connection.connection_type === 'llm' && connection.config.base_url) {
            const matchedProvider = LLM_PROVIDERS.find(p =>
              connection.config.base_url.includes(p.id) ||
              connection.config.base_url === p.baseUrl
            )
            if (matchedProvider) {
              setSelectedProvider(matchedProvider)
            }
          }
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

    // If LLM type selected, go to provider selection
    if (type === 'llm') {
      setCurrentStep('select-provider')
    } else {
      setCurrentStep('configure')
    }
  }

  const handleProviderSelect = (provider: LLMProvider) => {
    setSelectedProvider(provider)

    // Pre-populate config with provider defaults
    setConfig({
      ...config,
      base_url: provider.baseUrl,
      provider: provider.id
    })

    setRequiresManualModel(provider.requiresIAM || false)
    setCurrentStep('configure')
  }

  const handleConfigChange = (key: string, value: any) => {
    setConfig(prev => ({ ...prev, [key]: value }))
  }

  const handleTestCredentials = async () => {
    if (!token || !config.api_key || !config.base_url) {
      setError('API key and base URL are required to test connection')
      return
    }

    setIsFetchingModels(true)
    setError('')

    try {
      const result = await connectionsApi.testCredentials(token, {
        provider: selectedProvider?.id || 'openai',
        base_url: config.base_url,
        api_key: config.api_key,
        ...config
      })

      if (result.success) {
        setAvailableModels(result.models)
        setModelsFetched(true)

        // Auto-select first model if none selected
        if (result.models.length > 0 && !config.model) {
          handleConfigChange('model', result.models[0])
        }
      } else {
        setError(result.error || 'Failed to fetch models')

        if (result.requires_manual_model) {
          setRequiresManualModel(true)
          setModelsFetched(true)
        }
      }
    } catch (err: any) {
      setError(err.message || 'Failed to test connection')
    } finally {
      setIsFetchingModels(false)
    }
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
      case 'llm':
        return (
          <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
        )
      case 'sharepoint':
        return (
          <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
          </svg>
        )
      case 'extraction':
        return (
          <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        )
      default:
        return (
          <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        )
    }
  }

  const getProviderIcon = (providerId: string) => {
    // You can add provider-specific icons here
    return getConnectionTypeIcon('llm')
  }

  const renderConfigField = (key: string, schema: any) => {
    const value = config[key] || ''
    const fieldType = schema.type === 'string' ? 'text' : schema.type === 'integer' || schema.type === 'number' ? 'number' : 'text'
    const isSecret = key.toLowerCase().includes('secret') || key.toLowerCase().includes('password') || key.toLowerCase().includes('key')

    return (
      <div key={key} className="space-y-2">
        <label htmlFor={key} className="block text-sm font-medium text-gray-900 dark:text-gray-100">
          {schema.title || key}
          {schema.description && (
            <span className="block text-xs text-gray-500 dark:text-gray-400 font-normal mt-1">
              {schema.description}
            </span>
          )}
        </label>
        <input
          id={key}
          type={isSecret ? 'password' : fieldType}
          value={value}
          onChange={(e) => handleConfigChange(key, e.target.value)}
          placeholder={schema.default != null ? String(schema.default) : ''}
          className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white transition-all"
          required={schema.required}
        />
      </div>
    )
  }

  const renderStepIndicator = () => {
    const steps = selectedType === 'llm' && !connection ? [
      { id: 'select-type', label: 'Type', number: 1 },
      { id: 'select-provider', label: 'Provider', number: 2 },
      { id: 'configure', label: 'Configure', number: 3 },
      { id: 'review', label: 'Review', number: 4 }
    ] : [
      { id: 'select-type', label: 'Select Type', number: 1 },
      { id: 'configure', label: 'Configure', number: 2 },
      { id: 'review', label: 'Review', number: 3 }
    ]

    if (connection) {
      // When editing, skip step 1
      return null
    }

    const currentStepIndex = steps.findIndex(s => s.id === currentStep)

    return (
      <div className="mb-8">
        <div className="flex items-center justify-center">
          {steps.map((step, index) => (
            <div key={step.id} className="flex items-center">
              <div className="flex flex-col items-center">
                <div
                  className={`w-10 h-10 rounded-full flex items-center justify-center font-semibold transition-all ${
                    index <= currentStepIndex
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400'
                  }`}
                >
                  {index < currentStepIndex ? (
                    <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  ) : (
                    step.number
                  )}
                </div>
                <span className={`mt-2 text-xs font-medium ${
                  index <= currentStepIndex
                    ? 'text-blue-600 dark:text-blue-400'
                    : 'text-gray-500 dark:text-gray-400'
                }`}>
                  {step.label}
                </span>
              </div>
              {index < steps.length - 1 && (
                <div className={`w-16 h-0.5 mx-2 transition-all ${
                  index < currentStepIndex
                    ? 'bg-blue-600'
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
        <div className="text-center">
          <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
            Choose Connection Type
          </h3>
          <p className="text-gray-600 dark:text-gray-400">
            Select the type of service you want to connect
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-8">
          {connectionTypes.map((type) => (
            <button
              key={type.type}
              type="button"
              onClick={() => handleTypeSelect(type.type)}
              className="group relative p-6 bg-white dark:bg-gray-800 border-2 border-gray-200 dark:border-gray-700 rounded-xl hover:border-blue-500 hover:shadow-lg transition-all duration-200 text-left"
            >
              <div className="flex flex-col items-center text-center space-y-3">
                <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg text-blue-600 dark:text-blue-400 group-hover:scale-110 transition-transform">
                  {getConnectionTypeIcon(type.type)}
                </div>
                <div>
                  <h4 className="text-lg font-semibold text-gray-900 dark:text-white group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                    {type.display_name}
                  </h4>
                  <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                    {type.description}
                  </p>
                </div>
              </div>
              <div className="absolute top-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity">
                <svg className="w-5 h-5 text-blue-600 dark:text-blue-400" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clipRule="evenodd" />
                </svg>
              </div>
            </button>
          ))}
        </div>
      </div>
    )
  }

  const renderSelectProvider = () => {
    return (
      <div className="space-y-6">
        <div className="text-center">
          <div className="inline-flex items-center justify-center p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg text-blue-600 dark:text-blue-400 mb-4">
            {getConnectionTypeIcon('llm')}
          </div>
          <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
            Choose LLM Provider
          </h3>
          <p className="text-gray-600 dark:text-gray-400">
            Select your AI model provider
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-8">
          {LLM_PROVIDERS.map((provider) => (
            <button
              key={provider.id}
              type="button"
              onClick={() => handleProviderSelect(provider)}
              className="group relative p-6 bg-white dark:bg-gray-800 border-2 border-gray-200 dark:border-gray-700 rounded-xl hover:border-blue-500 hover:shadow-lg transition-all duration-200 text-left"
            >
              <div className="flex items-start space-x-4">
                <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg text-blue-600 dark:text-blue-400 group-hover:scale-110 transition-transform flex-shrink-0">
                  {getProviderIcon(provider.id)}
                </div>
                <div className="flex-1">
                  <h4 className="text-lg font-semibold text-gray-900 dark:text-white group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                    {provider.name}
                  </h4>
                  <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                    {provider.description}
                  </p>
                  {provider.requiresIAM && (
                    <span className="inline-block mt-2 px-2 py-1 text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-200 rounded">
                      Requires IAM Credentials
                    </span>
                  )}
                </div>
              </div>
              <div className="absolute top-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity">
                <svg className="w-5 h-5 text-blue-600 dark:text-blue-400" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clipRule="evenodd" />
                </svg>
              </div>
            </button>
          ))}
        </div>
      </div>
    )
  }

  const renderLLMConfig = () => {
    return (
      <div className="space-y-6">
        <div className="bg-gray-50 dark:bg-gray-900/50 rounded-xl p-6 space-y-5">
          {/* Provider badge */}
          {selectedProvider && (
            <div className="flex items-center space-x-2 pb-4 border-b border-gray-200 dark:border-gray-700">
              <span className="text-sm font-medium text-gray-600 dark:text-gray-400">Provider:</span>
              <span className="px-3 py-1 bg-blue-100 dark:bg-blue-900/20 text-blue-800 dark:text-blue-200 rounded-full text-sm font-medium">
                {selectedProvider.name}
              </span>
            </div>
          )}

          {/* Connection Name */}
          <div className="space-y-2">
            <label htmlFor="connection-name" className="block text-sm font-medium text-gray-900 dark:text-gray-100">
              Connection Name
            </label>
            <input
              id="connection-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={`e.g., ${selectedProvider?.name || 'My'} LLM`}
              required
              className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white transition-all"
            />
          </div>

          {/* Base URL */}
          <div className="space-y-2">
            <label htmlFor="base_url" className="block text-sm font-medium text-gray-900 dark:text-gray-100">
              Base URL
            </label>
            <input
              id="base_url"
              type="text"
              value={config.base_url || ''}
              onChange={(e) => handleConfigChange('base_url', e.target.value)}
              placeholder="https://api.openai.com/v1"
              required
              className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white transition-all"
            />
          </div>

          {/* API Key or IAM Credentials */}
          {selectedProvider?.requiresIAM ? (
            <>
              <div className="space-y-2">
                <label htmlFor="access_key" className="block text-sm font-medium text-gray-900 dark:text-gray-100">
                  AWS Access Key ID
                </label>
                <input
                  id="access_key"
                  type="password"
                  value={config.access_key || ''}
                  onChange={(e) => handleConfigChange('access_key', e.target.value)}
                  placeholder="AKIAIOSFODNN7EXAMPLE"
                  required
                  className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white transition-all"
                />
              </div>
              <div className="space-y-2">
                <label htmlFor="secret_key" className="block text-sm font-medium text-gray-900 dark:text-gray-100">
                  AWS Secret Access Key
                </label>
                <input
                  id="secret_key"
                  type="password"
                  value={config.secret_key || ''}
                  onChange={(e) => handleConfigChange('secret_key', e.target.value)}
                  placeholder="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
                  required
                  className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white transition-all"
                />
              </div>
              <div className="space-y-2">
                <label htmlFor="region" className="block text-sm font-medium text-gray-900 dark:text-gray-100">
                  AWS Region
                </label>
                <input
                  id="region"
                  type="text"
                  value={config.region || 'us-east-1'}
                  onChange={(e) => handleConfigChange('region', e.target.value)}
                  placeholder="us-east-1"
                  required
                  className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white transition-all"
                />
              </div>
            </>
          ) : (
            <div className="space-y-2">
              <label htmlFor="api_key" className="block text-sm font-medium text-gray-900 dark:text-gray-100">
                API Key
              </label>
              <input
                id="api_key"
                type="password"
                value={config.api_key || ''}
                onChange={(e) => handleConfigChange('api_key', e.target.value)}
                placeholder="sk-..."
                required
                className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white transition-all"
              />
            </div>
          )}

          {/* Test Connection and Fetch Models */}
          {!modelsFetched && !selectedProvider?.requiresIAM && (
            <div className="pt-4">
              <Button
                type="button"
                onClick={handleTestCredentials}
                disabled={isFetchingModels || !config.api_key || !config.base_url}
                variant="secondary"
                className="w-full"
              >
                {isFetchingModels ? (
                  <span className="flex items-center justify-center">
                    <svg className="animate-spin -ml-1 mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Testing Connection...
                  </span>
                ) : (
                  'Test Connection & Fetch Models'
                )}
              </Button>
            </div>
          )}

          {/* Model Selection */}
          {(modelsFetched || availableModels.length > 0) && (
            <div className="space-y-2 pt-4 border-t border-gray-200 dark:border-gray-700">
              <label htmlFor="model" className="block text-sm font-medium text-gray-900 dark:text-gray-100">
                Model
                {availableModels.length > 0 && (
                  <span className="ml-2 text-xs text-green-600 dark:text-green-400">
                    ✓ {availableModels.length} models available
                  </span>
                )}
              </label>
              {availableModels.length > 0 ? (
                <select
                  id="model"
                  value={config.model || ''}
                  onChange={(e) => handleConfigChange('model', e.target.value)}
                  required
                  className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white transition-all"
                >
                  <option value="">Select a model</option>
                  {availableModels.map(model => (
                    <option key={model} value={model}>{model}</option>
                  ))}
                </select>
              ) : requiresManualModel ? (
                <input
                  id="model"
                  type="text"
                  value={config.model || ''}
                  onChange={(e) => handleConfigChange('model', e.target.value)}
                  placeholder="e.g., anthropic.claude-3-sonnet-20240229-v1:0"
                  required
                  className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white transition-all"
                />
              ) : null}
            </div>
          )}

          {modelsFetched && availableModels.length > 0 && (
            <button
              type="button"
              onClick={() => {
                setModelsFetched(false)
                setAvailableModels([])
              }}
              className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
            >
              Re-test connection
            </button>
          )}
        </div>
      </div>
    )
  }

  const renderConfigure = () => {
    if (!selectedTypeInfo || !selectedTypeInfo.config_schema) {
      return <p className="text-sm text-gray-600 dark:text-gray-400">No configuration schema available</p>
    }

    // Special handling for LLM connections
    if (selectedType === 'llm') {
      return (
        <div className="space-y-6">
          <div className="text-center">
            <div className="inline-flex items-center justify-center p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg text-blue-600 dark:text-blue-400 mb-4">
              {getConnectionTypeIcon(selectedType)}
            </div>
            <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
              Configure {selectedProvider?.name || 'LLM'} Connection
            </h3>
            <p className="text-gray-600 dark:text-gray-400">
              {selectedProvider?.description || 'Set up your LLM connection'}
            </p>
          </div>

          {renderLLMConfig()}
        </div>
      )
    }

    // Standard configuration for non-LLM connections
    const schema = selectedTypeInfo.config_schema
    const properties = schema.properties || {}

    return (
      <div className="space-y-6">
        <div className="text-center">
          <div className="inline-flex items-center justify-center p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg text-blue-600 dark:text-blue-400 mb-4">
            {getConnectionTypeIcon(selectedType)}
          </div>
          <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
            Configure {selectedTypeInfo.display_name}
          </h3>
          <p className="text-gray-600 dark:text-gray-400">
            {selectedTypeInfo.description}
          </p>
        </div>

        <div className="bg-gray-50 dark:bg-gray-900/50 rounded-xl p-6 space-y-5">
          <div className="space-y-2">
            <label htmlFor="connection-name" className="block text-sm font-medium text-gray-900 dark:text-gray-100">
              Connection Name
            </label>
            <input
              id="connection-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Primary SharePoint"
              required
              className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white transition-all"
            />
          </div>

          <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
            <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">Connection Settings</h4>
            <div className="space-y-5">
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
        <div className="text-center">
          <div className="inline-flex items-center justify-center p-3 bg-green-50 dark:bg-green-900/20 rounded-lg text-green-600 dark:text-green-400 mb-4">
            <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
            Review Connection
          </h3>
          <p className="text-gray-600 dark:text-gray-400">
            Verify your connection details before saving
          </p>
        </div>

        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
          <div className="bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/20 dark:to-indigo-900/20 px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center space-x-3">
              <div className="text-blue-600 dark:text-blue-400">
                {getConnectionTypeIcon(selectedType)}
              </div>
              <div>
                <h4 className="text-lg font-semibold text-gray-900 dark:text-white">{name}</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  {selectedProvider?.name || selectedTypeInfo.display_name}
                </p>
              </div>
            </div>
          </div>

          <div className="p-6 space-y-4">
            {Object.entries(config).map(([key, value]) => {
              const isSecret = key.toLowerCase().includes('secret') || key.toLowerCase().includes('password') || key.toLowerCase().includes('key')

              return (
                <div key={key} className="flex justify-between items-start py-3 border-b border-gray-100 dark:border-gray-700 last:border-0">
                  <div className="flex-1">
                    <dt className="text-sm font-medium text-gray-900 dark:text-gray-100 capitalize">
                      {key.replace(/_/g, ' ')}
                    </dt>
                  </div>
                  <dd className="text-sm text-gray-700 dark:text-gray-300 font-mono bg-gray-50 dark:bg-gray-900 px-3 py-1 rounded max-w-md truncate">
                    {isSecret ? '••••••••' : String(value) || 'Not set'}
                  </dd>
                </div>
              )
            })}
          </div>
        </div>

        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
          <div className="flex items-start space-x-3">
            <div className="flex-shrink-0">
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={isDefault}
                  onChange={(e) => setIsDefault(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 dark:peer-focus:ring-blue-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-blue-600"></div>
              </label>
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium text-gray-900 dark:text-white">
                Set as default connection
              </p>
              <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">
                This connection will be used by default for this type
              </p>
            </div>
          </div>
        </div>

        {!connection && (
          <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-700 rounded-lg p-4">
            <div className="flex items-start space-x-3">
              <div className="flex-shrink-0">
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={testOnSave}
                    onChange={(e) => setTestOnSave(e.target.checked)}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 dark:peer-focus:ring-blue-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-blue-600"></div>
                </label>
              </div>
              <div className="flex-1">
                <p className="text-sm font-medium text-gray-900 dark:text-white">
                  Test connection before saving
                </p>
                <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">
                  Verify that the connection works before creating it
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg overflow-hidden">
      <div className="bg-gradient-to-r from-blue-600 to-indigo-600 px-8 py-6">
        <h2 className="text-2xl font-bold text-white">
          {connection ? 'Edit Connection' : 'New Connection'}
        </h2>
        <p className="text-blue-100 mt-1">
          {connection ? 'Update your connection settings' : 'Set up a new service connection'}
        </p>
      </div>

      <div className="p-8">
        {error && (
          <div className="mb-6 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4">
            <div className="flex">
              <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
              <p className="ml-3 text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          </div>
        )}

        {connection?.is_managed && (
          <div className="mb-6 rounded-lg bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 p-4">
            <div className="flex">
              <svg className="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
              <div className="ml-3">
                <h3 className="text-sm font-medium text-yellow-800 dark:text-yellow-200">
                  Managed Connection
                </h3>
                <p className="mt-1 text-sm text-yellow-700 dark:text-yellow-300">
                  This connection is managed by environment variables and cannot be edited through the UI.
                  {connection.managed_by && (
                    <span className="block mt-1 text-xs">{connection.managed_by}</span>
                  )}
                </p>
              </div>
            </div>
          </div>
        )}

        {renderStepIndicator()}

        <form onSubmit={handleSubmit} className="space-y-8">
          {currentStep === 'select-type' && renderSelectType()}
          {currentStep === 'select-provider' && renderSelectProvider()}
          {currentStep === 'configure' && renderConfigure()}
          {currentStep === 'review' && renderReview()}

          <div className="flex items-center justify-between pt-6 border-t border-gray-200 dark:border-gray-700">
            <div className="flex gap-3">
              {currentStep === 'select-provider' && (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setCurrentStep('select-type')}
                >
                  ← Back
                </Button>
              )}
              {currentStep === 'configure' && !connection && (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setCurrentStep(selectedType === 'llm' ? 'select-provider' : 'select-type')}
                >
                  ← Back
                </Button>
              )}
              {currentStep === 'review' && (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setCurrentStep('configure')}
                >
                  ← Back
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
                  disabled={!name || !selectedType || (selectedType === 'llm' && !config.model)}
                >
                  Continue →
                </Button>
              )}
              {currentStep === 'review' && (
                <Button type="submit" disabled={isLoading}>
                  {isLoading ? (
                    <span className="flex items-center">
                      <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                      Saving...
                    </span>
                  ) : (
                    connection ? 'Update Connection' : 'Create Connection'
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

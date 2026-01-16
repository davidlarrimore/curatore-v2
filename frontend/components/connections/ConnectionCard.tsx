import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { CheckCircle, XCircle, AlertCircle, Loader2, RefreshCw, ExternalLink } from 'lucide-react'

interface Connection {
  id: string
  name: string
  connection_type: string
  config: Record<string, any>
  is_default: boolean
  is_active: boolean
  is_managed?: boolean
  managed_by?: string
  last_tested_at?: string
  health_status?: 'healthy' | 'unhealthy' | 'unknown' | 'checking'
  created_at: string
  updated_at: string
}

interface ConnectionCardProps {
  connection: Connection
  isChecking?: boolean
  onEdit: () => void
  onDelete: () => void
  onTest: () => void
  onSetDefault: () => void
}

export default function ConnectionCard({
  connection,
  isChecking = false,
  onEdit,
  onDelete,
  onTest,
  onSetDefault,
}: ConnectionCardProps) {
  // Determine effective status (isChecking overrides health_status)
  const effectiveStatus = isChecking ? 'checking' : (connection.health_status || 'unknown')

  // Health status styling matching the health page
  const getCardBorderColor = () => {
    if (!connection.is_active) return 'border-gray-300 dark:border-gray-600'

    switch (effectiveStatus) {
      case 'healthy':
        return 'border-green-300 dark:border-green-700'
      case 'unhealthy':
        return 'border-red-300 dark:border-red-700'
      case 'checking':
        return 'border-blue-300 dark:border-blue-700'
      default:
        return 'border-gray-200 dark:border-gray-700'
    }
  }

  const getCardBgColor = () => {
    if (!connection.is_active) return 'bg-gray-50 dark:bg-gray-800/50'

    switch (effectiveStatus) {
      case 'healthy':
        return 'bg-green-50 dark:bg-green-900/20'
      case 'unhealthy':
        return 'bg-red-50 dark:bg-red-900/20'
      case 'checking':
        return 'bg-blue-50 dark:bg-blue-900/20 animate-pulse'
      default:
        return 'bg-white dark:bg-gray-800'
    }
  }

  const getStatusIcon = () => {
    if (!connection.is_active) {
      return <AlertCircle className="w-5 h-5 text-gray-400" />
    }

    switch (effectiveStatus) {
      case 'healthy':
        return <CheckCircle className="w-5 h-5 text-green-500" />
      case 'unhealthy':
        return <XCircle className="w-5 h-5 text-red-500" />
      case 'checking':
        return <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
      default:
        return <AlertCircle className="w-5 h-5 text-gray-400" />
    }
  }

  const getStatusBadgeColor = () => {
    switch (effectiveStatus) {
      case 'healthy':
        return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
      case 'unhealthy':
        return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'
      case 'checking':
        return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
      default:
        return 'bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-300'
    }
  }

  const getDocsUrl = (): string | null => {
    const { connection_type, config } = connection

    if (connection_type === 'llm') {
      if (config.base_url?.includes('openai.com')) {
        return 'https://platform.openai.com/docs'
      }
      if (config.base_url?.includes('localhost:11434') || config.base_url?.includes('ollama')) {
        return 'https://ollama.com/docs'
      }
      return null
    }

    if (connection_type === 'sharepoint') {
      return 'https://learn.microsoft.com/en-us/graph/api/overview'
    }

    if (connection_type === 'extraction') {
      if (config.service_url) {
        return `${config.service_url}/api/v1/docs`
      }
      return null
    }

    return null
  }

  const getConfigSummary = () => {
    const { connection_type, config } = connection

    if (connection_type === 'llm') {
      return (
        <div className="text-sm text-gray-600 dark:text-gray-400 space-y-1">
          <div className="flex justify-between">
            <span className="font-medium">Model:</span>
            <span className="truncate ml-2">{config.model || 'N/A'}</span>
          </div>
          <div className="flex justify-between">
            <span className="font-medium">Endpoint:</span>
            <span className="truncate ml-2" title={config.base_url}>
              {config.base_url?.replace(/^https?:\/\//, '') || 'N/A'}
            </span>
          </div>
        </div>
      )
    }

    if (connection_type === 'sharepoint') {
      return (
        <div className="text-sm text-gray-600 dark:text-gray-400 space-y-1">
          <div className="flex justify-between">
            <span className="font-medium">Tenant:</span>
            <span className="truncate ml-2" title={config.tenant_id}>
              {config.tenant_id?.substring(0, 8)}...
            </span>
          </div>
          <div className="flex justify-between">
            <span className="font-medium">Client:</span>
            <span className="truncate ml-2" title={config.client_id}>
              {config.client_id?.substring(0, 8)}...
            </span>
          </div>
        </div>
      )
    }

    if (connection_type === 'extraction') {
      return (
        <div className="text-sm text-gray-600 dark:text-gray-400 space-y-1">
          <div className="flex justify-between">
            <span className="font-medium">URL:</span>
            <span className="truncate ml-2" title={config.service_url}>
              {config.service_url?.replace(/^https?:\/\//, '') || 'N/A'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="font-medium">Timeout:</span>
            <span>{config.timeout || 30}s</span>
          </div>
        </div>
      )
    }

    return null
  }

  const docsUrl = getDocsUrl()

  return (
    <div className={`border-2 rounded-lg p-4 transition-all hover:shadow-md ${getCardBorderColor()} ${getCardBgColor()}`}>
      {/* Header with status icon and name */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-start space-x-3 flex-1 min-w-0">
          {getStatusIcon()}
          <div className="flex-1 min-w-0">
            <div className="flex items-center space-x-2">
              {docsUrl && effectiveStatus === 'healthy' ? (
                <a
                  href={docsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-lg font-semibold text-gray-900 dark:text-white hover:text-blue-600 dark:hover:text-blue-400 transition-colors flex items-center space-x-1 group"
                  title="View documentation"
                >
                  <span className="truncate">{connection.name}</span>
                  <ExternalLink className="w-3.5 h-3.5 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                </a>
              ) : (
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white truncate">
                  {connection.name}
                </h3>
              )}
            </div>
            <div className="flex gap-2 mt-1 flex-wrap">
              {connection.is_default && (
                <Badge variant="info">Default</Badge>
              )}
              {connection.is_managed && (
                <Badge variant="warning" title={connection.managed_by || 'Managed by environment variables'}>
                  Managed
                </Badge>
              )}
              {!connection.is_active && (
                <Badge variant="error">Inactive</Badge>
              )}
            </div>
          </div>
        </div>

        {/* Status badge and retest button */}
        <div className="flex items-center space-x-2 flex-shrink-0">
          <button
            onClick={onTest}
            disabled={isChecking}
            className={`p-1.5 rounded-md transition-colors ${
              isChecking
                ? 'text-gray-400 cursor-not-allowed'
                : 'text-gray-500 hover:text-gray-700 hover:bg-gray-200 dark:hover:bg-gray-700'
            }`}
            title={`Test ${connection.name}`}
            aria-label={`Test ${connection.name}`}
          >
            <RefreshCw className={`w-4 h-4 ${isChecking ? 'animate-spin' : ''}`} />
          </button>
          <span className={`text-xs px-2 py-1 rounded-full font-medium ${getStatusBadgeColor()}`}>
            {effectiveStatus === 'checking' ? 'checking...' : effectiveStatus}
          </span>
        </div>
      </div>

      {/* Config summary */}
      <div className="mb-3 pt-2 border-t border-gray-200/50 dark:border-gray-700/50">
        {getConfigSummary()}
      </div>

      {/* Last tested timestamp */}
      {connection.last_tested_at && (
        <p className="text-xs text-gray-500 dark:text-gray-500 mb-3">
          Last tested: {new Date(connection.last_tested_at).toLocaleString()}
        </p>
      )}

      {/* Action buttons */}
      <div className="flex gap-2 flex-wrap pt-2 border-t border-gray-200/50 dark:border-gray-700/50">
        {!connection.is_managed && (
          <Button
            onClick={onEdit}
            variant="secondary"
            size="sm"
          >
            Edit
          </Button>
        )}
        {!connection.is_default && !connection.is_managed && (
          <Button
            onClick={onSetDefault}
            variant="secondary"
            size="sm"
          >
            Set Default
          </Button>
        )}
        {!connection.is_managed && (
          <Button
            onClick={onDelete}
            variant="destructive"
            size="sm"
          >
            Delete
          </Button>
        )}
        {connection.is_managed && (
          <span className="text-xs text-gray-500 dark:text-gray-400 italic self-center">
            Managed by environment variables
          </span>
        )}
      </div>
    </div>
  )
}

import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'

interface Connection {
  id: string
  name: string
  connection_type: string
  config: Record<string, any>
  is_default: boolean
  is_active: boolean
  last_tested_at?: string
  health_status?: 'healthy' | 'unhealthy' | 'unknown'
  created_at: string
  updated_at: string
}

interface ConnectionCardProps {
  connection: Connection
  onEdit: () => void
  onDelete: () => void
  onTest: () => void
  onSetDefault: () => void
}

export default function ConnectionCard({
  connection,
  onEdit,
  onDelete,
  onTest,
  onSetDefault,
}: ConnectionCardProps) {
  const getStatusColor = (status?: string) => {
    switch (status) {
      case 'healthy':
        return 'bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-200'
      case 'unhealthy':
        return 'bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-200'
      default:
        return 'bg-gray-100 text-gray-800 dark:bg-gray-900/20 dark:text-gray-200'
    }
  }

  const getConfigSummary = () => {
    const { connection_type, config } = connection

    if (connection_type === 'llm') {
      return (
        <div className="text-sm text-gray-600 dark:text-gray-400 space-y-1">
          <p><span className="font-medium">Model:</span> {config.model || 'N/A'}</p>
          <p><span className="font-medium">Base URL:</span> {config.base_url || 'N/A'}</p>
        </div>
      )
    }

    if (connection_type === 'sharepoint') {
      return (
        <div className="text-sm text-gray-600 dark:text-gray-400 space-y-1">
          <p><span className="font-medium">Tenant:</span> {config.tenant_id?.substring(0, 8)}...</p>
          <p><span className="font-medium">Client:</span> {config.client_id?.substring(0, 8)}...</p>
        </div>
      )
    }

    if (connection_type === 'extraction') {
      return (
        <div className="text-sm text-gray-600 dark:text-gray-400 space-y-1">
          <p><span className="font-medium">Service URL:</span> {config.service_url || 'N/A'}</p>
          <p><span className="font-medium">Timeout:</span> {config.timeout || 30}s</p>
        </div>
      )
    }

    return null
  }

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-gray-800 hover:shadow-md transition-shadow">
      <div className="flex justify-between items-start mb-3">
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            {connection.name}
          </h3>
          <div className="flex gap-2 mt-1 flex-wrap">
            {connection.is_default && (
              <Badge variant="primary">Default</Badge>
            )}
            {!connection.is_active && (
              <Badge variant="error">Inactive</Badge>
            )}
            {connection.health_status && (
              <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${getStatusColor(connection.health_status)}`}>
                {connection.health_status === 'healthy' ? '✓' : connection.health_status === 'unhealthy' ? '✗' : '?'} {connection.health_status}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="mb-4">
        {getConfigSummary()}
      </div>

      {connection.last_tested_at && (
        <p className="text-xs text-gray-500 dark:text-gray-500 mb-3">
          Last tested: {new Date(connection.last_tested_at).toLocaleString()}
        </p>
      )}

      <div className="flex gap-2 flex-wrap">
        <Button
          onClick={onTest}
          variant="secondary"
          size="sm"
        >
          Test
        </Button>
        <Button
          onClick={onEdit}
          variant="secondary"
          size="sm"
        >
          Edit
        </Button>
        {!connection.is_default && (
          <Button
            onClick={onSetDefault}
            variant="secondary"
            size="sm"
          >
            Set Default
          </Button>
        )}
        <Button
          onClick={onDelete}
          variant="destructive"
          size="sm"
        >
          Delete
        </Button>
      </div>
    </div>
  )
}

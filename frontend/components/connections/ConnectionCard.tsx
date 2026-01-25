import { CheckCircle, XCircle, AlertCircle, Loader2, RefreshCw, ExternalLink, MoreHorizontal, Pencil, Trash2, Star } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'

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
  test_result?: Record<string, any> | null
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
  const [showMenu, setShowMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setShowMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Determine effective status (isChecking overrides health_status)
  const effectiveStatus = isChecking ? 'checking' : (connection.health_status || 'unknown')

  const getStatusConfig = () => {
    if (!connection.is_active) {
      return {
        icon: <AlertCircle className="w-4 h-4" />,
        label: 'Inactive',
        dotColor: 'bg-gray-400',
        textColor: 'text-gray-500 dark:text-gray-400',
        bgColor: 'bg-gray-50 dark:bg-gray-800/50'
      }
    }

    switch (effectiveStatus) {
      case 'healthy':
        return {
          icon: <CheckCircle className="w-4 h-4" />,
          label: 'Healthy',
          dotColor: 'bg-emerald-500',
          textColor: 'text-emerald-600 dark:text-emerald-400',
          bgColor: 'bg-emerald-50 dark:bg-emerald-900/20'
        }
      case 'unhealthy':
        return {
          icon: <XCircle className="w-4 h-4" />,
          label: 'Unhealthy',
          dotColor: 'bg-red-500',
          textColor: 'text-red-600 dark:text-red-400',
          bgColor: 'bg-red-50 dark:bg-red-900/20'
        }
      case 'checking':
        return {
          icon: <Loader2 className="w-4 h-4 animate-spin" />,
          label: 'Checking',
          dotColor: 'bg-blue-500',
          textColor: 'text-blue-600 dark:text-blue-400',
          bgColor: 'bg-blue-50 dark:bg-blue-900/20'
        }
      default:
        return {
          icon: <AlertCircle className="w-4 h-4" />,
          label: 'Unknown',
          dotColor: 'bg-gray-400',
          textColor: 'text-gray-500 dark:text-gray-400',
          bgColor: 'bg-gray-50 dark:bg-gray-800/50'
        }
    }
  }

  const statusConfig = getStatusConfig()

  const getDocsUrl = (): string | null => {
    const { connection_type, config } = connection

    if (connection_type === 'llm') {
      if (config.base_url?.includes('openai.com')) {
        return 'https://platform.openai.com/docs'
      }
      if (config.base_url?.includes('localhost:11434') || config.base_url?.includes('ollama')) {
        return 'https://ollama.com/docs'
      }
      if (config.base_url?.includes('anthropic.com')) {
        return 'https://docs.anthropic.com'
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

  type SummaryItem = {
    label: string
    value: string
    hint?: string
  }

  const getConfigSummary = (): SummaryItem[] => {
    const { connection_type, config } = connection

    if (connection_type === 'llm') {
      return [
        { label: 'Model', value: config.model || 'Not set' },
        { label: 'Endpoint', value: config.base_url?.replace(/^https?:\/\//, '').split('/')[0] || 'Not set' }
      ]
    }

    if (connection_type === 'sharepoint') {
      return [
        { label: 'Tenant', value: config.tenant_id ? `${config.tenant_id.substring(0, 8)}...` : 'Not set' },
        { label: 'Client', value: config.client_id ? `${config.client_id.substring(0, 8)}...` : 'Not set' }
      ]
    }

    if (connection_type === 'extraction') {
      // Determine engine type label
      const engineType = config.engine_type || 'unknown'
      const engineLabel = engineType === 'extraction-service'
        ? 'Internal Service'
        : engineType === 'docling'
        ? 'Docling'
        : engineType === 'tika'
        ? 'Apache Tika'
        : engineType.charAt(0).toUpperCase() + engineType.slice(1)

      const doclingVersion = connection.test_result?.details?.docling_api_version

      const summary: SummaryItem[] = [
        { label: 'Engine', value: engineLabel },
        { label: 'URL', value: config.service_url?.replace(/^https?:\/\//, '') || 'Not set' },
        { label: 'Timeout', value: `${config.timeout || 30}s` }
      ]

      if (engineType === 'docling' && doclingVersion) {
        summary.push({ label: 'Docling API', value: doclingVersion, hint: 'Detected from Docling openapi.json' })
      }

      return summary
    }

    return []
  }

  const docsUrl = getDocsUrl()
  const configSummary = getConfigSummary()

  const formatLastTested = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString()
  }

  return (
    <div className="group relative bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 hover:shadow-lg hover:shadow-gray-200/50 dark:hover:shadow-gray-900/50 transition-all duration-200 overflow-hidden">
      {/* Status indicator bar */}
      <div className={`absolute top-0 left-0 right-0 h-1 ${
        effectiveStatus === 'healthy' ? 'bg-gradient-to-r from-emerald-400 to-emerald-500' :
        effectiveStatus === 'unhealthy' ? 'bg-gradient-to-r from-red-400 to-red-500' :
        effectiveStatus === 'checking' ? 'bg-gradient-to-r from-blue-400 to-blue-500 animate-pulse' :
        'bg-gradient-to-r from-gray-300 to-gray-400 dark:from-gray-600 dark:to-gray-700'
      }`} />

      <div className="p-5">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 mb-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1.5">
              {docsUrl && effectiveStatus === 'healthy' ? (
                <a
                  href={docsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-base font-semibold text-gray-900 dark:text-white hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors truncate flex items-center gap-1.5 group/link"
                  title="View documentation"
                >
                  <span className="truncate">{connection.name}</span>
                  <ExternalLink className="w-3.5 h-3.5 flex-shrink-0 opacity-0 group-hover/link:opacity-100 transition-opacity" />
                </a>
              ) : (
                <h3 className="text-base font-semibold text-gray-900 dark:text-white truncate">
                  {connection.name}
                </h3>
              )}
            </div>

            {/* Badges */}
            <div className="flex items-center gap-2 flex-wrap">
              {connection.is_default && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300">
                  <Star className="w-3 h-3" />
                  Default
                </span>
              )}
              {connection.is_managed && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300" title={connection.managed_by || 'Managed by environment variables'}>
                  Managed
                </span>
              )}
              {!connection.is_active && (
                <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                  Disabled
                </span>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1">
            <button
              onClick={onTest}
              disabled={isChecking}
              className={`p-2 rounded-lg transition-all ${
                isChecking
                  ? 'text-gray-300 dark:text-gray-600 cursor-not-allowed'
                  : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
              }`}
              title="Test connection"
            >
              <RefreshCw className={`w-4 h-4 ${isChecking ? 'animate-spin' : ''}`} />
            </button>

            {!connection.is_managed && (
              <div className="relative" ref={menuRef}>
                <button
                  onClick={() => setShowMenu(!showMenu)}
                  className="p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-all"
                  title="More options"
                >
                  <MoreHorizontal className="w-4 h-4" />
                </button>

                {showMenu && (
                  <div className="absolute right-0 top-full mt-1 w-40 bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 py-1 z-10">
                    <button
                      onClick={() => { onEdit(); setShowMenu(false); }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                    >
                      <Pencil className="w-4 h-4" />
                      Edit
                    </button>
                    {!connection.is_default && (
                      <button
                        onClick={() => { onSetDefault(); setShowMenu(false); }}
                        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                      >
                        <Star className="w-4 h-4" />
                        Set as Default
                      </button>
                    )}
                    <hr className="my-1 border-gray-200 dark:border-gray-700" />
                    <button
                      onClick={() => { onDelete(); setShowMenu(false); }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                      Delete
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Config Summary */}
        <div className="space-y-2 mb-4">
          {configSummary.map((item, index) => (
            <div key={index} className="flex items-center justify-between text-sm">
              <span className="text-gray-500 dark:text-gray-400" title={item.hint || undefined}>
                {item.label}
              </span>
              <span className="font-mono text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/50 px-2 py-0.5 rounded truncate max-w-[180px]" title={item.value}>
                {item.value}
              </span>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between pt-3 border-t border-gray-100 dark:border-gray-700/50">
          {/* Status Badge */}
          <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${statusConfig.bgColor} ${statusConfig.textColor}`}>
            {statusConfig.icon}
            <span>{statusConfig.label}</span>
          </div>

          {/* Last tested */}
          {connection.last_tested_at && (
            <span className="text-xs text-gray-400 dark:text-gray-500">
              {formatLastTested(connection.last_tested_at)}
            </span>
          )}
        </div>

        {/* Managed indicator */}
        {connection.is_managed && (
          <p className="mt-3 text-xs text-gray-400 dark:text-gray-500 italic">
            Managed via environment variables
          </p>
        )}
      </div>
    </div>
  )
}

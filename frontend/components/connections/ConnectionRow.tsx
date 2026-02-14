'use client'

import { CheckCircle, XCircle, AlertCircle, Loader2, RefreshCw, Pencil, Eye, Trash2, Star, Shield, FolderSync, FileText, Link2 } from 'lucide-react'

interface Connection {
  id: string
  name: string
  connection_type: string
  config: Record<string, unknown>
  is_default: boolean
  is_active: boolean
  is_managed?: boolean
  managed_by?: string
  last_tested_at?: string
  health_status?: 'healthy' | 'unhealthy' | 'unknown' | 'checking'
  test_result?: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

interface ConnectionRowProps {
  connection: Connection
  isChecking?: boolean
  onEdit: () => void
  onView: () => void
  onDelete: () => void
  onTest: () => void
  onSetDefault: () => void
}

export default function ConnectionRow({
  connection,
  isChecking = false,
  onEdit,
  onView,
  onDelete,
  onTest,
  onSetDefault,
}: ConnectionRowProps) {
  // Determine effective status
  const effectiveStatus = isChecking ? 'checking' : (connection.health_status || 'unknown')

  const getStatusConfig = () => {
    if (!connection.is_active) {
      return {
        icon: <AlertCircle className="w-4 h-4" />,
        label: 'Inactive',
        dotColor: 'bg-gray-400',
        textColor: 'text-gray-500 dark:text-gray-400',
        bgColor: 'bg-gray-100 dark:bg-gray-800'
      }
    }

    switch (effectiveStatus) {
      case 'healthy':
        return {
          icon: <CheckCircle className="w-4 h-4" />,
          label: 'Healthy',
          dotColor: 'bg-emerald-500',
          textColor: 'text-emerald-600 dark:text-emerald-400',
          bgColor: 'bg-emerald-50 dark:bg-emerald-900/30'
        }
      case 'unhealthy':
        return {
          icon: <XCircle className="w-4 h-4" />,
          label: 'Unhealthy',
          dotColor: 'bg-red-500',
          textColor: 'text-red-600 dark:text-red-400',
          bgColor: 'bg-red-50 dark:bg-red-900/30'
        }
      case 'checking':
        return {
          icon: <Loader2 className="w-4 h-4 animate-spin" />,
          label: 'Checking',
          dotColor: 'bg-blue-500',
          textColor: 'text-blue-600 dark:text-blue-400',
          bgColor: 'bg-blue-50 dark:bg-blue-900/30'
        }
      default:
        return {
          icon: <AlertCircle className="w-4 h-4" />,
          label: 'Unknown',
          dotColor: 'bg-gray-400',
          textColor: 'text-gray-500 dark:text-gray-400',
          bgColor: 'bg-gray-100 dark:bg-gray-800'
        }
    }
  }

  const getTypeIcon = () => {
    switch (connection.connection_type) {
      case 'microsoft_graph':
        return <FolderSync className="w-4 h-4" />
      case 'extraction':
        return <FileText className="w-4 h-4" />
      default:
        return <Link2 className="w-4 h-4" />
    }
  }

  const getTypeGradient = () => {
    switch (connection.connection_type) {
      case 'microsoft_graph':
        return 'from-blue-500 to-cyan-500'
      case 'extraction':
        return 'from-emerald-500 to-teal-500'
      default:
        return 'from-gray-500 to-gray-600'
    }
  }

  const getConfigSummary = (): string => {
    const { connection_type, config } = connection

    if (connection_type === 'microsoft_graph') {
      const tenantId = typeof config.tenant_id === 'string' ? config.tenant_id : ''
      const tenant = tenantId ? `${tenantId.substring(0, 8)}...` : ''
      return tenant ? `Tenant: ${tenant}` : 'Not configured'
    }

    if (connection_type === 'extraction') {
      const engineType = typeof config.engine_type === 'string' ? config.engine_type : 'unknown'
      const serviceUrl = typeof config.service_url === 'string' ? config.service_url : ''
      const url = serviceUrl ? serviceUrl.replace(/^https?:\/\//, '') : ''
      return `${engineType}${url ? ` @ ${url}` : ''}`
    }

    return ''
  }

  const statusConfig = getStatusConfig()
  const configSummary = getConfigSummary()

  return (
    <div className={`group flex items-center gap-4 px-4 py-3 bg-white dark:bg-gray-800 rounded-lg border transition-all hover:shadow-md ${
      effectiveStatus === 'healthy'
        ? 'border-emerald-200 dark:border-emerald-900/50 hover:border-emerald-300 dark:hover:border-emerald-800'
        : effectiveStatus === 'unhealthy'
        ? 'border-red-200 dark:border-red-900/50 hover:border-red-300 dark:hover:border-red-800'
        : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
    }`}>
      {/* Type Icon */}
      <div className={`flex-shrink-0 w-9 h-9 rounded-lg bg-gradient-to-br ${getTypeGradient()} flex items-center justify-center text-white shadow-sm`}>
        {getTypeIcon()}
      </div>

      {/* Name & Config */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white truncate">
            {connection.name}
          </h3>
          {/* Badges */}
          {connection.is_default && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300">
              <Star className="w-3 h-3" />
              Default
            </span>
          )}
          {connection.is_managed && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300">
              <Shield className="w-3 h-3" />
              Managed
            </span>
          )}
        </div>
        {configSummary && (
          <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
            {configSummary}
          </p>
        )}
      </div>

      {/* Health Status */}
      <div className={`flex-shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${statusConfig.bgColor} ${statusConfig.textColor}`}>
        {statusConfig.icon}
        <span className="hidden sm:inline">{statusConfig.label}</span>
      </div>

      {/* Actions */}
      <div className="flex-shrink-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {/* Test/Refresh */}
        <button
          onClick={onTest}
          disabled={isChecking}
          className={`p-2 rounded-lg transition-all ${
            isChecking
              ? 'text-gray-300 dark:text-gray-600 cursor-not-allowed'
              : 'text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30'
          }`}
          title="Test connection"
        >
          <RefreshCw className={`w-4 h-4 ${isChecking ? 'animate-spin' : ''}`} />
        </button>

        {/* View (for managed) or Edit (for non-managed) */}
        {connection.is_managed ? (
          <button
            onClick={onView}
            className="p-2 rounded-lg text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 transition-all"
            title="View settings"
          >
            <Eye className="w-4 h-4" />
          </button>
        ) : (
          <button
            onClick={onEdit}
            className="p-2 rounded-lg text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 transition-all"
            title="Edit connection"
          >
            <Pencil className="w-4 h-4" />
          </button>
        )}

        {/* Set Default (only for non-default, non-managed) */}
        {!connection.is_default && !connection.is_managed && (
          <button
            onClick={onSetDefault}
            className="p-2 rounded-lg text-gray-400 hover:text-amber-600 dark:hover:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/30 transition-all"
            title="Set as default"
          >
            <Star className="w-4 h-4" />
          </button>
        )}

        {/* Delete (only for non-managed) */}
        {!connection.is_managed && (
          <button
            onClick={onDelete}
            className="p-2 rounded-lg text-gray-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 transition-all"
            title="Delete connection"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  )
}

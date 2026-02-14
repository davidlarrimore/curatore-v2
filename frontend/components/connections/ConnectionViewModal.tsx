'use client'

import { X, Star, Shield, Copy, Check, ExternalLink } from 'lucide-react'
import { useState } from 'react'

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

interface ConnectionViewModalProps {
  connection: Connection
  onClose: () => void
}

export default function ConnectionViewModal({ connection, onClose }: ConnectionViewModalProps) {
  const [copiedField, setCopiedField] = useState<string | null>(null)

  const copyToClipboard = (value: string, field: string) => {
    navigator.clipboard.writeText(value)
    setCopiedField(field)
    setTimeout(() => setCopiedField(null), 2000)
  }

  const getTypeLabel = (type: string) => {
    switch (type) {
      case 'microsoft_graph': return 'Microsoft Graph API'
      case 'extraction': return 'Extraction Service'
      default: return type
    }
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString()
  }

  // Get sensitive field names that should be masked
  const sensitiveFields = ['client_secret', 'api_key', 'secret', 'password', 'token']
  const isSensitive = (key: string) => sensitiveFields.some(f => key.toLowerCase().includes(f))

  const renderConfigValue = (key: string, value: unknown) => {
    if (value === null || value === undefined) return <span className="text-gray-400 italic">Not set</span>

    const stringValue = typeof value === 'object' ? JSON.stringify(value) : String(value)
    const masked = isSensitive(key)
    const displayValue = masked ? '••••••••••••••••' : stringValue

    return (
      <div className="flex items-center gap-2">
        <code className="text-sm font-mono text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-900 px-2 py-1 rounded max-w-md truncate">
          {displayValue}
        </code>
        {!masked && stringValue && (
          <button
            onClick={() => copyToClipboard(stringValue, key)}
            className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
            title="Copy to clipboard"
          >
            {copiedField === key ? (
              <Check className="w-4 h-4 text-green-500" />
            ) : (
              <Copy className="w-4 h-4" />
            )}
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-white dark:bg-gray-800 rounded-xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
              {connection.name}
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {getTypeLabel(connection.connection_type)}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-4 overflow-y-auto max-h-[calc(90vh-140px)]">
          {/* Status Badges */}
          <div className="flex items-center gap-2 mb-6">
            {connection.is_default && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300">
                <Star className="w-3.5 h-3.5" />
                Default
              </span>
            )}
            {connection.is_managed && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300">
                <Shield className="w-3.5 h-3.5" />
                Managed
              </span>
            )}
            {!connection.is_active && (
              <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                Disabled
              </span>
            )}
          </div>

          {/* Managed By Info */}
          {connection.is_managed && connection.managed_by && (
            <div className="mb-6 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
              <p className="text-sm text-amber-800 dark:text-amber-200">
                <strong>Managed by:</strong> {connection.managed_by}
              </p>
              <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">
                This connection is automatically configured from environment variables and cannot be edited.
              </p>
            </div>
          )}

          {/* Configuration */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white uppercase tracking-wider">
              Configuration
            </h3>
            <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg border border-gray-200 dark:border-gray-700 divide-y divide-gray-200 dark:divide-gray-700">
              {Object.entries(connection.config).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between px-4 py-3">
                  <span className="text-sm text-gray-600 dark:text-gray-400 font-medium">
                    {key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                  </span>
                  {renderConfigValue(key, value)}
                </div>
              ))}
            </div>
          </div>

          {/* Test Results */}
          {connection.test_result && (
            <div className="mt-6 space-y-4">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white uppercase tracking-wider">
                Last Test Result
              </h3>
              <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className={`w-2 h-2 rounded-full ${connection.test_result.success ? 'bg-green-500' : 'bg-red-500'}`} />
                  <span className={`text-sm font-medium ${connection.test_result.success ? 'text-green-700 dark:text-green-400' : 'text-red-700 dark:text-red-400'}`}>
                    {connection.test_result.success ? 'Success' : 'Failed'}
                  </span>
                </div>
                {typeof connection.test_result.message === 'string' && (
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    {connection.test_result.message}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Metadata */}
          <div className="mt-6 pt-4 border-t border-gray-200 dark:border-gray-700">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-gray-500 dark:text-gray-400">Created</span>
                <p className="text-gray-700 dark:text-gray-300">{formatDate(connection.created_at)}</p>
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">Last Updated</span>
                <p className="text-gray-700 dark:text-gray-300">{formatDate(connection.updated_at)}</p>
              </div>
              {connection.last_tested_at && (
                <div>
                  <span className="text-gray-500 dark:text-gray-400">Last Tested</span>
                  <p className="text-gray-700 dark:text-gray-300">{formatDate(connection.last_tested_at)}</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
          <button
            onClick={onClose}
            className="w-full px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

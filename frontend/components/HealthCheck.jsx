// frontend/components/HealthCheck.jsx
'use client'

import { useState, useEffect } from 'react'
import { API_PATH_VERSION } from '@/lib/api'

export function HealthCheck({ apiUrl, health, llmConnected }) {
  const [llmStatus, setLlmStatus] = useState(null)
  const [isRefreshing, setIsRefreshing] = useState(false)

  const refreshLlmStatus = async () => {
    setIsRefreshing(true)
    try {
      const response = await fetch(`${apiUrl}/api/${API_PATH_VERSION}/admin/system/health/llm`)
      const data = await response.json()
      setLlmStatus({
        connected: data.status === 'healthy',
        endpoint: data.endpoint,
        model: data.model,
        message: data.message,
        error: data.status === 'unhealthy' ? data.message : undefined,
      })
    } catch (error) {
      console.error('Failed to fetch LLM status:', error)
      setLlmStatus({ connected: false, error: error.message })
    }
    setIsRefreshing(false)
  }

  useEffect(() => {
    refreshLlmStatus()
  }, [])

  const getStatusColor = (status) => {
    switch (status) {
      case 'healthy':
      case 'ok':
        return 'text-green-600 bg-green-100'
      case 'error':
        return 'text-red-600 bg-red-100'
      default:
        return 'text-yellow-600 bg-yellow-100'
    }
  }

  const getConnectionStatus = (connected) => {
    return connected 
      ? 'text-green-600 bg-green-100' 
      : 'text-red-600 bg-red-100'
  }

  return (
    <div className="bg-white rounded-2xl border shadow-sm p-6">
      <h2 className="text-2xl font-semibold mb-4">🔧 System Status</h2>
      
      <div className="space-y-4">
        {/* API Health */}
        <div className="flex items-center justify-between">
          <span className="font-medium text-gray-700">API Health</span>
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${getStatusColor(health)}`}>
            {health}
          </span>
        </div>

        {/* LLM Connection */}
        <div className="flex items-center justify-between">
          <span className="font-medium text-gray-700">LLM Connection</span>
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${getConnectionStatus(llmConnected)}`}>
            {llmConnected ? 'Connected' : 'Disconnected'}
          </span>
        </div>

        {/* Detailed LLM Status */}
        {llmStatus && (
          <div className="border-t pt-4 mt-4">
            <div className="flex items-center justify-between mb-2">
              <span className="font-medium text-gray-700">LLM Details</span>
              <button
                type="button"
                onClick={refreshLlmStatus}
                disabled={isRefreshing}
                className="text-blue-600 hover:text-blue-800 text-sm disabled:opacity-50"
              >
                {isRefreshing ? '🔄' : '🔍'} Test
              </button>
            </div>
            
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600">Endpoint:</span>
                <span className="font-mono text-xs">{llmStatus.endpoint}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Model:</span>
                <span className="font-mono text-xs">{llmStatus.model}</span>
              </div>
              {llmStatus.error && (
                <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded">
                  <span className="text-red-800 text-xs">Error: {llmStatus.error}</span>
                </div>
              )}

              {llmStatus.connected && llmStatus.message && (
                <div className="mt-2 p-2 bg-green-50 border border-green-200 rounded">
                  <span className="text-green-800 text-xs">{llmStatus.message}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* API URL */}
        <div className="border-t pt-4 mt-4">
          <div className="text-sm">
            <span className="text-gray-600">API URL:</span>
            <code className="ml-2 text-xs bg-gray-100 px-2 py-1 rounded">{apiUrl}</code>
          </div>
        </div>

        {/* Quick Actions */}
        <div className="border-t pt-4 mt-4">
          <div className="flex gap-2">
            <a
              href={`${apiUrl}/api/${API_PATH_VERSION}/docs`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 text-center bg-blue-50 text-blue-700 px-3 py-2 rounded-lg text-sm hover:bg-blue-100 transition-colors"
            >
              📚 API Docs
            </a>
            <a
              href={`${apiUrl}/api/${API_PATH_VERSION}/admin/system/health/comprehensive`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 text-center bg-gray-50 text-gray-700 px-3 py-2 rounded-lg text-sm hover:bg-gray-100 transition-colors"
            >
              💙 Health
            </a>
          </div>
        </div>
      </div>
    </div>
  )
}

// components/Settings.tsx
'use client'

import { useState, useEffect } from 'react';
import { LLMConnectionStatus } from '@/types';
import { systemApi } from '@/lib/api';

export function Settings() {
  const [llmStatus, setLLMStatus] = useState<LLMConnectionStatus | null>(null);
  const [isTestingLLM, setIsTestingLLM] = useState(false);

  // Load LLM status on mount
  useEffect(() => {
    testLLMConnection();
  }, []);

  const testLLMConnection = async () => {
    setIsTestingLLM(true);
    try {
      const status = await systemApi.getLLMStatus();
      setLLMStatus(status);
    } catch (error) {
      console.error('Failed to test LLM connection:', error);
      setLLMStatus({
        connected: false,
        endpoint: 'Unknown',
        model: 'Unknown',
        error: 'Connection test failed',
        ssl_verify: true,
        timeout: 60
      });
    } finally {
      setIsTestingLLM(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl border shadow-sm p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-semibold">⚙️ Settings</h2>
      </div>

      <div className="space-y-8">
        {/* LLM Connection Status */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium">🤖 LLM Connection</h3>
            <button
              type="button"
              onClick={testLLMConnection}
              disabled={isTestingLLM}
              className="px-3 py-1 text-sm bg-blue-100 hover:bg-blue-200 text-blue-700 rounded-md transition-colors disabled:opacity-50"
            >
              {isTestingLLM ? '🔄 Testing...' : '🔍 Test Connection'}
            </button>
          </div>

          {llmStatus && (
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                <span className="font-medium">Status</span>
                <span className={`px-2 py-1 rounded-full text-sm font-medium ${
                  llmStatus.connected 
                    ? 'bg-green-100 text-green-800' 
                    : 'bg-red-100 text-red-800'
                }`}>
                  {llmStatus.connected ? '✅ Connected' : '❌ Disconnected'}
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-600">Endpoint:</span>
                  <span className="font-mono text-xs truncate ml-2">{llmStatus.endpoint}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Model:</span>
                  <span className="font-mono text-xs">{llmStatus.model}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">SSL Verify:</span>
                  <span className={`px-1 py-0.5 rounded text-xs ${
                    llmStatus.ssl_verify ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'
                  }`}>
                    {llmStatus.ssl_verify ? 'Enabled' : 'Disabled'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Timeout:</span>
                  <span className="text-xs">{llmStatus.timeout}s</span>
                </div>
              </div>

              {llmStatus.error && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
                  <span className="text-red-800 text-sm">⚠️ {llmStatus.error}</span>
                </div>
              )}

              {llmStatus.response && (
                <div className="p-3 bg-green-50 border border-green-200 rounded-lg">
                  <span className="text-green-800 text-sm">✅ Response: {llmStatus.response}</span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

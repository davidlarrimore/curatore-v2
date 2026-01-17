// components/Settings.tsx
'use client'

import { useState, useEffect } from 'react';
import { LLMConnectionStatus } from '@/types';
import { systemApi } from '@/lib/api';
import {
  Bot,
  RefreshCw,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  Globe,
  Cpu,
  Shield,
  Clock
} from 'lucide-react';

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
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm p-6">
      <div className="space-y-8">
        {/* LLM Connection Status */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-3">
              <div className="p-2 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-lg">
                <Bot className="w-5 h-5 text-white" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">LLM Connection</h3>
            </div>
            <button
              type="button"
              onClick={testLLMConnection}
              disabled={isTestingLLM}
              className="inline-flex items-center px-3 py-1.5 text-sm bg-indigo-100 dark:bg-indigo-900/30 hover:bg-indigo-200 dark:hover:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 rounded-lg transition-colors disabled:opacity-50"
            >
              {isTestingLLM ? (
                <>
                  <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                  Testing...
                </>
              ) : (
                <>
                  <RefreshCw className="w-4 h-4 mr-1.5" />
                  Test Connection
                </>
              )}
            </button>
          </div>

          {llmStatus && (
            <div className="space-y-3">
              <div className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
                <span className="font-medium text-gray-900 dark:text-white">Status</span>
                <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${
                  llmStatus.connected
                    ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
                    : 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400'
                }`}>
                  {llmStatus.connected ? (
                    <>
                      <CheckCircle2 className="w-4 h-4 mr-1.5" />
                      Connected
                    </>
                  ) : (
                    <>
                      <XCircle className="w-4 h-4 mr-1.5" />
                      Disconnected
                    </>
                  )}
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
                  <div className="flex items-center">
                    <Globe className="w-4 h-4 text-gray-500 dark:text-gray-400 mr-2" />
                    <span className="text-gray-600 dark:text-gray-400">Endpoint</span>
                  </div>
                  <span className="font-mono text-xs text-gray-900 dark:text-white truncate ml-2 max-w-[150px]">{llmStatus.endpoint}</span>
                </div>
                <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
                  <div className="flex items-center">
                    <Cpu className="w-4 h-4 text-gray-500 dark:text-gray-400 mr-2" />
                    <span className="text-gray-600 dark:text-gray-400">Model</span>
                  </div>
                  <span className="font-mono text-xs text-gray-900 dark:text-white">{llmStatus.model}</span>
                </div>
                <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
                  <div className="flex items-center">
                    <Shield className="w-4 h-4 text-gray-500 dark:text-gray-400 mr-2" />
                    <span className="text-gray-600 dark:text-gray-400">SSL Verify</span>
                  </div>
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                    llmStatus.ssl_verify
                      ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
                      : 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400'
                  }`}>
                    {llmStatus.ssl_verify ? 'Enabled' : 'Disabled'}
                  </span>
                </div>
                <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
                  <div className="flex items-center">
                    <Clock className="w-4 h-4 text-gray-500 dark:text-gray-400 mr-2" />
                    <span className="text-gray-600 dark:text-gray-400">Timeout</span>
                  </div>
                  <span className="text-xs text-gray-900 dark:text-white font-medium">{llmStatus.timeout}s</span>
                </div>
              </div>

              {llmStatus.error && (
                <div className="flex items-start p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/50 rounded-lg">
                  <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 mr-3 flex-shrink-0 mt-0.5" />
                  <span className="text-red-800 dark:text-red-200 text-sm">{llmStatus.error}</span>
                </div>
              )}

              {llmStatus.response && (
                <div className="flex items-start p-4 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800/50 rounded-lg">
                  <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400 mr-3 flex-shrink-0 mt-0.5" />
                  <span className="text-emerald-800 dark:text-emerald-200 text-sm">Response: {llmStatus.response}</span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

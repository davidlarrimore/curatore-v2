// components/admin/SystemSettingsPanel.tsx
'use client'

import { useState, useEffect } from 'react'
import { systemApi } from '@/lib/api'
import {
  RefreshCw,
  Loader2,
  Cpu,
  Search,
  BrainCircuit,
  ListTodo,
  HardDrive,
  Globe,
  Landmark,
  Mail,
  AlertTriangle,
  CheckCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/Button'

/* ------------------------------------------------------------------ */
/* Helper components                                                   */
/* ------------------------------------------------------------------ */

function ConfigRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between py-1.5 text-sm border-b border-gray-100 dark:border-gray-800 last:border-b-0">
      <span className="text-gray-500 dark:text-gray-400 font-medium">{label}</span>
      <span className="text-gray-900 dark:text-white text-right font-mono">{value ?? '—'}</span>
    </div>
  )
}

function ConfigSection({
  icon,
  title,
  badge,
  children,
  gradient,
}: {
  icon: React.ReactNode
  title: string
  badge?: React.ReactNode
  children: React.ReactNode
  gradient: string
}) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm overflow-hidden">
      <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-200 dark:border-gray-800">
        <div className={`w-9 h-9 rounded-lg ${gradient} flex items-center justify-center text-white shadow`}>
          {icon}
        </div>
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white flex-1">{title}</h3>
        {badge}
      </div>
      <div className="px-5 py-3">{children}</div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Section renderers                                                   */
/* ------------------------------------------------------------------ */

const SECTION_ORDER = [
  'embedding',
  'search',
  'llm_routing',
  'queue',
  'storage',
  'playwright',
  'sam',
  'email',
] as const

type SectionKey = (typeof SECTION_ORDER)[number]

const SECTION_META: Record<
  SectionKey,
  { title: string; icon: React.ReactNode; gradient: string }
> = {
  embedding: {
    title: 'Embedding & Indexing',
    icon: <Cpu className="w-4 h-4" />,
    gradient: 'bg-gradient-to-br from-violet-500 to-purple-600',
  },
  search: {
    title: 'Search Configuration',
    icon: <Search className="w-4 h-4" />,
    gradient: 'bg-gradient-to-br from-blue-500 to-cyan-500',
  },
  llm_routing: {
    title: 'LLM Task Routing',
    icon: <BrainCircuit className="w-4 h-4" />,
    gradient: 'bg-gradient-to-br from-amber-500 to-orange-500',
  },
  queue: {
    title: 'Queue',
    icon: <ListTodo className="w-4 h-4" />,
    gradient: 'bg-gradient-to-br from-emerald-500 to-teal-500',
  },
  storage: {
    title: 'Object Storage',
    icon: <HardDrive className="w-4 h-4" />,
    gradient: 'bg-gradient-to-br from-sky-500 to-blue-600',
  },
  playwright: {
    title: 'Playwright',
    icon: <Globe className="w-4 h-4" />,
    gradient: 'bg-gradient-to-br from-pink-500 to-rose-500',
  },
  sam: {
    title: 'SAM.gov',
    icon: <Landmark className="w-4 h-4" />,
    gradient: 'bg-gradient-to-br from-indigo-500 to-purple-500',
  },
  email: {
    title: 'Email',
    icon: <Mail className="w-4 h-4" />,
    gradient: 'bg-gradient-to-br from-teal-500 to-emerald-500',
  },
}

function renderEmbeddingSection(data: Record<string, any>) {
  const mismatch = data.config_matches_stored === false
  const badge = mismatch ? (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300">
      <AlertTriangle className="w-3 h-3" />
      Config Changed
    </span>
  ) : data.config_matches_stored === true ? (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300">
      <CheckCircle className="w-3 h-3" />
      In Sync
    </span>
  ) : null

  return { badge, body: (
    <>
      <ConfigRow label="Model" value={data.model} />
      <ConfigRow label="Dimensions" value={data.dimensions} />
      {data.stored_config && (
        <>
          <ConfigRow label="Stored Model" value={data.stored_config.model} />
          <ConfigRow label="Stored Dimensions" value={data.stored_config.dimensions} />
        </>
      )}
      {mismatch && (
        <div className="mt-3 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/50 text-xs text-amber-800 dark:text-amber-300">
          The current embedding configuration differs from what was used when documents were last indexed.
          A reindex may be required for consistent search results.
        </div>
      )}
    </>
  )}
}

function renderSearchSection(data: Record<string, any>) {
  return { badge: null, body: (
    <>
      <ConfigRow label="Enabled" value={data.enabled ? 'Yes' : 'No'} />
      <ConfigRow label="Mode" value={data.default_mode} />
      <ConfigRow label="Semantic Weight" value={data.semantic_weight} />
      <ConfigRow label="Chunk Size" value={data.chunk_size} />
      <ConfigRow label="Chunk Overlap" value={data.chunk_overlap} />
      <ConfigRow label="Batch Size" value={data.batch_size} />
      <ConfigRow label="Max Content Length" value={data.max_content_length?.toLocaleString()} />
    </>
  )}
}

function renderLLMSection(data: Record<string, any>) {
  return { badge: null, body: (
    <>
      <ConfigRow label="Provider" value={data.provider} />
      <ConfigRow label="Default Model" value={data.default_model} />
      <ConfigRow label="Base URL" value={data.base_url} />
      <ConfigRow label="Timeout" value={`${data.timeout}s`} />
      <ConfigRow label="Max Retries" value={data.max_retries} />
      <ConfigRow label="Verify SSL" value={data.verify_ssl ? 'Yes' : 'No'} />
      {data.task_types && data.task_types.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2 uppercase tracking-wider">Task Types</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700">
                  <th className="text-left py-1.5 pr-3 font-semibold text-gray-600 dark:text-gray-400">Type</th>
                  <th className="text-left py-1.5 pr-3 font-semibold text-gray-600 dark:text-gray-400">Model</th>
                  <th className="text-right py-1.5 pr-3 font-semibold text-gray-600 dark:text-gray-400">Temp</th>
                  <th className="text-right py-1.5 font-semibold text-gray-600 dark:text-gray-400">Dims</th>
                </tr>
              </thead>
              <tbody>
                {data.task_types.map((tt: any) => (
                  <tr key={tt.task_type} className="border-b border-gray-100 dark:border-gray-800 last:border-b-0">
                    <td className="py-1.5 pr-3 font-medium text-gray-900 dark:text-white">{tt.task_type}</td>
                    <td className="py-1.5 pr-3 font-mono text-gray-700 dark:text-gray-300">{tt.model}</td>
                    <td className="py-1.5 pr-3 text-right text-gray-700 dark:text-gray-300">{tt.temperature ?? '—'}</td>
                    <td className="py-1.5 text-right text-gray-700 dark:text-gray-300">{tt.dimensions ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )}
}

function renderGenericSection(data: Record<string, any>) {
  return { badge: null, body: (
    <>
      {Object.entries(data).map(([key, val]) => (
        <ConfigRow
          key={key}
          label={key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
          value={typeof val === 'boolean' ? (val ? 'Yes' : 'No') : String(val ?? '—')}
        />
      ))}
    </>
  )}
}

function renderSection(key: SectionKey, data: Record<string, any>): { badge: React.ReactNode; body: React.ReactNode } {
  switch (key) {
    case 'embedding':
      return renderEmbeddingSection(data)
    case 'search':
      return renderSearchSection(data)
    case 'llm_routing':
      return renderLLMSection(data)
    default:
      return renderGenericSection(data)
  }
}

/* ------------------------------------------------------------------ */
/* Main panel                                                          */
/* ------------------------------------------------------------------ */

export default function SystemSettingsPanel() {
  const [settings, setSettings] = useState<Record<string, any> | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const data = await systemApi.getSystemSettings()
      setSettings(data)
    } catch (err: any) {
      console.error('Failed to load system settings:', err)
      setError(err.message || 'Failed to load system settings')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 text-indigo-500 animate-spin" />
        <span className="ml-3 text-gray-600 dark:text-gray-400">Loading system settings...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-4">
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
          <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
        </div>
        <Button variant="secondary" size="sm" onClick={load}>
          Retry
        </Button>
      </div>
    )
  }

  if (!settings) return null

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
            System Configuration
          </h2>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Read-only view of settings from config.yml
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={load}
          className="flex items-center space-x-2"
        >
          <RefreshCw className="w-4 h-4" />
          <span>Refresh</span>
        </Button>
      </div>

      {/* Section cards */}
      <div className="grid grid-cols-1 gap-4">
        {SECTION_ORDER.filter((key) => settings[key]).map((key) => {
          const meta = SECTION_META[key]
          const { badge, body } = renderSection(key, settings[key])
          return (
            <ConfigSection
              key={key}
              icon={meta.icon}
              title={meta.title}
              gradient={meta.gradient}
              badge={badge}
            >
              {body}
            </ConfigSection>
          )
        })}
      </div>

      {/* Info box */}
      <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg className="h-5 w-5 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
            </svg>
          </div>
          <div className="ml-3">
            <h3 className="text-sm font-medium text-blue-800 dark:text-blue-200">
              About System Settings
            </h3>
            <div className="mt-2 text-sm text-blue-700 dark:text-blue-300">
              <ul className="list-disc list-inside space-y-1">
                <li>Settings are loaded from <code className="bg-blue-100 dark:bg-blue-900/50 px-1 py-0.5 rounded text-xs">config.yml</code> and are read-only</li>
                <li>API keys, passwords, and other secrets are never exposed</li>
                <li>If the embedding config has changed since documents were last indexed, a warning will appear</li>
                <li>To change settings, update <code className="bg-blue-100 dark:bg-blue-900/50 px-1 py-0.5 rounded text-xs">config.yml</code> and restart the backend</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

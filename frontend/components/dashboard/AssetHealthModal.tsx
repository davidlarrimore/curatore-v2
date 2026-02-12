'use client'

import { Fragment } from 'react'
import { Dialog, Transition } from '@headlessui/react'
import { HeartPulse, X, ExternalLink } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { Button } from '@/components/ui/Button'
import type { CollectionHealth } from '@/lib/api'

interface AssetHealthModalProps {
  isOpen: boolean
  onClose: () => void
  health: CollectionHealth
}

export function AssetHealthModal({ isOpen, onClose, health }: AssetHealthModalProps) {
  const router = useRouter()

  const { ready, pending, failed, inactive } = health.status_breakdown
  const total = health.total_assets
  const coverage = health.extraction_coverage

  const coverageColor =
    coverage >= 90 ? 'from-emerald-500 to-teal-500' :
    coverage >= 70 ? 'from-amber-500 to-orange-500' :
    'from-red-500 to-rose-500'

  const coverageTextColor =
    coverage >= 90 ? 'text-emerald-600 dark:text-emerald-400' :
    coverage >= 70 ? 'text-amber-600 dark:text-amber-400' :
    'text-red-600 dark:text-red-400'

  // Donut chart via conic-gradient
  const segments = [
    { value: ready, color: '#10b981' },   // emerald-500
    { value: pending, color: '#f59e0b' },  // amber-500
    { value: failed, color: '#ef4444' },   // red-500
    { value: inactive, color: '#9ca3af' }, // gray-400
  ]

  let conicStops = ''
  let cumulative = 0
  if (total > 0) {
    for (const seg of segments) {
      const pct = (seg.value / total) * 100
      conicStops += `${seg.color} ${cumulative}% ${cumulative + pct}%, `
      cumulative += pct
    }
    conicStops = conicStops.slice(0, -2)
  } else {
    conicStops = '#e5e7eb 0% 100%'
  }

  const formatDate = (dateString: string | null) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString()
  }

  return (
    <Transition.Root show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-300"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-200"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-gray-900/80 backdrop-blur-sm transition-opacity" />
        </Transition.Child>

        <div className="fixed inset-0 z-10 overflow-y-auto">
          <div className="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
            <Transition.Child
              as={Fragment}
              enter="ease-out duration-300"
              enterFrom="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
              enterTo="opacity-100 translate-y-0 sm:scale-100"
              leave="ease-in duration-200"
              leaveFrom="opacity-100 translate-y-0 sm:scale-100"
              leaveTo="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
            >
              <Dialog.Panel className="relative transform overflow-hidden rounded-xl bg-white dark:bg-gray-800 px-4 pb-4 pt-5 text-left shadow-2xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:p-6">
                {/* Close button */}
                <div className="absolute right-0 top-0 pr-4 pt-4">
                  <button
                    type="button"
                    className="rounded-lg p-1 text-gray-400 hover:text-gray-500 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    onClick={onClose}
                  >
                    <span className="sr-only">Close</span>
                    <X className="h-5 w-5" aria-hidden="true" />
                  </button>
                </div>

                {/* Header */}
                <div className="flex items-center gap-3 mb-6">
                  <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center text-white shadow-lg shadow-violet-500/25">
                    <HeartPulse className="w-5 h-5" />
                  </div>
                  <Dialog.Title as="h3" className="text-lg font-semibold text-gray-900 dark:text-white">
                    Asset Health
                  </Dialog.Title>
                </div>

                {/* Extraction Coverage */}
                <div className="mb-6">
                  <div className="flex items-baseline justify-between mb-2">
                    <span className="text-sm font-medium text-gray-500 dark:text-gray-400">Extraction Coverage</span>
                    <span className={`text-2xl font-bold ${coverageTextColor}`}>{coverage}%</span>
                  </div>
                  <div className="w-full h-3 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full bg-gradient-to-r ${coverageColor} transition-all duration-500`}
                      style={{ width: `${coverage}%` }}
                    />
                  </div>
                </div>

                {/* Status Breakdown */}
                <div className="mb-6">
                  <h4 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-3">Status Breakdown</h4>
                  <div className="flex items-center gap-6">
                    {/* Donut */}
                    <div className="relative w-32 h-32 flex-shrink-0">
                      <div
                        className="w-full h-full rounded-full"
                        style={{
                          background: `conic-gradient(${conicStops})`,
                        }}
                      />
                      <div className="absolute inset-3 rounded-full bg-white dark:bg-gray-800 flex items-center justify-center">
                        <div className="text-center">
                          <div className="text-xl font-bold text-gray-900 dark:text-white">{total}</div>
                          <div className="text-xs text-gray-500 dark:text-gray-400">total</div>
                        </div>
                      </div>
                    </div>

                    {/* Legend */}
                    <div className="flex-1 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="w-3 h-3 rounded-full bg-emerald-500" />
                          <span className="text-sm text-gray-600 dark:text-gray-300">Ready</span>
                        </div>
                        <span className="text-sm font-semibold text-gray-900 dark:text-white">{ready}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="w-3 h-3 rounded-full bg-amber-500" />
                          <span className="text-sm text-gray-600 dark:text-gray-300">Pending</span>
                        </div>
                        <span className="text-sm font-semibold text-gray-900 dark:text-white">{pending}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="w-3 h-3 rounded-full bg-red-500" />
                          <span className="text-sm text-gray-600 dark:text-gray-300">Failed</span>
                        </div>
                        <span className="text-sm font-semibold text-gray-900 dark:text-white">{failed}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="w-3 h-3 rounded-full bg-gray-400" />
                          <span className="text-sm text-gray-600 dark:text-gray-300">Inactive</span>
                        </div>
                        <span className="text-sm font-semibold text-gray-900 dark:text-white">{inactive}</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Version Stats */}
                <div className="mb-6">
                  <h4 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-3">Version Stats</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="bg-gradient-to-br from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-lg p-3">
                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Multi-Version Assets</p>
                      <p className="text-xl font-bold text-gray-900 dark:text-white">
                        {health.version_stats.multi_version_assets}
                      </p>
                    </div>
                    <div className="bg-gradient-to-br from-blue-50 to-cyan-50 dark:from-blue-900/20 dark:to-cyan-900/20 rounded-lg p-3">
                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Total Versions</p>
                      <p className="text-xl font-bold text-gray-900 dark:text-white">
                        {health.version_stats.total_versions}
                      </p>
                    </div>
                  </div>
                </div>

                {/* Last Updated */}
                <div className="mb-5 pt-3 border-t border-gray-100 dark:border-gray-700">
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Last updated: {formatDate(health.last_updated)}
                  </p>
                </div>

                {/* Actions */}
                <div className="flex items-center justify-between">
                  <div>
                    {failed > 0 && (
                      <button
                        onClick={() => {
                          onClose()
                          router.push('/assets?status=failed')
                        }}
                        className="inline-flex items-center gap-1.5 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 transition-colors"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        View Failed Assets
                      </button>
                    )}
                  </div>
                  <Button variant="secondary" onClick={onClose}>
                    Close
                  </Button>
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition.Root>
  )
}

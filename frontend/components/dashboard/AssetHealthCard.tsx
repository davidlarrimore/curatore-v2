'use client'

import { useState } from 'react'
import { HeartPulse, FileText, ShieldCheck, AlertTriangle, Loader2 } from 'lucide-react'
import type { CollectionHealth } from '@/lib/api'
import { AssetHealthModal } from './AssetHealthModal'

interface AssetHealthCardProps {
  health: CollectionHealth | null
  isLoading: boolean
}

export function AssetHealthCard({ health, isLoading }: AssetHealthCardProps) {
  const [isModalOpen, setIsModalOpen] = useState(false)

  const coverage = health?.extraction_coverage ?? 0
  const failed = health?.status_breakdown.failed ?? 0

  const statusBarColor =
    coverage >= 90 ? 'from-emerald-500 to-teal-500' :
    coverage >= 70 ? 'from-amber-500 to-orange-500' :
    'from-red-500 to-rose-500'

  const coverageTileColor =
    coverage >= 90
      ? 'from-emerald-50 to-teal-50 dark:from-emerald-900/20 dark:to-teal-900/20'
      : coverage >= 70
      ? 'from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/20'
      : 'from-red-50 to-rose-50 dark:from-red-900/20 dark:to-rose-900/20'

  const coverageIconColor =
    coverage >= 90 ? 'text-emerald-500 dark:text-emerald-400' :
    coverage >= 70 ? 'text-amber-500 dark:text-amber-400' :
    'text-red-500 dark:text-red-400'

  const failedTileColor = failed === 0
    ? 'from-emerald-50 to-teal-50 dark:from-emerald-900/20 dark:to-teal-900/20'
    : 'from-red-50 to-rose-50 dark:from-red-900/20 dark:to-rose-900/20'

  const failedIconColor = failed === 0
    ? 'text-emerald-500 dark:text-emerald-400'
    : 'text-red-500 dark:text-red-400'

  // Compact proportional status bar
  const total = health?.total_assets ?? 0
  const ready = health?.status_breakdown.ready ?? 0
  const pending = health?.status_breakdown.pending ?? 0
  const inactive = health?.status_breakdown.inactive ?? 0

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden hover:shadow-lg hover:shadow-gray-200/50 dark:hover:shadow-gray-900/50 transition-all duration-200">
      {/* Status bar at top */}
      <div className={`h-1 bg-gradient-to-r ${health ? statusBarColor : 'from-gray-300 to-gray-400'}`} />

      <div className="p-5">
        {/* Header */}
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center text-white shadow-lg shadow-violet-500/25">
            <HeartPulse className="w-5 h-5" />
          </div>
          <div className="flex-1">
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">Asset Health</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">Document collection status</p>
          </div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 text-gray-400 animate-spin" />
          </div>
        ) : health && total > 0 ? (
          <>
            {/* 3-column stat grid */}
            <div className="grid grid-cols-3 gap-3 mb-4">
              {/* Total Assets */}
              <div className="bg-gradient-to-br from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-lg p-3">
                <div className="flex items-center gap-1.5 mb-1">
                  <FileText className="w-3.5 h-3.5 text-indigo-500 dark:text-indigo-400" />
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Total</span>
                </div>
                <p className="text-lg font-bold text-gray-900 dark:text-white">
                  {total.toLocaleString()}
                </p>
              </div>

              {/* Coverage */}
              <div className={`bg-gradient-to-br ${coverageTileColor} rounded-lg p-3`}>
                <div className="flex items-center gap-1.5 mb-1">
                  <ShieldCheck className={`w-3.5 h-3.5 ${coverageIconColor}`} />
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Coverage</span>
                </div>
                <p className="text-lg font-bold text-gray-900 dark:text-white">
                  {coverage}%
                </p>
              </div>

              {/* Failed */}
              <div className={`bg-gradient-to-br ${failedTileColor} rounded-lg p-3`}>
                <div className="flex items-center gap-1.5 mb-1">
                  <AlertTriangle className={`w-3.5 h-3.5 ${failedIconColor}`} />
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Failed</span>
                </div>
                <p className="text-lg font-bold text-gray-900 dark:text-white">
                  {failed}
                </p>
              </div>
            </div>

            {/* Compact status bar */}
            {total > 0 && (
              <div className="mb-4">
                <div className="flex w-full h-2 rounded-full overflow-hidden bg-gray-100 dark:bg-gray-700">
                  {ready > 0 && (
                    <div
                      className="bg-emerald-500 transition-all duration-500"
                      style={{ width: `${(ready / total) * 100}%` }}
                      title={`Ready: ${ready}`}
                    />
                  )}
                  {pending > 0 && (
                    <div
                      className="bg-amber-500 transition-all duration-500"
                      style={{ width: `${(pending / total) * 100}%` }}
                      title={`Pending: ${pending}`}
                    />
                  )}
                  {failed > 0 && (
                    <div
                      className="bg-red-500 transition-all duration-500"
                      style={{ width: `${(failed / total) * 100}%` }}
                      title={`Failed: ${failed}`}
                    />
                  )}
                  {inactive > 0 && (
                    <div
                      className="bg-gray-400 transition-all duration-500"
                      style={{ width: `${(inactive / total) * 100}%` }}
                      title={`Inactive: ${inactive}`}
                    />
                  )}
                </div>
                <div className="flex items-center gap-3 mt-1.5">
                  <div className="flex items-center gap-1">
                    <div className="w-2 h-2 rounded-full bg-emerald-500" />
                    <span className="text-[10px] text-gray-500 dark:text-gray-400">Ready</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <div className="w-2 h-2 rounded-full bg-amber-500" />
                    <span className="text-[10px] text-gray-500 dark:text-gray-400">Pending</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <div className="w-2 h-2 rounded-full bg-red-500" />
                    <span className="text-[10px] text-gray-500 dark:text-gray-400">Failed</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <div className="w-2 h-2 rounded-full bg-gray-400" />
                    <span className="text-[10px] text-gray-500 dark:text-gray-400">Inactive</span>
                  </div>
                </div>
              </div>
            )}

            {/* View Details link */}
            <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
              <button
                onClick={() => setIsModalOpen(true)}
                className="text-sm font-medium text-violet-600 dark:text-violet-400 hover:text-violet-700 dark:hover:text-violet-300 transition-colors"
              >
                View Details
              </button>
            </div>
          </>
        ) : (
          <div className="text-sm text-gray-500 dark:text-gray-400 py-4">
            No assets in collection yet.
          </div>
        )}
      </div>

      {/* Modal */}
      {health && (
        <AssetHealthModal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          health={health}
        />
      )}
    </div>
  )
}

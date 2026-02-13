import { Loader2 } from 'lucide-react'

/**
 * Loading state for org-scoped routes.
 * Shows a full-screen loading overlay while the page is loading.
 */
export default function OrgLoading() {
  return (
    <div className="fixed inset-0 bg-white/80 dark:bg-gray-900/80 flex items-center justify-center z-50">
      <div className="flex flex-col items-center gap-3">
        <Loader2 className="w-8 h-8 animate-spin text-indigo-600" />
        <p className="text-sm text-gray-600 dark:text-gray-400">Loading...</p>
      </div>
    </div>
  )
}

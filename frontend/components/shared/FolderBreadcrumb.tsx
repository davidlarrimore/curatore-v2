'use client'

import { ChevronRight, Folder, Home } from 'lucide-react'

interface FolderBreadcrumbProps {
  bucket: string
  bucketDisplayName?: string
  prefix: string
  onNavigate: (path: string) => void
  /** Map of raw segment values to display labels (e.g., org UUID → slug) */
  segmentLabelMap?: Record<string, string>
  /** Segments to hide from the breadcrumb (e.g., org UUID when in org context) */
  hideSegments?: string[]
}

export default function FolderBreadcrumb({
  bucket,
  bucketDisplayName,
  prefix,
  onNavigate,
  segmentLabelMap,
  hideSegments,
}: FolderBreadcrumbProps) {
  // Parse prefix into path segments, filtering out hidden segments
  const allSegments = prefix
    .split('/')
    .filter((s) => s.length > 0)

  const segments = hideSegments
    ? allSegments.filter((s) => !hideSegments.includes(s))
    : allSegments

  // Build breadcrumb items from prefix segments only (bucket is shown in the dropdown)
  // Recalculate paths to include hidden segments in the actual path
  const items = segments.map((segment, index) => {
    // Find the actual index in allSegments to build the correct path
    const actualIndex = allSegments.indexOf(segment)
    return {
      label: segmentLabelMap?.[segment] ?? segment,
      path: allSegments.slice(0, actualIndex + 1).join('/') + '/',
      isRoot: index === 0,
    }
  })

  // If no prefix segments, show a single root item for the bucket
  if (items.length === 0) {
    items.push({
      label: bucketDisplayName || bucket,
      path: '',
      isRoot: true,
    })
  }

  return (
    <nav className="flex items-center space-x-1 text-sm overflow-x-auto">
      {items.map((item, index) => (
        <div key={item.path} className="flex items-center">
          {index > 0 && (
            <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0 mx-1" />
          )}
          <button
            onClick={() => onNavigate(item.path)}
            className={`flex items-center gap-1.5 px-2 py-1 rounded-md transition-colors whitespace-nowrap ${
              index === items.length - 1
                ? 'bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 font-medium'
                : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-900 dark:hover:text-gray-200'
            }`}
          >
            {item.isRoot ? (
              <Home className="w-3.5 h-3.5" />
            ) : (
              <Folder className="w-3.5 h-3.5" />
            )}
            <span className="truncate max-w-[150px]">{item.label}</span>
          </button>
        </div>
      ))}
    </nav>
  )
}

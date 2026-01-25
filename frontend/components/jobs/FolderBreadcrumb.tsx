'use client'

import React from 'react'
import { ChevronRight, Home } from 'lucide-react'

interface FolderBreadcrumbProps {
  bucket: string
  bucketDisplayName: string
  prefix: string
  onNavigate: (prefix: string) => void
}

export default function FolderBreadcrumb({
  bucket,
  bucketDisplayName,
  prefix,
  onNavigate,
}: FolderBreadcrumbProps) {
  // Parse prefix into path segments
  const segments = prefix
    .split('/')
    .filter(Boolean)

  // Build breadcrumb items
  const items = [
    { label: bucketDisplayName, path: '', isRoot: true },
    ...segments.map((segment, index) => ({
      label: segment,
      path: segments.slice(0, index + 1).join('/') + '/',
      isRoot: false,
    })),
  ]

  return (
    <nav className="flex items-center gap-1 text-sm overflow-x-auto">
      {items.map((item, index) => (
        <React.Fragment key={item.path}>
          {index > 0 && (
            <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />
          )}
          <button
            onClick={() => onNavigate(item.path)}
            className={`flex items-center gap-1.5 px-2 py-1 rounded-md transition-colors flex-shrink-0 ${
              index === items.length - 1
                ? 'text-indigo-600 dark:text-indigo-400 font-medium bg-indigo-50 dark:bg-indigo-900/20'
                : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
          >
            {item.isRoot && <Home className="w-4 h-4" />}
            <span className="truncate max-w-[150px]">{item.label}</span>
          </button>
        </React.Fragment>
      ))}
    </nav>
  )
}

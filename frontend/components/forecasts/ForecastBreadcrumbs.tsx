'use client'

import Link from 'next/link'
import { ChevronRight, Home } from 'lucide-react'

export interface BreadcrumbItem {
  label: string
  href?: string
}

interface ForecastBreadcrumbsProps {
  items: BreadcrumbItem[]
}

export default function ForecastBreadcrumbs({ items }: ForecastBreadcrumbsProps) {
  return (
    <nav className="flex items-center gap-1.5 text-sm mb-4">
      <Link
        href="/"
        className="flex items-center gap-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
      >
        <Home className="w-4 h-4" />
      </Link>
      <ChevronRight className="w-4 h-4 text-gray-300 dark:text-gray-600" />
      <Link
        href="/forecasts"
        className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
      >
        Forecasts
      </Link>
      {items.map((item, index) => (
        <span key={index} className="flex items-center gap-1.5">
          <ChevronRight className="w-4 h-4 text-gray-300 dark:text-gray-600" />
          {item.href ? (
            <Link
              href={item.href}
              className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
            >
              {item.label}
            </Link>
          ) : (
            <span className="text-gray-900 dark:text-white font-medium truncate max-w-xs">
              {item.label}
            </span>
          )}
        </span>
      ))}
    </nav>
  )
}

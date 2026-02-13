'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useOrgUrl } from '@/lib/org-url-context'
import {
  LayoutDashboard,
  Settings,
  FileText,
  Building2,
} from 'lucide-react'

interface NavItem {
  path: string
  label: string
  icon: React.ElementType
  exact?: boolean
}

const navItems: NavItem[] = [
  { path: '/syncs/sam', label: 'Dashboard', icon: LayoutDashboard, exact: true },
  { path: '/syncs/sam/setup', label: 'Setup', icon: Settings },
  { path: '/syncs/sam/notices', label: 'Notices', icon: FileText },
  { path: '/syncs/sam/solicitations', label: 'Solicitations', icon: Building2 },
]

export default function SamNavigation() {
  const pathname = usePathname()
  const { orgSlug } = useOrgUrl()

  const orgUrl = (path: string) => `/orgs/${orgSlug}${path}`

  const isActive = (item: NavItem) => {
    const href = orgUrl(item.path)
    if (item.exact) {
      return pathname === href
    }
    return pathname.startsWith(href)
  }

  return (
    <div className="flex flex-wrap items-center gap-2 mb-6">
      {navItems.map((item) => {
        const Icon = item.icon
        const active = isActive(item)

        return (
          <Link
            key={item.path}
            href={orgUrl(item.path)}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              active
                ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 shadow-sm'
                : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white'
            }`}
          >
            <Icon className="w-4 h-4" />
            <span>{item.label}</span>
          </Link>
        )
      })}
    </div>
  )
}
